import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.clients.deadlock_api import DeadlockApiClient
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
        await message.answer("Использование: <code>/addplayer player_id</code>", parse_mode="HTML")
        return
    query = args[1].strip()

    player_id = query
    display_name = query
    if not query.isdigit():
        variants = await api.resolve_player(query)
        if len(variants) == 1:
            player_id = str(variants[0].get("player_id"))
            display_name = variants[0].get("display_name", query)
        elif len(variants) > 1:
            await message.answer(
                "Найдено несколько игроков. Для MVP используйте точный <code>player_id</code>.\n"
                "TODO: интерактивный выбор из нескольких кандидатов.",
                parse_mode="HTML",
            )
            return
        else:
            await message.answer("Игрок не найден. Проверьте ID или ник.")
            return

    created = players_repo.add_player(message.from_user.id, player_id, display_name)
    if created:
        await message.answer(f"Игрок <b>{display_name}</b> добавлен в отслеживание.", parse_mode="HTML")
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
        await message.answer("Использование: <code>/removeplayer player_id</code>", parse_mode="HTML")
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
        await message.answer("Использование: <code>/track player_id on|off</code>", parse_mode="HTML")
        return
    enabled = args[2] == "on"
    updated = players_repo.set_auto_reports(message.from_user.id, args[1], enabled)
    if updated:
        await message.answer("Автоотслеживание обновлено.")
    else:
        await message.answer("Игрок не найден.")


@router.message(F.text == MAIN_MENU_ADD_PLAYER)
async def btn_add_player(message: Message) -> None:
    await message.answer("Отправьте команду: <code>/addplayer player_id</code> или <code>/addplayer ник</code>", parse_mode="HTML")


@router.message(F.text == MAIN_MENU_PLAYERS)
async def btn_players(message: Message) -> None:
    await cmd_players(message)


@router.message(F.text == MAIN_MENU_LAST_MATCH)
async def btn_last_match(message: Message) -> None:
    await message.answer("Нажмите «👥 Мои игроки» и выберите «📄 Матч» у нужного игрока.")


@router.message(F.text == MAIN_MENU_PROFILE)
async def btn_profile(message: Message) -> None:
    await message.answer("Нажмите «👥 Мои игроки» и выберите «🧾 Профиль» у нужного игрока.")


@router.message(F.text == MAIN_MENU_HELP)
async def btn_help(message: Message) -> None:
    await message.answer("Используйте кнопки меню ниже для управления ботом или введите /help.")


@router.callback_query(lambda c: c.data and c.data.startswith("rm:"))
async def cb_remove_player(callback: CallbackQuery) -> None:
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]
    player_id = callback.data.split(":", maxsplit=1)[1]
    ok = players_repo.remove_player(callback.from_user.id, player_id)
    await callback.answer("Игрок удалён." if ok else "Игрок не найден.")
    if ok:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(lambda c: c.data and c.data.startswith("tg:"))
async def cb_toggle_track(callback: CallbackQuery) -> None:
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]
    _, player_id, state = callback.data.split(":", maxsplit=2)
    enabled = state == "on"
    ok = players_repo.set_auto_reports(callback.from_user.id, player_id, enabled)
    await callback.answer("Автоотчёты обновлены." if ok else "Игрок не найден.")
    if ok:
        await callback.message.edit_reply_markup(reply_markup=players_management_keyboard(player_id, enabled))
