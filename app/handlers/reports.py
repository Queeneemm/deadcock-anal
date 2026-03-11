from datetime import datetime

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.clients.deadlock_api import DeadlockApiClient, DeadlockApiError, DeadlockApiNotFoundError, DeadlockApiTemporaryError
from app.keyboards.inline import player_select_keyboard, report_actions_keyboard
from app.models import MatchSummary
from app.repositories.matches import MatchesRepository
from app.repositories.players import TrackedPlayersRepository
from app.services.analytics import AnalyticsService
from app.services.cards import CardRenderer
from app.services.heroes import hero_name_by_id

router = Router()

RATE_LIMIT_MESSAGE = "Слишком много запросов к API Deadlock. Подожди несколько секунд и попробуй снова."
TEMPORARY_API_MESSAGE = "API Deadlock сейчас временно перегружено. Попробуй ещё раз через несколько секунд."
MATCH_HISTORY_TEMPORARY_MESSAGE = "История матчей временно недоступна. Попробуй позже."


async def _notify_temporary_api_issue(message: Message, callback: CallbackQuery | None = None) -> None:
    if callback:
        await callback.answer("API перегружено, попробуйте позже.", show_alert=False)
    await message.answer(TEMPORARY_API_MESSAGE)


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


def _extract_winrate(item: dict) -> float:
    if item.get("winrate") is not None:
        try:
            return float(item.get("winrate") or 0)
        except (TypeError, ValueError):
            return 0.0
    wins = int(item.get("wins") or 0)
    losses = int(item.get("losses") or 0)
    matches = int(item.get("matches_played") or item.get("matches") or wins + losses or 0)
    return round((wins / matches) * 100, 1) if matches > 0 else 0.0


def _format_winrate(item: dict) -> str:
    value = _extract_winrate(item)
    return f"{value:.1f}%" if value > 0 else "—"


def _format_mmr(mmr_item: dict | None) -> str:
    if not mmr_item:
        return "—"
    if mmr_item.get("mmr") is not None:
        return str(mmr_item.get("mmr"))
    rank = mmr_item.get("rank")
    division = mmr_item.get("division")
    tier = mmr_item.get("division_tier")
    score = mmr_item.get("player_score") or mmr_item.get("score")
    parts: list[str] = []
    if rank is not None and division is not None:
        rank_line = f"{rank}.{division}"
        if tier is not None:
            rank_line += f" (tier {tier})"
        parts.append(f"Ранг: {rank_line}")
    if score is not None:
        try:
            parts.append(f"Score: {float(score):.2f}")
        except (TypeError, ValueError):
            parts.append(f"Score: {score}")
    return " | ".join(parts) if parts else "—"


