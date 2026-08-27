"""
Telegram bot logic, wired for WEBHOOK delivery instead of long-polling —
this is what lets the bot run inside the same process as the backend, with
no separate worker service. Used only when settings.telegram_webhook_enabled
is true (see app/config.py); for a VPS or Fly.io deployment that runs the
bot as its own long-polling process instead, bot/bot.py is unchanged and
still works exactly as before — a bot token can only be in one mode
(webhook or polling) at a time, so pick one deployment target per token,
not both at once.

bot/bot.py deliberately stays a minimal, standalone script (its own
requirements.txt, no database) so it can run on a bare VPS. Everything
below it (persistent menu, group picker, admin panel, support relay) needs
the backend's own DB and settings, so it only lives here — the two
commands they share (/start in a group vs. private chat) behave the same
in spirit, but bot/bot.py's private /start stays the short, DB-free
version.
"""
from __future__ import annotations
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery, ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, Message, ReplyKeyboardMarkup, Update, WebAppInfo,
)
from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import func, select

from app.config import settings
from app.database import AsyncSessionLocal
from app.i18n import (
    BTN_LANGUAGE, LANGUAGE_LABELS, SUPPORTED_LANGUAGES, button_text, button_texts,
    get_user_language, set_user_language, t,
)
from app.models.models import BotSetting, KnownGroup, SupportMessage, User
from app.services.game_service import get_or_create_user
from app.services.telegram_bot_api import verify_group_membership

logger = logging.getLogger("mafia.telegram_bot")

router = APIRouter(prefix="/bot", tags=["bot"])

# The Bot object validates its token's format the moment it's constructed
# (aiogram raises TokenValidationError for anything that isn't
# "<digits>:<35 chars>"). Building it at import time would crash every
# test and every deployment that doesn't set a real TELEGRAM_BOT_TOKEN —
# including this project's own test suite, which uses placeholder tokens.
# Building it lazily, only when webhook mode is actually used, avoids that
# entirely. Dispatcher() itself needs no token, so it's fine at import time.
dp = Dispatcher()
_bot: Optional[Bot] = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=settings.telegram_bot_token,
                    default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    return _bot


def webapp_base_url() -> str:
    """Where this backend (and the Mini App it serves) is actually
    reachable from the outside — explicit WEBAPP_URL if set, otherwise
    Render's own auto-injected RENDER_EXTERNAL_URL (present automatically
    on every Render web service, no configuration needed)."""
    return (settings.webapp_url or os.environ.get("RENDER_EXTERNAL_URL", "")).rstrip("/")


# ------------------------------------------------------- private menu ----
# A persistent reply keyboard (not inline) so it's always sitting above the
# keyboard in the private chat, not tied to any one message. Button labels
# come from app/i18n.py so each user sees them in their own language —
# since a ReplyKeyboardMarkup button is matched by its literal text, every
# handler below filters on button_texts(key) (all languages' labels), not
# a single fixed string.


def menu_for(user_id: int, lang: str) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=button_text("start_group_game", lang)),
         KeyboardButton(text=button_text("roles", lang))],
        [KeyboardButton(text=button_text("my_stats", lang)),
         KeyboardButton(text=button_text("about", lang))],
        [KeyboardButton(text=button_text("contact_admin", lang))],
        [KeyboardButton(text=BTN_LANGUAGE)],
    ]
    if user_id in settings.admin_telegram_ids:
        rows.append([KeyboardButton(text=button_text("admin_panel", lang))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


# In-memory: telegram_user_id -> waiting for their next private message to
# relay to the admins. Losing this on a restart just means they have to
# tap the button again — not worth persisting.
_awaiting_admin_message: set[int] = set()
_awaiting_forcesub_input: set[int] = set()
_awaiting_broadcast_input: set[int] = set()


# ------------------------------------------------------------- language --
@dp.message(F.text == BTN_LANGUAGE, F.chat.type == ChatType.PRIVATE)
async def on_language_button(message: Message) -> None:
    lang = await get_user_language(message.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"setlang:{code}")]
        for code, label in LANGUAGE_LABELS.items()
    ])
    await message.answer(t("language_prompt", lang), reply_markup=kb)


