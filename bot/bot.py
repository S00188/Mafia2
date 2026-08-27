"""
Mafia Mini App — Telegram bot side.

This process's only job is: when someone runs /start in a group, post one
button that opens the Mini App for that group. Everything else (who's in
the lobby, starting the game, night/day/vote, win screens) happens inside
the web app talking directly to the FastAPI backend — this bot never
touches game state.

Run alongside the backend (two separate processes):
    backend:  uvicorn app.main:app --host 0.0.0.0 --port 8000
    bot:      python bot.py

Both processes read TELEGRAM_BOT_TOKEN from the environment — it's the
same bot token either way, just used for two different things (verifying
Mini App launches on the backend, sending messages here).
"""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mafia-bot")

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
# Where the FastAPI app (app/static/index.html) is actually reachable from
# the outside world, e.g. "https://mafia.fly.dev" — no trailing slash.
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://example.com").rstrip("/")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


@dp.message(Command("start"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def start_in_group(message: Message) -> None:
    """The one and only entry point into a match. There is no "create game"
    command — every tap of this button lands on POST /games/for-chat on the
    backend, which creates the group's match on the first tap and joins
    everyone else into that same match on every tap after."""
    chat_id = message.chat.id
    # `web_app` inline buttons only work in a private chat with the bot —
    # Telegram rejects them here with "Bad Request: BUTTON_TYPE_INVALID"
    # since this always runs in a group. Use a plain `url` button with the
    # "Direct Link Mini App" scheme instead (t.me/<bot>?startapp=<payload>);
    # Telegram launches the Mini App from that link with real initData,
    # same as a native web_app button would. Requires the bot's Mini App
    # URL to be set once via @BotFather (Bot Settings > Mini App) to this
    # same WEBAPP_URL.
    me = await bot.get_me()
    webapp_url = f"https://t.me/{me.username}?startapp={chat_id}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎭 O'yinga qo'shilish", url=webapp_url),
    ]])
    await message.answer(
        "🌙 <b>MAFIA</b> boshlanmoqda!\n\n"
        "Qo'shilish uchun quyidagi tugmani bosing.\n"
        "Kamida <b>6</b> kishi yig'ilsa, o'yinni boshlash mumkin bo'ladi.\n"
        "<b>25</b> kishi to'lsa — o'yin avtomatik boshlanadi.",
        reply_markup=keyboard,
    )


@dp.message(Command("start"), F.chat.type == ChatType.PRIVATE)
async def start_in_private(message: Message) -> None:
    await message.answer(
        "👋 Salom! Bu bot guruh o'yinlari uchun.\n\n"
        "Meni biror guruhga qo'shing va o'sha yerda <code>/start</code> buyrug'ini yuboring — "
        "a'zolar qo'shiladigan tugma paydo bo'ladi."
    )


async def main() -> None:
    logger.info("Mafia bot starting (webapp_url=%s)", WEBAPP_URL)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
