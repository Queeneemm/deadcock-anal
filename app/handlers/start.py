from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.keyboards.inline import main_menu_keyboard

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "<b>Привет!</b> Я бот для отслеживания матчей Deadlock.\n"
        "Работаю по account_id (или ссылке на Steam-профиль).",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>Доступные действия:</b>\n"
        "• ➕ Добавить игрока — отправлю инструкцию, как добавить\n"
        "• 👥 Мои игроки — список с кнопками действий\n"
        "• 📄 Последний матч — выберите игрока кнопкой\n"
        "• 🧾 Профиль — выберите игрока кнопкой\n\n"
        "<b>Команды тоже работают:</b>\n"
        "/addplayer &lt;account_id|ссылка_steam_profile&gt;\n"
        "/players\n"
        "/removeplayer &lt;account_id&gt;\n"
        "/track &lt;account_id&gt; &lt;on|off&gt;\n"
        "/lastmatch &lt;account_id&gt;\n"
        "/profile &lt;account_id&gt;",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