@dp.callback_query(F.data.startswith("setlang:"))
async def on_language_picked(callback: CallbackQuery) -> None:
    lang = callback.data.split(":", 1)[1]
    if lang not in SUPPORTED_LANGUAGES:
        return
    await set_user_language(callback.from_user.id, lang)
    await callback.answer()
    await callback.message.edit_text(t("language_set", lang))
    await callback.message.answer(t("use_menu_below", lang),
                                   reply_markup=menu_for(callback.from_user.id, lang))


# --------------------------------------------------- mandatory sub-check --
FORCE_SUB_SETTING_KEY = "force_sub_channel"


async def get_force_sub_channel() -> Optional[str]:
    """The @username or numeric chat id of the channel users must join to
    use the bot, or None if the bot owner hasn't turned this on."""
    async with AsyncSessionLocal() as session:
        row = await session.get(BotSetting, FORCE_SUB_SETTING_KEY)
        return row.value if row and row.value else None


async def set_force_sub_channel(channel: Optional[str]) -> None:
    async with AsyncSessionLocal() as session:
        row = await session.get(BotSetting, FORCE_SUB_SETTING_KEY)
        if row is None:
            row = BotSetting(key=FORCE_SUB_SETTING_KEY, value=channel or "")
            session.add(row)
        else:
            row.value = channel or ""
        await session.commit()


async def check_force_sub(user_id: int) -> tuple[bool, Optional[str]]:
    """(is_allowed, channel). channel is None when no gate is configured,
    in which case is_allowed is always True."""
    channel = await get_force_sub_channel()
    if not channel:
        return True, None
    return await verify_group_membership(channel, user_id), channel


def _force_sub_prompt(channel: str, lang: str) -> tuple[str, InlineKeyboardMarkup]:
    link = channel if channel.startswith("http") else f"https://t.me/{channel.lstrip('@')}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("force_sub_go_to_channel", lang), url=link)],
        [InlineKeyboardButton(text=t("force_sub_check", lang), callback_data="checksub")],
    ])
    return t("force_sub_prompt", lang), kb


@dp.callback_query(F.data == "checksub")
async def on_check_sub(callback: CallbackQuery) -> None:
    lang = await get_user_language(callback.from_user.id)
    ok, channel = await check_force_sub(callback.from_user.id)
    if not ok:
        await callback.answer(t("force_sub_not_yet", lang), show_alert=True)
        return
    await callback.answer(t("force_sub_confirmed", lang))
    await callback.message.edit_text(t("force_sub_confirmed_body", lang))
    await callback.message.answer(t("use_menu_below", lang),
                                   reply_markup=menu_for(callback.from_user.id, lang))


# --------------------------------------------------------- known groups --
async def upsert_known_group(chat_id: int, title: str, is_active: bool) -> None:
    async with AsyncSessionLocal() as session:
        row = await session.get(KnownGroup, chat_id)
        if row is None:
            session.add(KnownGroup(chat_id=chat_id, title=title, is_active=is_active))
        else:
            row.title = title or row.title
            row.is_active = is_active
            row.updated_at = datetime.now(timezone.utc)
        await session.commit()


@dp.my_chat_member(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def on_bot_membership_changed(event: ChatMemberUpdated) -> None:
    """Telegram's Bot API has no "list every group I'm in" call, so this is
    the only way the bot can ever know which groups exist for the "Guruhda
    o'yin boshlash" picker below — it has to notice itself being added or
    removed, as it happens, and remember."""
    status = event.new_chat_member.status
    is_active = status not in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED)
    await upsert_known_group(event.chat.id, event.chat.title or "", is_active)


