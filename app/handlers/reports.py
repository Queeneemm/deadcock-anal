from datetime import datetime

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.clients.deadlock_api import DeadlockApiClient
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


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: <code>/profile player_id</code>", parse_mode="HTML")
        return
    profile = await api.get_player_profile(args[1])
    await message.answer(
        f"<b>Профиль игрока</b>\n"
        f"ID: <code>{profile.get('player_id', args[1])}</code>\n"
        f"Ник: <b>{profile.get('display_name', '—')}</b>\n"
        f"MMR: <b>{profile.get('mmr', '—')}</b>",
        parse_mode="HTML",
    )


@router.message(Command("lastmatch"))
async def cmd_lastmatch(message: Message) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    matches_repo: MatchesRepository = router.matches_repo  # type: ignore[attr-defined]
    analytics: AnalyticsService = router.analytics  # type: ignore[attr-defined]
    cards: CardRenderer = router.cards  # type: ignore[attr-defined]

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: <code>/lastmatch player_id</code>", parse_mode="HTML")
        return
    player_id = args[1]

    matches = await api.get_player_recent_matches(player_id)
    if not matches:
        await message.answer("Не удалось получить матчи игрока.")
        return
    match_id = str(matches[0].get("match_id") or matches[0].get("id"))
    match_payload = await api.get_match(match_id)
    parsed = api.parse_match_for_player(match_payload, player_id)
    summary = MatchSummary(
        match_id=parsed["match_id"],
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
        caption="Последний матч сформирован вручную.",
        reply_markup=report_actions_keyboard(player_id, summary.match_id),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("autoff:"))
async def cb_autoff(callback: CallbackQuery) -> None:
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]
    player_id = callback.data.split(":")[1]
    ok = players_repo.set_auto_reports(callback.from_user.id, player_id, False)
    await callback.answer("Автоотслеживание отключено." if ok else "Игрок не найден.")


@router.callback_query(lambda c: c.data and c.data.startswith("profile:"))
async def cb_profile(callback: CallbackQuery) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    player_id = callback.data.split(":")[1]
    profile = await api.get_player_profile(player_id)
    await callback.message.answer(
        f"Профиль: <b>{profile.get('display_name', player_id)}</b>\n"
        f"MMR: <b>{profile.get('mmr', '—')}</b>",
        parse_mode="HTML",
    )
    await callback.answer()
