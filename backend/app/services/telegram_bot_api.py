"""
Verifies, via Telegram's own Bot API, that the person calling
POST /games/for-chat with a given chat_id is actually a member of that
Telegram group right now.

Without this, chat_id is just a client-supplied URL query string —
initData proves *who* is calling, but says nothing about *which group*
they claim to be sitting in. A valid Telegram user could otherwise type
any group's chat_id into the Mini App URL and join (or even become host
of, and start) a match for a group they were never a member of. This
closes that gap.
"""
from __future__ import annotations
import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger("mafia.telegram_bot_api")

# Telegram's ChatMember.status values for someone currently in the chat.
# "left" and "kicked" (and anything else/unexpected) are NOT membership.
ACTIVE_MEMBER_STATUSES = {"creator", "administrator", "member", "restricted"}


async def verify_group_membership(chat_id: str, telegram_user_id: int) -> bool:
    """True only if Telegram itself confirms telegram_user_id is currently
    a member of chat_id (via getChatMember). Fails closed: a bad token, an
    unresolvable chat_id, a network hiccup, or any unexpected response is
    treated as "not a member" — the whole point of this check is to be the
    thing that says no when it can't be sure."""
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getChatMember"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params={"chat_id": chat_id, "user_id": telegram_user_id})
        data = resp.json()
    except Exception:
        logger.exception(
            "getChatMember failed for chat_id=%s user_id=%s — denying by default",
            chat_id, telegram_user_id,
        )
        return False

    if not data.get("ok"):
        return False
    status: Optional[str] = data.get("result", {}).get("status")
    return status in ACTIVE_MEMBER_STATUSES