# ------------------------------------------------------------- /start ----
async def post_join_button(chat_id: int) -> None:
    base_url = webapp_base_url()
    if not base_url:
        # Would otherwise build an invalid (relative) web_app URL that
        # Telegram rejects with a cryptic Bad Request — surface the real
        # cause plainly instead of letting that generic error confuse
        # whoever's debugging it.
        raise TelegramBadRequest(
            method=None,
            message="WEBAPP_URL/RENDER_EXTERNAL_URL is not set — cannot build a webapp link",
        )
    webapp_url = f"{base_url}/?chat_id={chat_id}"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎭 O'yinga qo'shilish", web_app=WebAppInfo(url=webapp_url)),
    ]])
    await get_bot().send_message(
        chat_id,
        "🌙 <b>MAFIA</b> boshlanmoqda!\n\n"
        "Qo'shilish uchun quyidagi tugmani bosing.\n"
        "Kamida <b>6</b> kishi yig'ilsa, o'yinni boshlash mumkin bo'ladi.\n"
        "<b>25</b> kishi to'lsa — o'yin avtomatik boshlanadi.",
        reply_markup=keyboard,
    )


@dp.message(Command("start"), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def start_in_group(message: Message) -> None:
    """The one and only entry point into a match — same as bot/bot.py's
    polling version. There is no "create game" command; every tap of this
    button lands on POST /games/for-chat, which creates the group's match
    on the first tap and joins everyone else into that same match after."""
    await upsert_known_group(message.chat.id, message.chat.title or "", True)
    await post_join_button(message.chat.id)


@dp.message(Command("start"), F.chat.type == ChatType.PRIVATE)
async def start_in_private(message: Message) -> None:
    tg_user = message.from_user
    async with AsyncSessionLocal() as session:
        await get_or_create_user(session, tg_user.id, tg_user.first_name,
                                  tg_user.last_name, tg_user.username, None)

    lang = await get_user_language(tg_user.id)
    ok, channel = await check_force_sub(tg_user.id)
    if not ok:
        text, kb = _force_sub_prompt(channel, lang)
        await message.answer(text, reply_markup=kb)
        return

    await message.answer(t("start_private_welcome", lang), reply_markup=menu_for(tg_user.id, lang))


@dp.message(Command("admin"), F.chat.type == ChatType.PRIVATE)
async def admin_panel_command(message: Message) -> None:
    await _open_admin_panel(message)


# ------------------------------------------------------ menu: Admin paneli
# The primary way in — a row on the bottom keyboard itself (see menu_for),
# shown only to admin_telegram_ids, so the panel never needs the /admin
# command to be remembered. /admin above is kept as a harmless alternative
# for anyone who prefers to type it.
@dp.message(F.text.in_(button_texts("admin_panel")), F.chat.type == ChatType.PRIVATE)
async def on_admin_panel_button(message: Message) -> None:
    await _open_admin_panel(message)


# ----------------------------------------------------- menu: Bot haqida --
@dp.message(F.text.in_(button_texts("about")), F.chat.type == ChatType.PRIVATE)
async def on_about(message: Message) -> None:
    lang = await get_user_language(message.from_user.id)
    await message.answer(t(
        "about_body", lang,
        start_group_game=button_text("start_group_game", lang),
        roles=button_text("roles", lang),
        my_stats=button_text("my_stats", lang),
        contact_admin=button_text("contact_admin", lang),
    ))


# ----------------------------------------------------- menu: Statistikam -
@dp.message(F.text.in_(button_texts("my_stats")), F.chat.type == ChatType.PRIVATE)
async def on_my_stats(message: Message) -> None:
    lang = await get_user_language(message.from_user.id)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_user_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

    if user is None or user.games_played == 0:
        await message.answer(t("stats_none_yet", lang))
        return

    win_rate = round(100 * user.wins / user.games_played)
    await message.answer(t(
        "stats_body", lang,
        games_played=user.games_played, wins=user.wins, win_rate=win_rate,
        losses=user.losses, town_wins=user.town_wins,
        mafia_wins=user.mafia_wins, neutral_wins=user.neutral_wins,
    ))


# ----------------------------------------------------------- menu: Rollar -
@dp.message(F.text.in_(button_texts("roles")), F.chat.type == ChatType.PRIVATE)
async def on_roles_button(message: Message) -> None:
    lang = await get_user_language(message.from_user.id)
    ok, channel = await check_force_sub(message.from_user.id)
    if not ok:
        text, kb = _force_sub_prompt(channel, lang)
        await message.answer(text, reply_markup=kb)
        return

    # ?view=roles tells the webapp (app/static/app.js) to open straight into
    # the Roles tab with the rest of the navigation hidden — see that
    # file's boot() for how the query param is read. lang= lets the webapp
    # open already translated instead of defaulting to Uzbek and flashing
    # a language switch a moment later.
    url = f"{webapp_base_url()}/?view=roles&lang={lang}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t("roles_open_button", lang), web_app=WebAppInfo(url=url)),
    ]])
    await message.answer(t("roles_prompt", lang), reply_markup=kb)