async def _resolve_command_account(message: Message, explicit_account: str | None, action: str) -> str | None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]

    if explicit_account:
        return api.normalize_account_id(explicit_account)

    tracked = players_repo.list_players(message.from_user.id)
    if not tracked:
        await message.answer("У вас нет сохранённых игроков. Добавьте через /addplayer.")
        return None
    if len(tracked) == 1:
        return tracked[0].player_id

    players = [(p.player_id, p.display_name) for p in tracked]
    await message.answer(
        "У вас несколько игроков. Выберите, по какому профилю выполнить команду:",
        reply_markup=player_select_keyboard(action, players),
    )
    return None


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
                hero_id=parsed.get("hero_id"),
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
        key=lambda item: (_extract_winrate(item), int(item.get("matches_played") or item.get("matches") or 0)),
        default=None,
    )
    best_hero_text = hero_name_by_id(best_hero.get("hero_id")) if best_hero else "—"
    mmr = _format_mmr(mmr_stats[0] if mmr_stats else None)

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
    latest = await api.get_last_match(account_id)
    if latest is None:
        await message.answer("История матчей пуста.")
        return

    parsed = api.parse_match_for_player(latest, account_id)
    match_id = str(parsed["match_id"] or latest.get("match_id") or latest.get("id") or "unknown")

    summary = MatchSummary(
        match_id=match_id,
        match_datetime=datetime.fromisoformat(parsed["match_datetime"].replace("Z", "+00:00")),
        hero_name=parsed["hero_name"],
        is_win=parsed["is_win"],
        hero_id=parsed.get("hero_id"),
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
        matches = item.get("matches") or item.get("games") or item.get("matches_played") or "?"
        lines.append(f"• {_steam_link(profile, api)} — матчей: <b>{matches}</b>, WR: <b>{_format_winrate(item)}</b>")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    player_id = await _resolve_command_account(message, _pick_account_from_text(message.text or ""), "profile")
    if not player_id:
        return
    try:
        await _send_profile(message, player_id)
    except DeadlockApiTemporaryError:
        await message.answer(RATE_LIMIT_MESSAGE)
    except (DeadlockApiNotFoundError, DeadlockApiError):
        await message.answer("Не удалось собрать профиль. Проверьте account_id и доступность API.")


@router.message(Command("lastmatch"))
async def cmd_lastmatch(message: Message) -> None:
    player_id = await _resolve_command_account(message, _pick_account_from_text(message.text or ""), "lastmatch")
    if not player_id:
        return
    try:
        await _send_last_match(message, player_id)
    except DeadlockApiTemporaryError:
        await message.answer(MATCH_HISTORY_TEMPORARY_MESSAGE)
    except (DeadlockApiNotFoundError, DeadlockApiError):
        await message.answer("Не удалось получить матч. Проверьте account_id и API.")


@router.message(Command("heroes"))
async def cmd_heroes(message: Message) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    player_id = await _resolve_command_account(message, _pick_account_from_text(message.text or ""), "heroes")
    if not player_id:
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
    player_id = await _resolve_command_account(message, _pick_account_from_text(message.text or ""), "besthero")
    if not player_id:
        return
    stats = await api.get_player_hero_stats([api.normalize_account_id(player_id)])
    best = max(stats, key=lambda x: (_extract_winrate(x), int(x.get("matches_played") or x.get("matches") or 0)), default=None)
    if not best:
        await message.answer("Недостаточно данных по героям.")
        return
    await message.answer(
        f"Лучший герой: <b>{hero_name_by_id(best.get('hero_id'))}</b>\n"
        f"Матчей: <b>{best.get('matches_played') or best.get('matches') or 0}</b>\n"
        f"Winrate: <b>{_format_winrate(best)}</b>",
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
    player_id = await _resolve_command_account(message, _pick_account_from_text(message.text or ""), "teammates")
    if not player_id:
        return
    await _send_relation_stats(message, api.normalize_account_id(player_id), mode="mates")


@router.message(Command("enemies"))
async def cmd_enemies(message: Message) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    player_id = await _resolve_command_account(message, _pick_account_from_text(message.text or ""), "enemies")
    if not player_id:
        return
    await _send_relation_stats(message, api.normalize_account_id(player_id), mode="enemies")


@router.message(Command("party"))
async def cmd_party(message: Message) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    player_id = await _resolve_command_account(message, _pick_account_from_text(message.text or ""), "party")
    if not player_id:
        return
    account_id = api.normalize_account_id(player_id)
    stats = await api.get_player_party_stats(account_id)
    if not stats:
        await message.answer("Нет данных party-stats.")
        return
    total = sum(int(x.get("matches") or x.get("games") or 0) for x in stats)
    best = max(stats, key=lambda x: _extract_winrate(x), default={})
    await message.answer(
        f"<b>Пати-статистика</b> <code>{account_id}</code>\n"
        f"Всего пати-игр: <b>{total}</b>\n"
        f"Лучшая пати-связка (по WR): <b>{best.get('party_size') or best.get('size') or '—'}</b>\n"
        f"Winrate: <b>{_format_winrate(best)}</b>",
        parse_mode="HTML",
    )


@router.message(Command("meta"))
async def cmd_meta(message: Message) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    meta = await api.get_global_hero_stats()
    top = sorted(meta, key=lambda x: _extract_winrate(x), reverse=True)[:10]
    lines = ["<b>Глобальная мета (top winrate)</b>"]
    for item in top:
        matches = int(item.get('matches') or item.get('matches_played') or 0)
        lines.append(f"• {hero_name_by_id(item.get('hero_id'))}: WR {_format_winrate(item)}, Matches {matches}")
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
        lines.append(f"• {hero_name_by_id(partner_id)} — {_format_winrate(item) if _extract_winrate(item) > 0 else item.get('score') or '—'}")
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
        lines.append(f"• {hero_name_by_id(counter_id)} — {_format_winrate(item) if _extract_winrate(item) > 0 else item.get('score') or '—'}")
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
        mmr = _format_mmr(item)
        if acc and str(acc) in steam:
            lines.append(f"{rank}. {_steam_link(steam[str(acc)], api)} — MMR: <b>{mmr}</b>")
        else:
            lines.append(f"{rank}. <code>{acc}</code> — MMR: <b>{mmr}</b>")
    await message.answer("\n".join(lines), parse_mode="HTML")




@router.message(Command("patches"))
async def cmd_patches(message: Message) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    patches = await api.get_patches()
    if not patches:
        await message.answer("No patch data available right now.")
        return

    lines = ["<b>Latest Deadlock patches</b>"]
    for patch in patches[:8]:
        version = patch.get("title") or patch.get("version") or patch.get("name") or patch.get("patch") or "Unknown version"
        ts = patch.get("pub_date") or patch.get("released_at") or patch.get("release_date") or patch.get("date")
        if ts:
            lines.append(f"• <b>{version}</b> — {ts}")
        else:
            lines.append(f"• <b>{version}</b>")
    await message.answer("\n".join(lines), parse_mode="HTML")



@router.callback_query(lambda c: c.data and c.data.startswith("sel:"))
async def cb_select_player_for_action(callback: CallbackQuery) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    _, action, player_id = callback.data.split(":", maxsplit=2)
    account_id = api.normalize_account_id(player_id)

    try:
        if action == "profile":
            await _send_profile(callback.message, account_id)
        elif action == "lastmatch":
            try:
                await _send_last_match(callback.message, account_id)
            except DeadlockApiTemporaryError:
                await callback.message.answer(MATCH_HISTORY_TEMPORARY_MESSAGE)
                await callback.answer()
                return
        elif action == "heroes":
            stats = await api.get_player_hero_stats([account_id])
            if not stats:
                await callback.message.answer("Нет hero-stats для этого игрока.")
            else:
                lines = [f"<b>Герои игрока</b> <code>{account_id}</code>"]
                for item in stats[:12]:
                    lines.append(
                        f"• <b>{hero_name_by_id(item.get('hero_id'))}</b>: матчей {item.get('matches_played') or item.get('matches') or 0}, "
                        f"wins {item.get('wins') or 0}, K/D/A {item.get('kills') or 0}/{item.get('deaths') or 0}/{item.get('assists') or 0}, "
                        f"NPM {item.get('networth_per_min') or '—'}"
                    )
                await callback.message.answer("\n".join(lines), parse_mode="HTML")
        elif action == "besthero":
            stats = await api.get_player_hero_stats([account_id])
            best = max(stats, key=lambda x: (_extract_winrate(x), int(x.get("matches_played") or x.get("matches") or 0)), default=None)
            if not best:
                await callback.message.answer("Недостаточно данных по героям.")
            else:
                await callback.message.answer(
                    f"Лучший герой: <b>{hero_name_by_id(best.get('hero_id'))}</b>\n"
                    f"Матчей: <b>{best.get('matches_played') or best.get('matches') or 0}</b>\n"
                    f"Winrate: <b>{_format_winrate(best)}</b>",
                    parse_mode="HTML",
                )
        elif action == "teammates":
            await _send_relation_stats(callback.message, account_id, mode="mates")
        elif action == "enemies":
            await _send_relation_stats(callback.message, account_id, mode="enemies")
        elif action == "party":
            stats = await api.get_player_party_stats(account_id)
            if not stats:
                await callback.message.answer("Нет данных party-stats.")
            else:
                total = sum(int(x.get("matches") or x.get("games") or 0) for x in stats)
                best = max(stats, key=lambda x: _extract_winrate(x), default={})
                await callback.message.answer(
                    f"<b>Пати-статистика</b> <code>{account_id}</code>\n"
                    f"Всего пати-игр: <b>{total}</b>\n"
                    f"Лучшая пати-связка (по WR): <b>{best.get('party_size') or best.get('size') or '—'}</b>\n"
                    f"Winrate: <b>{_format_winrate(best)}</b>",
                    parse_mode="HTML",
                )
        else:
            await callback.answer("Неизвестное действие.")
            return

        await callback.answer()
    except DeadlockApiTemporaryError:
        await callback.answer("API перегружено, попробуйте позже.", show_alert=False)
        await callback.message.answer(TEMPORARY_API_MESSAGE)


@router.callback_query(lambda c: c.data and c.data.startswith("lm:"))
async def cb_lastmatch(callback: CallbackQuery) -> None:
    player_id = callback.data.split(":", maxsplit=1)[1]
    try:
        await _send_last_match(callback.message, player_id)
        await callback.answer()
    except DeadlockApiTemporaryError:
        await callback.answer("API перегружено, попробуйте позже.", show_alert=False)
        await callback.message.answer(MATCH_HISTORY_TEMPORARY_MESSAGE)


@router.callback_query(lambda c: c.data and c.data.startswith("rp:"))
async def cb_profile_button(callback: CallbackQuery) -> None:
    player_id = callback.data.split(":", maxsplit=1)[1]
    try:
        await _send_profile(callback.message, player_id)
        await callback.answer()
    except DeadlockApiTemporaryError:
        await callback.answer("API перегружено, попробуйте позже.", show_alert=False)
        await callback.message.answer(TEMPORARY_API_MESSAGE)


@router.callback_query(lambda c: c.data and c.data.startswith("autoff:"))
async def cb_autoff(callback: CallbackQuery) -> None:
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]
    player_id = callback.data.split(":")[1]
    ok = players_repo.set_auto_reports(callback.from_user.id, player_id, False)
    await callback.answer("Автоотслеживание отключено." if ok else "Игрок не найден.")


@router.callback_query(lambda c: c.data and c.data.startswith("profile:"))
async def cb_profile(callback: CallbackQuery) -> None:
    player_id = callback.data.split(":")[1]
    try:
        await _send_profile(callback.message, player_id)
        await callback.answer()
    except DeadlockApiTemporaryError:
        await callback.answer("API перегружено, попробуйте позже.", show_alert=False)
        await callback.message.answer(TEMPORARY_API_MESSAGE)


@router.callback_query(lambda c: c.data and c.data.startswith("details:"))
async def cb_details(callback: CallbackQuery) -> None:
    _, _, match_id = callback.data.split(":", maxsplit=2)
    await callback.answer(f"Детали матча {match_id} пока в разработке.")


@router.callback_query(lambda c: c.data and c.data.startswith("prev:"))
async def cb_prev(callback: CallbackQuery) -> None:
    await callback.answer("Переход к предыдущему матчу пока в разработке.")


@router.error()
async def reports_error_handler(event) -> bool:
    exception = getattr(event, "exception", None)
    if not isinstance(exception, DeadlockApiTemporaryError):
        return False

    update = getattr(event, "update", None)
    callback = getattr(update, "callback_query", None)
    message = getattr(update, "message", None) or (callback.message if callback else None)
    if callback is not None:
        await callback.answer("API перегружено, попробуйте позже.", show_alert=False)
    if message is not None:
        await message.answer(TEMPORARY_API_MESSAGE)
    return True
