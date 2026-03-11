import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.clients.deadlock_api import DeadlockApiClient, DeadlockApiError
from app.keyboards.inline import (
    MAIN_MENU_ADD_PLAYER,
    MAIN_MENU_ANALYTICS,
    MAIN_MENU_DASHBOARD,
    MAIN_MENU_HELP,
    MAIN_MENU_LAST_MATCH,
    MAIN_MENU_PATCHNOTES,
    MAIN_MENU_PLAYERS,
    MAIN_MENU_PROFILE,
    MAIN_MENU_SETTINGS,
    SETTINGS_DISABLE_AUTO,
    SETTINGS_ENABLE_AUTO,
    analytics_actions_keyboard,
    patches_keyboard,
    players_management_keyboard,
    settings_keyboard,
)
from app.repositories.players import TrackedPlayersRepository
from app.repositories.users import UsersRepository

logger = logging.getLogger(__name__)
router = Router()

MENU_BUTTON_TEXTS = {
    MAIN_MENU_ADD_PLAYER,
    MAIN_MENU_PLAYERS,
    MAIN_MENU_LAST_MATCH,
    MAIN_MENU_PROFILE,
    MAIN_MENU_ANALYTICS,
    MAIN_MENU_DASHBOARD,
    MAIN_MENU_PATCHNOTES,
    MAIN_MENU_SETTINGS,
    MAIN_MENU_HELP,
    SETTINGS_ENABLE_AUTO,
    SETTINGS_DISABLE_AUTO,
}


def _profile_link(account_id: str, personaname: str, profile_url: str | None, api: DeadlockApiClient) -> str:
    url = profile_url or f"https://steamcommunity.com/profiles/{api.account_id_to_steam64(account_id)}"
    return f'<a href="{url}">{personaname}</a>'


def setup_players_dependencies(users_repo: UsersRepository, players_repo: TrackedPlayersRepository, api: DeadlockApiClient) -> None:
    router.users_repo = users_repo  # type: ignore[attr-defined]
    router.players_repo = players_repo  # type: ignore[attr-defined]
    router.api = api  # type: ignore[attr-defined]
    router.search_cache = {}  # type: ignore[attr-defined]
    router.awaiting_add_input = set()  # type: ignore[attr-defined]


async def _save_player(message: Message, account_id: str, personaname: str, profile_url: str | None) -> None:
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]
    created = players_repo.add_player(message.from_user.id, account_id, personaname, steam_profile_url=profile_url)
    if created:
        await message.answer(
            f"Игрок {_profile_link(account_id, personaname, profile_url, router.api)} (<code>{account_id}</code>) добавлен.",  # type: ignore[attr-defined]
            parse_mode="HTML",
        )
        if not players_repo.get_default_player(message.from_user.id):
            players_repo.set_default_player(message.from_user.id, account_id)
            await message.answer("Сделал этого игрока профилем по умолчанию ⭐")
    else:
        await message.answer("Этот игрок уже есть в вашем списке.")


async def _resolve_and_save_player(message: Message, query: str) -> None:
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]
    try:
        resolved = await api.resolve_player(query)
    except (DeadlockApiError, ValueError):
        logger.exception("Ошибка resolve_player: %s", query)
        await message.answer("Не удалось обработать ввод. Проверьте формат и попробуйте снова.")
        return

    resolved = [item for item in resolved if item.get("account_id")]
    if not resolved:
        await message.answer("Ничего не найдено. Проверьте ник/ссылку/ID и попробуйте снова.")
        return

    if len(resolved) == 1:
        profile = resolved[0]
        await _save_player(
            message,
            str(profile["account_id"]),
            str(profile.get("personaname") or f"Игрок {profile['account_id']}"),
            profile.get("profile_url"),
        )
        return

    search_cache: dict[int, list[dict[str, str]]] = router.search_cache  # type: ignore[attr-defined]
    search_cache[message.from_user.id] = [
        {
            "account_id": str(item["account_id"]),
            "personaname": str(item.get("personaname") or f"Игрок {item['account_id']}"),
            "profile_url": str(item.get("profile_url") or ""),
        }
        for item in resolved[:10]
    ]
    lines = ["Найдено несколько профилей. Выберите командой:"]
    for idx, item in enumerate(search_cache[message.from_user.id], start=1):
        lines.append(f"{idx}. {item['personaname']} (<code>{item['account_id']}</code>) — /pickplayer {idx}")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("addplayer"))
async def cmd_addplayer(message: Message) -> None:
    users_repo: UsersRepository = router.users_repo  # type: ignore[attr-defined]

    users_repo.ensure_user(message.from_user.id)
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Напишите ID/Steam64/URL/ник одним сообщением.")
        awaiting_add: set[int] = router.awaiting_add_input  # type: ignore[attr-defined]
        awaiting_add.add(message.from_user.id)
        return

    await _resolve_and_save_player(message, args[1].strip())


@router.message(F.text & ~F.text.startswith("/") & ~F.text.in_(MENU_BUTTON_TEXTS))
async def handle_pending_add_player(message: Message) -> None:
    awaiting_add: set[int] = router.awaiting_add_input  # type: ignore[attr-defined]
    if message.from_user.id not in awaiting_add:
        return
    awaiting_add.discard(message.from_user.id)
    await _resolve_and_save_player(message, (message.text or "").strip())


