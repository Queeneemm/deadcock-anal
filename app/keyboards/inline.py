from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def report_actions_keyboard(player_id: str, match_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Подробнее", callback_data=f"details:{player_id}:{match_id}")],
            [InlineKeyboardButton(text="Прошлый матч", callback_data=f"prev:{player_id}:{match_id}")],
            [InlineKeyboardButton(text="Профиль", callback_data=f"profile:{player_id}")],
            [InlineKeyboardButton(text="Отключить автоотслеживание", callback_data=f"autoff:{player_id}")],
        ]
    )
