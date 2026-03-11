from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.keyboards.inline import main_menu_keyboard

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "<b>Привет!</b> Я бот для отслеживания матчей Deadlock.\n"
        "Теперь можно пользоваться кнопками внизу — без ручного ввода команд.",
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
        "/addplayer &lt;player_id|ник|ссылка_steam_profile&gt;\n"
        "/players\n"
        "/removeplayer &lt;player_id&gt;\n"
        "/track &lt;player_id&gt; &lt;on|off&gt;\n"
        "/lastmatch &lt;player_id&gt;\n"
        "/profile &lt;player_id&gt;",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