@router.message(Command("pickplayer"))
async def cmd_pickplayer(message: Message) -> None:
    search_cache: dict[int, list[dict[str, str]]] = router.search_cache  # type: ignore[attr-defined]
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: <code>/pickplayer N</code>", parse_mode="HTML")
        return
    options = search_cache.get(message.from_user.id) or []
    if not options:
        await message.answer("Нет активного списка поиска. Сначала выполните /addplayer nickname")
        return
    idx = int(args[1]) - 1
    if idx < 0 or idx >= len(options):
        await message.answer("Неверный номер варианта.")
        return
    picked = options[idx]
    await _save_player(message, picked["account_id"], picked["personaname"], picked.get("profile_url") or None)


@router.message(Command("players"))
async def cmd_players(message: Message) -> None:
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]
    api: DeadlockApiClient = router.api  # type: ignore[attr-defined]

    players = players_repo.list_players(message.from_user.id)
    if not players:
        await message.answer("Пока нет отслеживаемых игроков. Добавьте через /addplayer.")
        return

    await message.answer("<b>Ваши отслеживаемые игроки:</b>", parse_mode="HTML")
    for p in players:
        status = "✅ автоотслеживание включено" if p.auto_reports_enabled else "⏸ автоотслеживание выключено"
        default_mark = "⭐ по умолчанию" if p.is_default else ""
        name = _profile_link(p.player_id, p.display_name, p.steam_profile_url, api)
        await message.answer(
            f"• {name} (<code>{p.player_id}</code>)\n{status}\n{default_mark}",
            parse_mode="HTML",
            reply_markup=players_management_keyboard(p.player_id, p.auto_reports_enabled, p.steam_profile_url, p.is_default),
        )


@router.message(F.text == MAIN_MENU_ADD_PLAYER)
async def btn_add_player(message: Message) -> None:
    awaiting_add: set[int] = router.awaiting_add_input  # type: ignore[attr-defined]
    awaiting_add.add(message.from_user.id)
    await message.answer("Отправьте ID/Steam64/steamcommunity URL/ник одним сообщением.")


@router.message(F.text == MAIN_MENU_PLAYERS)
async def btn_players(message: Message) -> None:
    await cmd_players(message)


@router.message(F.text == MAIN_MENU_ANALYTICS)
async def btn_analytics(message: Message) -> None:
    await message.answer("Выберите раздел аналитики:", reply_markup=analytics_actions_keyboard())


@router.message(F.text == MAIN_MENU_SETTINGS)
async def btn_settings(message: Message) -> None:
    await message.answer("<b>Настройки</b>\nВыберите действие для автоотчётов:", parse_mode="HTML")
    await message.answer("Выберите опцию:", reply_markup=settings_keyboard())


@router.message(F.text == SETTINGS_ENABLE_AUTO)
async def btn_settings_enable_auto(message: Message) -> None:
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]
    players = players_repo.list_players(message.from_user.id)
    if not players:
        await message.answer("Сначала добавьте игрока через /addplayer.")
        return
    updated = sum(1 for p in players if players_repo.set_auto_reports(message.from_user.id, p.player_id, True))
    await message.answer(f"Включил автоотчёты для {updated} игроков.")


@router.message(F.text == SETTINGS_DISABLE_AUTO)
async def btn_settings_disable_auto(message: Message) -> None:
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]
    players = players_repo.list_players(message.from_user.id)
    if not players:
        await message.answer("Сначала добавьте игрока через /addplayer.")
        return
    updated = sum(1 for p in players if players_repo.set_auto_reports(message.from_user.id, p.player_id, False))
    await message.answer(f"Выключил автоотчёты для {updated} игроков.")


@router.message(F.text == MAIN_MENU_HELP)
async def btn_help(message: Message) -> None:
    await message.answer("Используйте главное меню и кнопки в карточках игроков.")


@router.callback_query(lambda c: c.data and c.data.startswith("rm:"))
async def cb_remove_player(callback: CallbackQuery) -> None:
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]
    player_id = callback.data.split(":")[1]
    ok = players_repo.remove_player(callback.from_user.id, player_id)
    await callback.answer("Игрок удалён." if ok else "Игрок не найден.")


@router.callback_query(lambda c: c.data and c.data.startswith("tg:"))
async def cb_toggle_tracking(callback: CallbackQuery) -> None:
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]
    _, player_id, toggle_to = callback.data.split(":", maxsplit=2)
    ok = players_repo.set_auto_reports(callback.from_user.id, player_id, toggle_to == "on")
    await callback.answer("Статус автоотслеживания обновлён." if ok else "Игрок не найден.")


@router.callback_query(lambda c: c.data and c.data.startswith("def:"))
async def cb_default_player(callback: CallbackQuery) -> None:
    players_repo: TrackedPlayersRepository = router.players_repo  # type: ignore[attr-defined]
    _, player_id, value = callback.data.split(":", maxsplit=2)
    if value == "on":
        ok = players_repo.set_default_player(callback.from_user.id, player_id)
        await callback.answer("Игрок установлен по умолчанию." if ok else "Игрок не найден.")
    else:
        ok = players_repo.clear_default_player(callback.from_user.id)
        await callback.answer("Игрок по умолчанию снят." if ok else "Не было игрока по умолчанию.")
