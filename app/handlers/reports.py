from datetime import datetime

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.clients.deadlock_api import DeadlockApiClient, DeadlockApiError, DeadlockApiNotFoundError, DeadlockApiTemporaryError
from app.keyboards.inline import report_actions_keyboard
from app.models import MatchSummary
from app.repositories.matches import MatchesRepository
from app.repositories.players import TrackedPlayersRepository
from app.services.analytics import AnalyticsService
from app.services.cards import CardRenderer
from app.services.heroes import hero_name_by_id

router = Router()


def _steam_link(profile: dict[str, str], api: DeadlockApiClient) -> str:
    account_id = str(profile.get("account_id") or "")
    name = str(profile.get("personaname") or f"Игрок {account_id}")
    url = profile.get("profile_url") or f"https://steamcommunity.com/profiles/{api.account_id_to_steam64(account_id)}"
    return f'<a href="{url}">{name}</a>'


def _pick_account_from_text(message_text: str) -> str | None:
    args = (message_text or "").split(maxsplit=1)
    return args[1].strip() if len(args) > 1 else None


async def _resolve_profile_line(api: DeadlockApiClient, account_id: str) -> tuple[str, str | None]:
    profiles = await api.get_steam_profiles([account_id])
    if profiles:
        mapped = api._map_steam_profile(profiles[0])
        return _steam_link(mapped, api), mapped.get("profile_url")
    return f"Игрок <code>{account_id}</code>", None


def setup_reports_dependencies(
    bot: Bot,
    api: DeadlockApiClient,
    players_repo: TrackedPlayersRepository,
    matches_repo: MatchesRepository,
    analytics: AnalyticsService,
    cards: CardRenderer,
) -> None:
    router.bot = bot  # type: ignore[attr-defined]
    router.api = api  # type: ignore[attr-defined]
    router.players_repo = players_repo  # type: ignore[attr-defined]
    router.matches_repo = matches_repo  # type: ignore[attr-defined]
    router.analytics = analytics  # type: ignore[attr-defined]
    router.cards = cards  # type: ignore[attr-defined]


async def _send_profile(message: Message, player_id: str) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    matches_repo: MatchesRepository = router.matches_repo  # type: ignore[attr-defined]

    account_id = api.normalize_account_id(player_id)
    local_recent = matches_repo.get_recent_player_matches(account_id, 20)
    if local_recent:
        summaries = local_recent
    else:
        history = await api.get_player_recent_matches(account_id, limit=20)
        summaries = []
        for item in history:
            parsed = api.parse_match_for_player(item, account_id)
            summary = MatchSummary(
                match_id=parsed["match_id"] or "unknown",
                match_datetime=datetime.fromisoformat(parsed["match_datetime"].replace("Z", "+00:00")),
                hero_name=parsed["hero_name"],
                is_win=parsed["is_win"],
                kills=parsed["kills"],
                deaths=parsed["deaths"],
                assists=parsed["assists"],
                souls=parsed["souls"],
                damage=parsed["damage"],
                duration_seconds=parsed["duration_seconds"],
                items=parsed["items"],
                raw_payload=parsed.get("raw_payload"),
            )
            matches_repo.store_player_match_history(account_id, summary)
            summaries.append(summary)

    hero_stats = await api.get_player_hero_stats([account_id])
    mmr_stats = await api.get_player_mmr([account_id])
    steam_line, _ = await _resolve_profile_line(api, account_id)

    if not summaries:
        await message.answer(f"{steam_line}\nНет данных матчей для профиля.", parse_mode="HTML")
        return

    matches_count = len(summaries)
    avg_kda = sum((m.kills + m.assists) / max(m.deaths, 1) for m in summaries) / matches_count
    avg_souls = sum(m.souls for m in summaries) / matches_count
    avg_last_hits = sum(int((m.raw_payload or {}).get("last_hits") or 0) for m in summaries) / matches_count
    wins = sum(1 for m in summaries if m.is_win)

    top_heroes = sorted(
        hero_stats,
        key=lambda item: int(item.get("matches_played") or item.get("matches") or 0),
        reverse=True,
    )[:3]
    top_heroes_text = ", ".join(
        f"{hero_name_by_id(item.get('hero_id'))} ({int(item.get('matches_played') or item.get('matches') or 0)})"
        for item in top_heroes
    ) or "—"

    best_hero = max(
        hero_stats,
        key=lambda item: (float(item.get("winrate") or 0), int(item.get("matches_played") or item.get("matches") or 0)),
        default=None,
    )
    best_hero_text = hero_name_by_id(best_hero.get("hero_id")) if best_hero else "—"
    mmr = mmr_stats[0].get("mmr") if mmr_stats else "—"

    await message.answer(
        f"<b>Профиль игрока</b>\n"
        f"Игрок: {steam_line}\n"
        f"account_id: <code>{account_id}</code>\n"
        f"MMR: <b>{mmr}</b>\n"
        f"Последних матчей: <b>{matches_count}</b>\n"
        f"Winrate: <b>{(wins / matches_count) * 100:.1f}%</b>\n"
        f"Средний KDA: <b>{avg_kda:.2f}</b>\n"
        f"Средний net worth: <b>{avg_souls:.0f}</b>\n"
        f"Средние last hits: <b>{avg_last_hits:.1f}</b>\n"
        f"Частые герои: <b>{top_heroes_text}</b>\n"
        f"Лучший герой: <b>{best_hero_text}</b>",
        parse_mode="HTML",
    )