# ------------------------------------------- menu: Guruhda o'yin boshlash -
@dp.message(F.text.in_(button_texts("start_group_game")), F.chat.type == ChatType.PRIVATE)
async def on_start_group_game(message: Message) -> None:
    lang = await get_user_language(message.from_user.id)
    ok, channel = await check_force_sub(message.from_user.id)
    if not ok:
        text, kb = _force_sub_prompt(channel, lang)
        await message.answer(text, reply_markup=kb)
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(KnownGroup).where(KnownGroup.is_active.is_(True)))
        groups = result.scalars().all()

    if not groups:
        await message.answer(t("no_groups_known", lang))
        return

    # Telegram's Bot API has no "which groups is this user in" call, so
    # membership is checked one known group at a time — fine at the
    # friend-group scale this bot is built for (see render.yaml).
    matches = []
    for g in groups:
        if await verify_group_membership(str(g.chat_id), message.from_user.id):
            matches.append(g)

    if not matches:
        await message.answer(t("no_matching_groups", lang))
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=g.title or f"Guruh {g.chat_id}",
                               callback_data=f"startgame:{g.chat_id}")]
        for g in matches[:20]
    ])
    await message.answer(t("pick_a_group", lang), reply_markup=kb)


@dp.callback_query(F.data.startswith("startgame:"))
async def on_group_picked(callback: CallbackQuery) -> None:
    lang = await get_user_language(callback.from_user.id)
    chat_id = int(callback.data.split(":", 1)[1])
    # Re-verify at click time too — the list shown could be stale by now.
    if not await verify_group_membership(str(chat_id), callback.from_user.id):
        await callback.answer(t("not_a_member_alert", lang), show_alert=True)
        return

    try:
        await post_join_button(chat_id)
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        # Whatever Telegram actually said (not a guess) — logged in full for
        # the bot owner, and shown to the user too: a swallowed "may have
        # been removed" guess hides real causes like an invalid webapp URL
        # or a group that restricts messaging to admins-only.
        logger.warning("post_join_button failed for chat_id=%s: %s: %s",
                        chat_id, type(e).__name__, e)
        error_text = str(e)
        await callback.answer(
            t("could_not_post_to_group_alert", lang, error=error_text[:120]),
            show_alert=True,
        )
        await callback.message.answer(t("could_not_post_to_group_details", lang, error=error_text))
        return

    await callback.answer(t("sent_confirmation", lang))
    await callback.message.edit_text(t("group_link_sent", lang))


# --------------------------------------------- menu: Admin bilan bog'lanish
@dp.message(F.text.in_(button_texts("contact_admin")), F.chat.type == ChatType.PRIVATE)
async def on_contact_admin(message: Message) -> None:
    lang = await get_user_language(message.from_user.id)
    if not settings.admin_telegram_ids:
        await message.answer(t("admin_not_configured", lang))
        return
    _awaiting_admin_message.add(message.from_user.id)
    await message.answer(t("ask_admin_message", lang))


