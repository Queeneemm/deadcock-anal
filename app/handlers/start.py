from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.keyboards.inline import commands_keyboard

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "<b>Привет!</b> Это персональный Deadlock tracker-бот.\n"
        "Поддерживаются account_id, Steam64, steamcommunity URL и ник Steam.",
        parse_mode="HTML",
        reply_markup=commands_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>Основные команды:</b>\n"
        "/addplayer &lt;account_id|Steam64|steam_url|nickname&gt;\n"
        "/pickplayer &lt;N&gt;\n"
        "/players\n"
        "/lastmatch [account_id]\n"
        "/profile [account_id]\n"
        "/heroes [account_id]\n"
        "/besthero [account_id]\n"
        "/hero &lt;account_id&gt; &lt;hero_id&gt;\n"
        "/teammates [account_id]\n"
        "/enemies [account_id]\n"
        "/party [account_id]\n"
        "/meta\n"
        "/synergy &lt;hero_id&gt;\n"
        "/counter &lt;hero_id&gt;\n"
        "/leaderboard &lt;region&gt;\n"
        "/patches",
        parse_mode="HTML",
        reply_markup=commands_keyboard(),
    )
