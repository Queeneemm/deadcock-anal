from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

MAIN_MENU_ADD_PLAYER = "➕ Добавить игрока"
MAIN_MENU_PLAYERS = "👥 Мои игроки"
MAIN_MENU_LAST_MATCH = "📄 Последний матч"
MAIN_MENU_PROFILE = "🧾 Профиль"
MAIN_MENU_HELP = "❓ Помощь"


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MAIN_MENU_ADD_PLAYER), KeyboardButton(text=MAIN_MENU_PLAYERS)],
            [KeyboardButton(text=MAIN_MENU_LAST_MATCH), KeyboardButton(text=MAIN_MENU_PROFILE)],
            [KeyboardButton(text=MAIN_MENU_HELP)],
        ],
        resize_keyboard=True,
    )


def report_actions_keyboard(player_id: str, match_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подробнее", callback_data=f"details:{player_id}:{match_id}")],
            [InlineKeyboardButton(text="Прошлый матч", callback_data=f"prev:{player_id}:{match_id}")],
            [InlineKeyboardButton(text="Профиль", callback_data=f"profile:{player_id}")],
            [InlineKeyboardButton(text="Отключить автоотслеживание", callback_data=f"autoff:{player_id}")],
        ]
    )


def players_management_keyboard(player_id: str, auto_reports_enabled: bool, steam_profile_url: str | None = None) -> InlineKeyboardMarkup:
    toggle_text = "Отключить автоотслеживание" if auto_reports_enabled else "Включить автоотслеживание"
    toggle_to = "off" if auto_reports_enabled else "on"
    rows = [
        [
            InlineKeyboardButton(text="📄 Последний матч", callback_data=f"lm:{player_id}"),
            InlineKeyboardButton(text="🧾 Профиль", callback_data=f"rp:{player_id}"),
        ],
        [InlineKeyboardButton(text=toggle_text, callback_data=f"tg:{player_id}:{toggle_to}")],
    ]
    if steam_profile_url:
        rows.append([InlineKeyboardButton(text="🔗 Открыть профиль", url=steam_profile_url)])
    rows.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"rm:{player_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