async def _relay_to_admins(message: Message) -> None:
    """Copies a user's free-text message to every configured admin and
    remembers which admin got which copy, so whichever one replies (a
    Telegram reply-to on their own copy) gets routed back to this same
    user — see on_admin_reply below. The forwarded copy the ADMIN sees
    stays Uzbek-only, same scope note as the rest of the admin panel."""
    lang = await get_user_language(message.from_user.id)
    tg_user = message.from_user
    display_name = (f"@{tg_user.username}" if tg_user.username
                     else f"{tg_user.first_name} {tg_user.last_name or ''}".strip())

    sent_to_anyone = False
    async with AsyncSessionLocal() as session:
        for admin_id in settings.admin_telegram_ids:
            try:
                copy = await get_bot().send_message(
                    admin_id,
                    f"✉️ <b>{display_name}</b> (id: <code>{tg_user.id}</code>) dan xabar:\n\n"
                    f"{message.text}",
                )
            except (TelegramForbiddenError, TelegramBadRequest):
                # That admin has never started the bot, or has blocked it —
                # skip them, other admins may still be reachable.
                continue
            sent_to_anyone = True
            session.add(SupportMessage(
                user_telegram_id=tg_user.id, user_display_name=display_name,
                admin_telegram_id=admin_id, admin_copy_message_id=copy.message_id,
                original_text=message.text[:4096],
            ))
        await session.commit()

    if sent_to_anyone:
        await message.answer(t("admin_message_sent", lang))
    else:
        await message.answer(t("admin_message_failed", lang))


async def on_admin_reply(message: Message) -> None:
    """An admin, in their own private chat with the bot, replied to one of
    the forwarded copies from _relay_to_admins — route their reply text
    back to the original user, in THAT user's own language (not the
    admin's), since this part is player-facing."""
    replied_to = message.reply_to_message
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SupportMessage).where(
                SupportMessage.admin_telegram_id == message.from_user.id,
                SupportMessage.admin_copy_message_id == replied_to.message_id,
            )
        )
        support_row = result.scalar_one_or_none()
        if support_row is None:
            return
        support_row.replied = True
        await session.commit()
        target_user_id = support_row.user_telegram_id

    target_lang = await get_user_language(target_user_id)
    try:
        await get_bot().send_message(target_user_id, t("admin_reply_label", target_lang, text=message.text))
        await message.reply("✅ Yuborildi.")
    except (TelegramForbiddenError, TelegramBadRequest):
        await message.reply("Foydalanuvchiga yubora olmadim — u botni bloklagan bo'lishi mumkin.")


# ------------------------------------------------------------ admin panel -
async def _bot_admin_stats() -> dict:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        total_users = (await session.execute(select(func.count()).select_from(User))).scalar_one()
        new_today = (await session.execute(
            select(func.count()).select_from(User).where(User.created_at >= now - timedelta(days=1))
        )).scalar_one()
        new_week = (await session.execute(
            select(func.count()).select_from(User).where(User.created_at >= now - timedelta(days=7))
        )).scalar_one()
        total_groups = (await session.execute(
            select(func.count()).select_from(KnownGroup).where(KnownGroup.is_active.is_(True))
        )).scalar_one()
    return {"total_users": total_users, "new_today": new_today,
            "new_week": new_week, "total_groups": total_groups}


def _admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Statistika", callback_data="admin:stats")],
        [InlineKeyboardButton(text="📢 Xabar yuborish", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="📡 Majburiy obuna", callback_data="admin:forcesub")],
        [InlineKeyboardButton(text="🏆 Top o'yinchilar", callback_data="admin:top")],
    ])


async def _open_admin_panel(message: Message) -> None:
    if message.from_user.id not in settings.admin_telegram_ids:
        return
    await message.answer("🛠 <b>Admin paneli</b>", reply_markup=_admin_panel_keyboard())


