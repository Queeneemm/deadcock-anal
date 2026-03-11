from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

MAIN_MENU_ADD_PLAYER = "➕ Добавить игрока"
MAIN_MENU_PLAYERS = "👥 Мои игроки"
MAIN_MENU_LAST_MATCH = "📄 Последний матч"
MAIN_MENU_PROFILE = "🧾 Профиль"
MAIN_MENU_ANALYTICS = "📊 Аналитика"
MAIN_MENU_SETTINGS = "⚙️ Настройки"
MAIN_MENU_HELP = "❓ Помощь"
SETTINGS_ENABLE_AUTO = "🔔 Включить автоотчёты всем"
SETTINGS_DISABLE_AUTO = "🔕 Выключить автоотчёты всем"


def commands_keyboard() -> ReplyKeyboardMarkup:
    return main_menu_keyboard()


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MAIN_MENU_ADD_PLAYER), KeyboardButton(text=MAIN_MENU_PLAYERS)],
            [KeyboardButton(text=MAIN_MENU_LAST_MATCH), KeyboardButton(text=MAIN_MENU_PROFILE)],
            [KeyboardButton(text=MAIN_MENU_ANALYTICS), KeyboardButton(text=MAIN_MENU_SETTINGS)],
            [KeyboardButton(text=MAIN_MENU_HELP)],
        ],
        resize_keyboard=True,
    )




def settings_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=SETTINGS_ENABLE_AUTO), KeyboardButton(text=SETTINGS_DISABLE_AUTO)],
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


def analytics_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🦸 Герои", callback_data="menu:heroes"), InlineKeyboardButton(text="🏆 Лучший герой", callback_data="menu:besthero")],
            [InlineKeyboardButton(text="🤝 Тиммейты", callback_data="menu:teammates"), InlineKeyboardButton(text="⚔️ Соперники", callback_data="menu:enemies")],
            [InlineKeyboardButton(text="🎉 Пати", callback_data="menu:party"), InlineKeyboardButton(text="🌍 Мета", callback_data="menu:meta")],
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


def player_select_keyboard(action: str, players: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"{name} ({account_id})", callback_data=f"sel:{action}:{account_id}")] for account_id, name in players[:10]]
    return InlineKeyboardMarkup(inline_keyboard=rows)
