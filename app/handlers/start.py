from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "<b>Привет!</b> Я бот для отслеживания матчей Deadlock.\n"
        "Добавьте игрока командой <code>/addplayer player_id</code> или <code>/addplayer ник</code>.",
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>Доступные команды:</b>\n"
        "/addplayer &lt;player_id|ник&gt; — добавить игрока\n"
        "/players — список отслеживаемых\n"
        "/removeplayer &lt;player_id&gt; — удалить игрока\n"
        "/track &lt;player_id&gt; &lt;on|off&gt; — включить/выключить автоотчёты\n"
        "/lastmatch &lt;player_id&gt; — отправить последний матч\n"
        "/profile &lt;player_id&gt; — профиль игрока",
        parse_mode="HTML",
    )