async def _send_last_match(message: Message, player_id: str) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    matches_repo: MatchesRepository = router.matches_repo  # type: ignore[attr-defined]
    analytics: AnalyticsService = router.analytics  # type: ignore[attr-defined]
    cards: CardRenderer = router.cards  # type: ignore[attr-defined]

    account_id = api.normalize_account_id(player_id)
    matches = await api.get_player_recent_matches(account_id, limit=20)
    if not matches:
        await message.answer("Не удалось получить матчи игрока.")
        return

    latest = matches[0]
    parsed = api.parse_match_for_player(latest, account_id)
    match_id = str(parsed["match_id"] or latest.get("match_id") or latest.get("id") or "unknown")

    summary = MatchSummary(
        match_id=match_id,
        match_datetime=datetime.fromisoformat(parsed["match_datetime"].replace("Z", "+00:00")),
        hero_name=parsed["hero_name"],
        is_win=parsed["is_win"],
        kills=parsed["kills"],
        deaths=parsed["deaths"],
        assists=parsed["assists"],
        souls=parsed["souls"],
        damage=parsed["damage"],
        duration_seconds=parsed["duration_seconds"],
        items=parsed["items"],
        raw_payload=parsed.get("raw_payload"),
    )
    matches_repo.store_player_match_history(account_id, summary)
    recent = matches_repo.get_recent_player_matches(account_id, 20)
    hero = matches_repo.get_recent_player_matches(account_id, 20, summary.hero_name)
    week = matches_repo.get_recent_player_matches(account_id, 100)
    analysis = analytics.analyze(summary, recent, hero, week)
    card_path = await cards.render(account_id, summary, analysis)

    await message.answer_photo(
        photo=FSInputFile(card_path),
        caption="Последний матч сформирован по /players/{account_id}/match-history.",
        reply_markup=report_actions_keyboard(account_id, summary.match_id),
    )


async def _send_relation_stats(message: Message, account_id: str, mode: str) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    if mode == "mates":
        raw = await api.get_player_mate_stats(account_id)
        title = "Частые тиммейты"
    else:
        raw = await api.get_player_enemy_stats(account_id)
        title = "Частые соперники"

    ids: list[str] = []
    for item in raw:
        other = item.get("account_id") or item.get("other_account_id") or item.get("player_account_id")
        if other is not None and str(other).isdigit():
            ids.append(api.normalize_account_id(other))

    steam_map = {entry["account_id"]: entry for entry in [api._map_steam_profile(p) for p in (await api.get_steam_profiles(ids) if ids else [])] if entry.get("account_id")}
    lines = [f"<b>{title}</b> для <code>{account_id}</code>"]
    for item in raw[:10]:
        other = item.get("account_id") or item.get("other_account_id") or item.get("player_account_id")
        if other is None or not str(other).isdigit():
            continue
        normalized = api.normalize_account_id(other)
        profile = steam_map.get(normalized, {"account_id": normalized, "personaname": f"Игрок {normalized}", "profile_url": None})
        wr = item.get("winrate")
        matches = item.get("matches") or item.get("games") or item.get("matches_played") or "?"
        lines.append(f"• {_steam_link(profile, api)} — матчей: <b>{matches}</b>, WR: <b>{wr if wr is not None else '—'}</b>")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    player_id = _pick_account_from_text(message.text or "")
    if not player_id:
        await message.answer("Использование: <code>/profile account_id</code>", parse_mode="HTML")
        return
    try:
        await _send_profile(message, player_id)
    except (DeadlockApiNotFoundError, DeadlockApiTemporaryError, DeadlockApiError):
        await message.answer("Не удалось собрать профиль. Проверьте account_id и доступность API.")


