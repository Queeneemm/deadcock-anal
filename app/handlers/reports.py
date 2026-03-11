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

router = Router()


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

    local_recent = matches_repo.get_recent_player_matches(player_id, 20)
    if local_recent:
        summaries = local_recent
    else:
        try:
            history = await api.get_player_recent_matches(player_id)
        except DeadlockApiNotFoundError:
            await message.answer("Профиль не найден. Проверьте account_id или SteamID64.")
            return
        except DeadlockApiTemporaryError:
            await message.answer("API временно недоступен. Попробуйте позже.")
            return
        except DeadlockApiError:
            await message.answer("Не удалось получить профиль из API.")
            return

        summaries = []
        for item in history[:20]:
            parsed = api.parse_match_for_player(item, player_id)
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
                team_damage_rank=parsed.get("team_damage_rank"),
                team_souls_rank=parsed.get("team_souls_rank"),
                raw_payload=parsed.get("raw_payload"),
            )
            matches_repo.store_player_match_history(player_id, summary)
            summaries.append(summary)

    if not summaries:
        await message.answer("Нет данных для построения профиля по истории матчей.")
        return

    matches_count = len(summaries)
    avg_kda = sum((m.kills + m.assists) / max(m.deaths, 1) for m in summaries) / matches_count
    avg_souls = sum(m.souls for m in summaries) / matches_count
    avg_last_hits = sum(int((m.raw_payload or {}).get("last_hits") or 0) for m in summaries) / matches_count
    wins = sum(1 for m in summaries if m.is_win)

    hero_freq: dict[str, int] = {}
    for m in summaries:
        hero_freq[m.hero_name] = hero_freq.get(m.hero_name, 0) + 1
    top_heroes = sorted(hero_freq.items(), key=lambda x: x[1], reverse=True)[:3]
    top_heroes_text = ", ".join(f"{hero} ({count})" for hero, count in top_heroes) if top_heroes else "—"

    await message.answer(
        f"<b>Профиль игрока (по match-history)</b>\n"
        f"ID: <code>{player_id}</code>\n"
        f"Последних матчей: <b>{matches_count}</b>\n"
        f"Winrate: <b>{(wins / matches_count) * 100:.1f}%</b>\n"
        f"Средний KDA: <b>{avg_kda:.2f}</b>\n"
        f"Средний net worth: <b>{avg_souls:.0f}</b>\n"
        f"Средние last hits: <b>{avg_last_hits:.1f}</b>\n"
        f"Частые герои: <b>{top_heroes_text}</b>",
        parse_mode="HTML",
    )


async def _send_last_match(message: Message, player_id: str) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    matches_repo: MatchesRepository = router.matches_repo  # type: ignore[attr-defined]
    analytics: AnalyticsService = router.analytics  # type: ignore[attr-defined]
    cards: CardRenderer = router.cards  # type: ignore[attr-defined]

    try:
        matches = await api.get_player_recent_matches(player_id)
    except DeadlockApiNotFoundError:
        await message.answer("История матчей не найдена. Проверьте account_id.")
        return
    except DeadlockApiTemporaryError:
        await message.answer("API временно недоступен. Попробуйте позже.")
        return
    except DeadlockApiError:
        await message.answer("Не удалось получить историю матчей.")
        return

    if not matches:
        await message.answer("Не удалось получить матчи игрока.")
        return

    latest = matches[0]
    parsed = api.parse_match_for_player(latest, player_id)
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
        team_damage_rank=parsed.get("team_damage_rank"),
        team_souls_rank=parsed.get("team_souls_rank"),
        raw_payload=parsed.get("raw_payload"),
    )
    matches_repo.store_player_match_history(player_id, summary)
    recent = matches_repo.get_recent_player_matches(player_id, 20)
    hero = matches_repo.get_recent_player_matches(player_id, 20, summary.hero_name)
    week = matches_repo.get_recent_player_matches(player_id, 100)
    analysis = analytics.analyze(summary, recent, hero, week)
    card_path = await cards.render(player_id, summary, analysis)

    await message.answer_photo(
        photo=FSInputFile(card_path),
        caption="Последний матч сформирован по истории матчей.",
        reply_markup=report_actions_keyboard(player_id, summary.match_id),
    )


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: <code>/profile account_id</code>", parse_mode="HTML")
        return
    await _send_profile(message, args[1])


@router.message(Command("lastmatch"))
async def cmd_lastmatch(message: Message) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: <code>/lastmatch account_id</code>", parse_mode="HTML")
        return
    await _send_last_match(message, args[1])


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