def _require_admin_callback(callback: CallbackQuery) -> bool:
    return callback.from_user.id in settings.admin_telegram_ids


@dp.callback_query(F.data == "admin:stats")
async def on_admin_stats(callback: CallbackQuery) -> None:
    if not _require_admin_callback(callback):
        await callback.answer("Siz admin emassiz.", show_alert=True)
        return
    stats = await _bot_admin_stats()
    await callback.answer()
    await callback.message.edit_text(
        "📊 <b>Statistika</b>\n\n"
        f"Jami foydalanuvchilar: <b>{stats['total_users']}</b>\n"
        f"Bugun qo'shilgan: <b>{stats['new_today']}</b>\n"
        f"Shu hafta qo'shilgan: <b>{stats['new_week']}</b>\n"
        f"Faol guruhlar: <b>{stats['total_groups']}</b>",
        reply_markup=_admin_panel_keyboard(),
    )


@dp.callback_query(F.data == "admin:top")
async def on_admin_top(callback: CallbackQuery) -> None:
    if not _require_admin_callback(callback):
        await callback.answer("Siz admin emassiz.", show_alert=True)
        return
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.games_played > 0).order_by(User.wins.desc()).limit(10)
        )
        top_users = result.scalars().all()
    await callback.answer()
    if not top_users:
        text = "🏆 Hali hech kim o'yin yakunlamagan."
    else:
        lines = ["🏆 <b>Top o'yinchilar (g'alabalar bo'yicha)</b>", ""]
        for i, u in enumerate(top_users, start=1):
            name = f"@{u.username}" if u.username else u.first_name
            lines.append(f"{i}. {name} — {u.wins} g'alaba ({u.games_played} o'yin)")
        text = "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=_admin_panel_keyboard())


@dp.callback_query(F.data == "admin:forcesub")
async def on_admin_forcesub(callback: CallbackQuery) -> None:
    if not _require_admin_callback(callback):
        await callback.answer("Siz admin emassiz.", show_alert=True)
        return
    current = await get_force_sub_channel()
    _awaiting_forcesub_input.add(callback.from_user.id)
    await callback.answer()
    status = f"Joriy kanal: <code>{current}</code>" if current else "Hozir o'chirilgan."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ O'chirish", callback_data="admin:forcesub_off")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin:back")],
    ])
    await callback.message.edit_text(
        "📡 <b>Majburiy obuna</b>\n\n"
        f"{status}\n\n"
        "Yangi kanal o'rnatish uchun kanal username'ini "
        "(<code>@kanalim</code>) yoki uning raqamli ID'sini yozib yuboring.",
        reply_markup=kb,
    )


@dp.callback_query(F.data == "admin:forcesub_off")
async def on_admin_forcesub_off(callback: CallbackQuery) -> None:
    if not _require_admin_callback(callback):
        await callback.answer("Siz admin emassiz.", show_alert=True)
        return
    await set_force_sub_channel(None)
    _awaiting_forcesub_input.discard(callback.from_user.id)
    await callback.answer("O'chirildi.")
    await callback.message.edit_text("📡 Majburiy obuna o'chirildi.", reply_markup=_admin_panel_keyboard())


@dp.callback_query(F.data == "admin:back")
async def on_admin_back(callback: CallbackQuery) -> None:
    if not _require_admin_callback(callback):
        await callback.answer("Siz admin emassiz.", show_alert=True)
        return
    _awaiting_forcesub_input.discard(callback.from_user.id)
    _awaiting_broadcast_input.discard(callback.from_user.id)
    await callback.answer()
    await callback.message.edit_text("🛠 <b>Admin paneli</b>", reply_markup=_admin_panel_keyboard())


