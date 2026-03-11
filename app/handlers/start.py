from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.keyboards.inline import main_menu_keyboard

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "<b>Привет!</b> Это персональный Deadlock tracker-бот.\n"
        "Поддерживаются account_id, Steam64, steamcommunity URL и ник Steam.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>Основные команды:</b>\n"
        "/addplayer &lt;account_id|Steam64|steam_url|nickname&gt;\n"
        "/pickplayer &lt;N&gt;\n"
        "/players\n"
        "/lastmatch &lt;account_id&gt;\n"
        "/profile &lt;account_id&gt;\n"
        "/heroes &lt;account_id&gt;\n"
        "/besthero &lt;account_id&gt;\n"
        "/hero &lt;account_id&gt; &lt;hero_id&gt;\n"
        "/teammates &lt;account_id&gt;\n"
        "/enemies &lt;account_id&gt;\n"
        "/party &lt;account_id&gt;\n"
        "/meta\n"
        "/synergy &lt;hero_id&gt;\n"
        "/counter &lt;hero_id&gt;\n"
        "/leaderboard &lt;region&gt;",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