@router.message(Command("lastmatch"))
async def cmd_lastmatch(message: Message) -> None:
    player_id = _pick_account_from_text(message.text or "")
    if not player_id:
        await message.answer("Использование: <code>/lastmatch account_id</code>", parse_mode="HTML")
        return
    try:
        await _send_last_match(message, player_id)
    except (DeadlockApiNotFoundError, DeadlockApiTemporaryError, DeadlockApiError):
        await message.answer("Не удалось получить матч. Проверьте account_id и API.")


@router.message(Command("heroes"))
async def cmd_heroes(message: Message) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    player_id = _pick_account_from_text(message.text or "")
    if not player_id:
        await message.answer("Использование: <code>/heroes account_id</code>", parse_mode="HTML")
        return
    account_id = api.normalize_account_id(player_id)
    stats = await api.get_player_hero_stats([account_id])
    if not stats:
        await message.answer("Нет hero-stats для этого игрока.")
        return
    lines = [f"<b>Герои игрока</b> <code>{account_id}</code>"]
    for item in stats[:12]:
        lines.append(
            f"• <b>{hero_name_by_id(item.get('hero_id'))}</b>: матчей {item.get('matches_played') or item.get('matches') or 0}, "
            f"wins {item.get('wins') or 0}, K/D/A {item.get('kills') or 0}/{item.get('deaths') or 0}/{item.get('assists') or 0}, "
            f"NPM {item.get('networth_per_min') or '—'}"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("besthero"))
async def cmd_besthero(message: Message) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    player_id = _pick_account_from_text(message.text or "")
    if not player_id:
        await message.answer("Использование: <code>/besthero account_id</code>", parse_mode="HTML")
        return
    stats = await api.get_player_hero_stats([api.normalize_account_id(player_id)])
    best = max(stats, key=lambda x: (float(x.get("winrate") or 0), int(x.get("matches_played") or 0)), default=None)
    if not best:
        await message.answer("Недостаточно данных по героям.")
        return
    await message.answer(
        f"Лучший герой: <b>{hero_name_by_id(best.get('hero_id'))}</b>\n"
        f"Матчей: <b>{best.get('matches_played') or best.get('matches') or 0}</b>\n"
        f"Winrate: <b>{best.get('winrate') or '—'}</b>",
        parse_mode="HTML",
    )


@router.message(Command("hero"))
async def cmd_hero(message: Message) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    args = (message.text or "").split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Использование: <code>/hero account_id hero_id</code>", parse_mode="HTML")
        return
    account_id = api.normalize_account_id(args[1])
    hero_id = args[2]
    stats = await api.get_player_hero_stats([account_id])
    item = next((x for x in stats if str(x.get("hero_id")) == hero_id), None)
    if not item:
        await message.answer("Статистика по этому герою не найдена.")
        return
    await message.answer(
        f"<b>{hero_name_by_id(item.get('hero_id'))}</b>\n"
        f"Матчей: {item.get('matches_played') or item.get('matches') or 0}\n"
        f"Wins: {item.get('wins') or 0}\n"
        f"K/D/A: {item.get('kills') or 0}/{item.get('deaths') or 0}/{item.get('assists') or 0}\n"
        f"Networth/min: {item.get('networth_per_min') or '—'}\n"
        f"Last hits/min: {item.get('last_hits_per_min') or '—'}\n"
        f"Damage/min: {item.get('damage_per_min') or '—'}\n"
        f"Accuracy: {item.get('accuracy') or '—'}\n"
        f"Crit shot rate: {item.get('crit_shot_rate') or '—'}",
        parse_mode="HTML",
    )


@router.message(Command("teammates"))
async def cmd_teammates(message: Message) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    player_id = _pick_account_from_text(message.text or "")
    if not player_id:
        await message.answer("Использование: <code>/teammates account_id</code>", parse_mode="HTML")
        return
    await _send_relation_stats(message, api.normalize_account_id(player_id), mode="mates")


@router.message(Command("enemies"))
async def cmd_enemies(message: Message) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    player_id = _pick_account_from_text(message.text or "")
    if not player_id:
        await message.answer("Использование: <code>/enemies account_id</code>", parse_mode="HTML")
        return
    await _send_relation_stats(message, api.normalize_account_id(player_id), mode="enemies")