@dp.callback_query(F.data == "admin:broadcast")
async def on_admin_broadcast_prompt(callback: CallbackQuery) -> None:
    if not _require_admin_callback(callback):
        await callback.answer("Siz admin emassiz.", show_alert=True)
        return
    _awaiting_broadcast_input.add(callback.from_user.id)
    await callback.answer()
    await callback.message.edit_text(
        "📢 Barcha foydalanuvchilarga yuboriladigan xabar matnini yozing.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Bekor qilish", callback_data="admin:back")],
        ]),
    )


async def _run_broadcast(message: Message) -> None:
    text = message.text
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User.telegram_user_id))
        user_ids = [row[0] for row in result.all()]

    sent, failed = 0, 0
    for uid in user_ids:
        try:
            await get_bot().send_message(uid, text)
            sent += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1
    await message.answer(
        f"📢 Xabar yuborildi.\n\n✅ Yetkazildi: {sent}\n🚫 Yetkazilmadi: {failed}",
        reply_markup=_admin_panel_keyboard(),
    )


async def _handle_admin_text_input(message: Message) -> bool:
    """Returns True if this message was consumed as admin-panel input
    (force-sub channel, broadcast text) so no other handler should also
    process it."""
    admin_id = message.from_user.id
    if admin_id in _awaiting_forcesub_input:
        _awaiting_forcesub_input.discard(admin_id)
        channel = message.text.strip()
        await set_force_sub_channel(channel)
        await message.answer(f"✅ Majburiy obuna kanali o'rnatildi: <code>{channel}</code>",
                              reply_markup=_admin_panel_keyboard())
        return True

    if admin_id in _awaiting_broadcast_input:
        _awaiting_broadcast_input.discard(admin_id)
        await _run_broadcast(message)
        return True

    return False


# ------------------------------------------------- private catch-all text -
# Registered last on purpose: every specific handler above (menu buttons)
# matches first when it applies, so this only ever catches free-form text —
# an admin's reply-to on a relayed message, admin-panel input (force-sub
# channel, broadcast body), a user's message while _awaiting_admin_message,
# or (falling through) a nudge back to the menu. admin_telegram_ids is read
# here at call time (not baked into a filter at import time), so it always
# reflects whatever settings.admin_telegram_ids currently holds.
@dp.message(F.chat.type == ChatType.PRIVATE, F.text)
async def on_private_text(message: Message) -> None:
    is_admin = message.from_user.id in settings.admin_telegram_ids

    if is_admin and message.reply_to_message is not None:
        await on_admin_reply(message)
        return
    if is_admin and await _handle_admin_text_input(message):
        return
    if message.from_user.id in _awaiting_admin_message:
        _awaiting_admin_message.discard(message.from_user.id)
        await _relay_to_admins(message)
        return
    lang = await get_user_language(message.from_user.id)
    await message.answer(t("command_not_understood", lang), reply_markup=menu_for(message.from_user.id, lang))


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
) -> dict:
    """Telegram POSTs every update here instead of us polling for them.
    The secret-token header is Telegram's own mechanism for proving a
    request really came from them (set via set_webhook(secret_token=...)
    in register_webhook() below) — without checking it, this public URL
    would accept a forged update from anyone who found it."""
    if not settings.telegram_webhook_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid secret token")
    bot = get_bot()
    update = Update.model_validate(await request.json(), context={"bot": bot})
    await dp.feed_update(bot, update)
    return {"ok": True}


async def register_webhook() -> None:
    """Called once from the backend's own startup (see app/main.py's
    lifespan) — the single deployed web service registers its own webhook
    with Telegram, no separate bot process or manual setWebhook call
    needed."""
    base_url = webapp_base_url()
    if not base_url:
        logger.warning(
            "telegram_webhook_enabled is set but no public URL is known "
            "(WEBAPP_URL or RENDER_EXTERNAL_URL) — skipping set_webhook"
        )
        return
    await get_bot().set_webhook(
        url=f"{base_url}/bot/webhook",
        secret_token=settings.telegram_webhook_secret,
        drop_pending_updates=True,
    )
    logger.info("Telegram webhook registered at %s/bot/webhook", base_url)
