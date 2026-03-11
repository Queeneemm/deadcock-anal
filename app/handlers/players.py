import logging
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.clients.deadlock_api import DeadlockApiClient, DeadlockApiError
from app.keyboards.inline import (
    MAIN_MENU_ADD_PLAYER,
    MAIN_MENU_HELP,
    MAIN_MENU_LAST_MATCH,
    MAIN_MENU_PLAYERS,
    MAIN_MENU_PROFILE,
    players_management_keyboard,
)
from app.repositories.players import TrackedPlayersRepository
from app.repositories.users import UsersRepository

logger = logging.getLogger(__name__)
router = Router()


def setup_players_dependencies(users_repo: UsersRepository, players_repo: TrackedPlayersRepository, api: DeadlockApiClient) -> None:
    router.users_repo = users_repo  # type: ignore[attr-defined]
    router.players_repo = players_repo  # type: ignore[attr-defined]
    router.api = api  # type: ignore[attr-defined]


@router.message(Command("addplayer"))
async def cmd_addplayer(message: Message) -> None:
    users_repo: UsersRepository = router.users_repo  # type: ignore[attr-defined]
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]

    users_repo.ensure_user(message.from_user.id)
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Использование: <code>/addplayer account_id|Steam64|steamcommunity_url</code>",
            parse_mode="HTML",
        )
        return

    query = args[1].strip()
    account_id: str | None = None

    try:
        if re.match(r"^https?://steamcommunity\.com/(profiles|id)/", query, flags=re.IGNORECASE):
            account_id = await api.resolve_steam_profile_to_account_id(query)
            if not account_id:
                await message.answer("Не удалось прочитать Steam-профиль. Проверьте ссылку и приватность профиля.")
                return
        elif query.isdigit():
            account_id = api.normalize_account_id(query)
        else:
            await message.answer(
                "Поиск по нику пока не поддерживается. "
                "Укажите account_id, Steam64 или ссылку на steamcommunity.com/profiles/... (или /id/...)."
            )
            return
    except (DeadlockApiError, ValueError):
        logger.exception("Ошибка при добавлении игрока: %s", query)
        await message.answer("Не удалось обработать ввод. Укажите корректный account_id, Steam64 или ссылку Steam.")
        return

    if not account_id:
        await message.answer("Не удалось определить account_id. Используйте account_id, Steam64 или ссылку Steam.")
        return

    try:
        profile = await api.get_player_profile(account_id)
        display_name = str(profile.get("display_name") or account_id)
    except DeadlockApiError:
        logger.warning("Не удалось получить fallback-профиль для account_id=%s", account_id)
        display_name = account_id

    created = players_repo.add_player(message.from_user.id, account_id, display_name)
    if created:
        await message.answer(f"Игрок <b>{display_name}</b> (<code>{account_id}</code>) добавлен в отслеживание.", parse_mode="HTML")
    else:
        await message.answer("Этот игрок уже отслеживается.")


@router.message(Command("players"))
async def cmd_players(message: Message) -> None:
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]
    players = players_repo.list_players(message.from_user.id)
    if not players:
        await message.answer("Пока нет отслеживаемых игроков. Добавьте через /addplayer.")
        return

    await message.answer("<b>Ваши отслеживаемые игроки:</b>", parse_mode="HTML")
    for p in players:
        status = "✅ автоотчёты" if p.auto_reports_enabled else "⏸ автоотчёты выключены"
        await message.answer(
            f"• <b>{p.display_name}</b> (<code>{p.player_id}</code>) — {status}",
            parse_mode="HTML",
            reply_markup=players_management_keyboard(p.player_id, p.auto_reports_enabled),
        )


@router.message(Command("removeplayer"))
async def cmd_removeplayer(message: Message) -> None:
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: <code>/removeplayer account_id</code>", parse_mode="HTML")
        return
    if players_repo.remove_player(message.from_user.id, args[1].strip()):
        await message.answer("Игрок удалён из отслеживания.")
    else:
        await message.answer("Игрок не найден в вашем списке.")


@router.message(Command("track"))
async def cmd_track(message: Message) -> None:
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]
    args = (message.text or "").split(maxsplit=2)
    if len(args) < 3 or args[2] not in {"on", "off"}:
        await message.answer("Использование: <code>/track account_id on|off</code>", parse_mode="HTML")
        return
    enabled = args[2] == "on"
    updated = players_repo.set_auto_reports(message.from_user.id, args[1], enabled)
    if updated:
        await message.answer("Автоотслеживание обновлено.")
    else:
        await message.answer("Игрок не найден.")


@router.message(F.text == MAIN_MENU_ADD_PLAYER)
async def btn_add_player(message: Message) -> None:
    await message.answer(
        "Отправьте: <code>/addplayer account_id</code> "
        "или <code>/addplayer Steam64</code> "
        "или <code>/addplayer https://steamcommunity.com/...</code>",
        parse_mode="HTML",
    )


@router.message(F.text == MAIN_MENU_PLAYERS)
async def btn_players(message: Message) -> None:
    await cmd_players(message)


@router.message(F.text == MAIN_MENU_LAST_MATCH)
async def btn_last_match(message: Message) -> None:
    await message.answer("Используйте <code>/lastmatch account_id</code> или кнопки в списке игроков.", parse_mode="HTML")


@router.message(F.text == MAIN_MENU_PROFILE)
async def btn_profile(message: Message) -> None:
    await message.answer("Используйте <code>/profile account_id</code> или кнопки в списке игроков.", parse_mode="HTML")


@router.message(F.text == MAIN_MENU_HELP)
async def btn_help(message: Message) -> None:
    await message.answer(
        "Подсказка:\n"
        "1) Добавьте игрока через /addplayer\n"
        "2) Откройте /players\n"
        "3) Используйте кнопки для профиля, последнего матча и управления автоотчётами.",
    )


@router.callback_query(lambda c: c.data and c.data.startswith("rm:"))
async def cb_remove_player(callback: CallbackQuery) -> None:
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]
    player_id = callback.data.split(":")[1]
    ok = players_repo.remove_player(callback.from_user.id, player_id)
    await callback.answer("Игрок удалён." if ok else "Игрок не найден.")


@router.callback_query(lambda c: c.data and c.data.startswith("tr:on:"))
async def cb_track_on(callback: CallbackQuery) -> None:
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]
    player_id = callback.data.split(":", maxsplit=2)[2]
    ok = players_repo.set_auto_reports(callback.from_user.id, player_id, True)
    await callback.answer("Автоотслеживание включено." if ok else "Игрок не найден.")


@router.callback_query(lambda c: c.data and c.data.startswith("tr:off:"))
async def cb_track_off(callback: CallbackQuery) -> None:
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]
    player_id = callback.data.split(":", maxsplit=2)[2]
    ok = players_repo.set_auto_reports(callback.from_user.id, player_id, False)
    await callback.answer("Автоотслеживание отключено." if ok else "Игрок не найден.")