@router.message(Command("party"))
async def cmd_party(message: Message) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    player_id = _pick_account_from_text(message.text or "")
    if not player_id:
        await message.answer("Использование: <code>/party account_id</code>", parse_mode="HTML")
        return
    account_id = api.normalize_account_id(player_id)
    stats = await api.get_player_party_stats(account_id)
    if not stats:
        await message.answer("Нет данных party-stats.")
        return
    total = sum(int(x.get("matches") or x.get("games") or 0) for x in stats)
    best = max(stats, key=lambda x: float(x.get("winrate") or 0), default={})
    await message.answer(
        f"<b>Пати-статистика</b> <code>{account_id}</code>\n"
        f"Всего пати-игр: <b>{total}</b>\n"
        f"Лучшая пати-связка (по WR): <b>{best.get('party_size') or best.get('size') or '—'}</b>\n"
        f"Winrate: <b>{best.get('winrate') or '—'}</b>",
        parse_mode="HTML",
    )


@router.message(Command("meta"))
async def cmd_meta(message: Message) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    meta = await api.get_global_hero_stats()
    top = sorted(meta, key=lambda x: float(x.get("winrate") or 0), reverse=True)[:10]
    lines = ["<b>Глобальная мета (top winrate)</b>"]
    for item in top:
        lines.append(f"• {hero_name_by_id(item.get('hero_id'))}: WR {item.get('winrate') or '—'}, Pick {item.get('pickrate') or '—'}")
    await message.answer("\n".join(lines), parse_mode="HTML")


def _filter_by_hero(data: list[dict], hero_id: str) -> list[dict]:
    return [item for item in data if str(item.get("hero_id") or item.get("source_hero_id") or item.get("hero")) == hero_id]


@router.message(Command("synergy"))
async def cmd_synergy(message: Message) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: <code>/synergy hero_id</code>", parse_mode="HTML")
        return
    hero_id = args[1].strip()
    stats = _filter_by_hero(await api.get_hero_synergy_stats(), hero_id)
    lines = [f"<b>Синергии для {hero_name_by_id(hero_id)}</b>"]
    for item in stats[:10]:
        partner_id = item.get("pair_hero_id") or item.get("target_hero_id") or item.get("hero_b_id")
        lines.append(f"• {hero_name_by_id(partner_id)} — {item.get('winrate') or item.get('score') or '—'}")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("counter"))
async def cmd_counter(message: Message) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: <code>/counter hero_id</code>", parse_mode="HTML")
        return
    hero_id = args[1].strip()
    stats = _filter_by_hero(await api.get_hero_counter_stats(), hero_id)
    lines = [f"<b>Контрпики для {hero_name_by_id(hero_id)}</b>"]
    for item in stats[:10]:
        counter_id = item.get("counter_hero_id") or item.get("target_hero_id") or item.get("hero_b_id")
        lines.append(f"• {hero_name_by_id(counter_id)} — {item.get('winrate') or item.get('score') or '—'}")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    args = (message.text or "").split(maxsplit=1)
    region = args[1].strip() if len(args) > 1 else "Europe"
    rows = await api.get_leaderboard(region)
    ids = [str(item.get("account_id")) for item in rows if item.get("account_id")]
    mapped_profiles = [api._map_steam_profile(x) for x in (await api.get_steam_profiles(ids) if ids else [])]
    steam = {entry["account_id"]: entry for entry in mapped_profiles if entry.get("account_id")}
    lines = [f"<b>Лидерборд {region}</b>"]
    for item in rows[:10]:
        acc = item.get("account_id")
        rank = item.get("rank") or item.get("position") or "?"
        mmr = item.get("mmr") or item.get("score") or "—"
        if acc and str(acc) in steam:
            lines.append(f"{rank}. {_steam_link(steam[str(acc)], api)} — MMR: <b>{mmr}</b>")
        else:
            lines.append(f"{rank}. <code>{acc}</code> — MMR: <b>{mmr}</b>")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.callback_query(lambda c: c.data and c.data.startswith("lm:"))
async def cb_lastmatch(callback: CallbackQuery) -> None:
    player_id = callback.data.split(":", maxsplit=1)[1]
    await _send_last_match(callback.message, player_id)
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("rp:"))
async def cb_profile_button(callback: CallbackQuery) -> None:
    player_id = callback.data.split(":", maxsplit=1)[1]
    await _send_profile(callback.message, player_id)
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("autoff:"))
async def cb_autoff(callback: CallbackQuery) -> None:
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]
    player_id = callback.data.split(":")[1]
    ok = players_repo.set_auto_reports(callback.from_user.id, player_id, False)
    await callback.answer("Автоотслеживание отключено." if ok else "Игрок не найден.")


@router.callback_query(lambda c: c.data and c.data.startswith("profile:"))
async def cb_profile(callback: CallbackQuery) -> None:
    player_id = callback.data.split(":")[1]
    await _send_profile(callback.message, player_id)
    await callback.answer()
