"""Covers the new DB-backed helpers behind the bot's private-chat menu
(app/telegram_bot.py): known-group tracking for the "Guruhda o'yin
boshlash" picker, the mandatory-subscription gate, and the admin panel's
stats query. These are plain async functions with no aiogram Message/
CallbackQuery involved, so they're tested directly rather than through a
simulated conversation — see test_telegram_webhook.py for why constructing
real aiogram objects is avoided in this suite."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import settings
settings.telegram_bot_token = "TEST-TOKEN"
settings.database_url = "sqlite+aiosqlite:///:memory:"

import app.telegram_bot as tb  # noqa: E402
from app.database import AsyncSessionLocal, init_db  # noqa: E402
from app.models.models import KnownGroup, User  # noqa: E402
from app.services.game_service import get_or_create_user  # noqa: E402


@pytest.fixture(autouse=True)
async def _ensure_tables():
    await init_db()


# ------------------------------------------------------- known groups ----
@pytest.mark.asyncio
async def test_upsert_known_group_inserts_then_updates():
    await tb.upsert_known_group(chat_id=-100123, title="Do'stlar", is_active=True)

    async with AsyncSessionLocal() as session:
        row = await session.get(KnownGroup, -100123)
        assert row.title == "Do'stlar"
        assert row.is_active is True

    # Bot removed from the group later — same row, flipped to inactive.
    await tb.upsert_known_group(chat_id=-100123, title="Do'stlar", is_active=False)

    async with AsyncSessionLocal() as session:
        row = await session.get(KnownGroup, -100123)
        assert row.is_active is False


@pytest.mark.asyncio
async def test_upsert_known_group_keeps_title_when_blank():
    await tb.upsert_known_group(chat_id=-100456, title="Real Title", is_active=True)
    # A later event with no title (edge case Telegram could send) shouldn't
    # blank out a title we already have.
    await tb.upsert_known_group(chat_id=-100456, title="", is_active=True)

    async with AsyncSessionLocal() as session:
        row = await session.get(KnownGroup, -100456)
        assert row.title == "Real Title"


# ------------------------------------------------------ force-subscribe --
@pytest.mark.asyncio
async def test_force_sub_channel_round_trip():
    assert await tb.get_force_sub_channel() is None

    await tb.set_force_sub_channel("@mychannel")
    assert await tb.get_force_sub_channel() == "@mychannel"

    await tb.set_force_sub_channel(None)
    assert await tb.get_force_sub_channel() is None


@pytest.mark.asyncio
async def test_check_force_sub_passes_when_unset(monkeypatch):
    await tb.set_force_sub_channel(None)
    ok, channel = await tb.check_force_sub(user_id=555)
    assert ok is True
    assert channel is None


@pytest.mark.asyncio
async def test_check_force_sub_defers_to_membership_check(monkeypatch):
    await tb.set_force_sub_channel("@required")

    async def fake_membership(chat_id, telegram_user_id):
        assert chat_id == "@required"
        return telegram_user_id == 42

    monkeypatch.setattr(tb, "verify_group_membership", fake_membership)

    ok, channel = await tb.check_force_sub(user_id=42)
    assert ok is True
    assert channel == "@required"

    ok, channel = await tb.check_force_sub(user_id=99)
    assert ok is False
    assert channel == "@required"


# -------------------------------------------------------- admin stats ----
@pytest.mark.asyncio
async def test_bot_admin_stats_counts_users_and_groups():
    # This DB is a single shared in-memory instance for the whole test
    # session (see app/database.py's StaticPool for ":memory:"), so other
    # test files' rows are already sitting in it — assert on the *change*
    # this test causes, not on absolute totals (same approach
    # test_admin_bot_owner.py's /admin/stats test takes).
    before = await tb._bot_admin_stats()

    async with AsyncSessionLocal() as session:
        await get_or_create_user(session, 910001, "Alice", None, "alice", None)
        await get_or_create_user(session, 910002, "Bob", None, "bob", None)
        # Backdate one user to look like they joined 2 weeks ago, so the
        # "new today"/"new this week" windows can be told apart from the
        # "total users" count.
        result = await session.execute(select(User).where(User.telegram_user_id == 910002))
        bob = result.scalar_one()
        bob.created_at = datetime.now(timezone.utc) - timedelta(days=14)
        await session.commit()

    active_chat_id, inactive_chat_id = -910001, -910002
    await tb.upsert_known_group(chat_id=active_chat_id, title="G1", is_active=True)
    await tb.upsert_known_group(chat_id=inactive_chat_id, title="G2 (chiqib ketgan)", is_active=False)

    after = await tb._bot_admin_stats()
    assert after["total_users"] - before["total_users"] == 2
    assert after["new_today"] - before["new_today"] == 1
    assert after["new_week"] - before["new_week"] == 1
    assert after["total_groups"] - before["total_groups"] == 1  # only the active one


# ------------------------------------------------------- support relay ---
class _FakeSentMessage:
    def __init__(self, message_id: int):
        self.message_id = message_id


class _FakeBot:
    """Stands in for get_bot() so _relay_to_admins/on_admin_reply can be
    tested without a real Telegram Bot object or network call."""

    def __init__(self):
        self.sent = []  # list of (chat_id, text)
        self._next_id = 1

    async def send_message(self, chat_id, text, **kwargs):
        msg = _FakeSentMessage(self._next_id)
        self._next_id += 1
        self.sent.append((chat_id, text, msg.message_id))
        return msg


class _FakeUser:
    def __init__(self, id, username=None, first_name="Test", last_name=None):
        self.id = id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name


class _FakeMessage:
    def __init__(self, from_user, text, reply_to_message=None):
        self.from_user = from_user
        self.text = text
        self.reply_to_message = reply_to_message
        self.answered = []
        self.replied = []

    async def answer(self, text, **kwargs):
        self.answered.append(text)

    async def reply(self, text, **kwargs):
        self.replied.append(text)


class _FakeRepliedTo:
    def __init__(self, message_id):
        self.message_id = message_id


@pytest.mark.asyncio
async def test_relay_to_admins_and_admin_reply_round_trip(monkeypatch):
    settings.admin_telegram_ids = [900001]
    fake_bot = _FakeBot()
    monkeypatch.setattr(tb, "get_bot", lambda: fake_bot)

    user_msg = _FakeMessage(_FakeUser(id=555, username="asker"), "Salom, savolim bor")
    await tb._relay_to_admins(user_msg)

    # The admin got a copy, and the user was told it went through.
    assert len(fake_bot.sent) == 1
    admin_chat_id, forwarded_text, admin_copy_id = fake_bot.sent[0]
    assert admin_chat_id == 900001
    assert "Salom, savolim bor" in forwarded_text
    assert any("yuborildi" in t for t in user_msg.answered)

    # Admin replies to that forwarded copy.
    admin_reply = _FakeMessage(
        _FakeUser(id=900001), "Albatta, mana javob",
        reply_to_message=_FakeRepliedTo(admin_copy_id),
    )
    await tb.on_admin_reply(admin_reply)

    # The original user (555) receives the admin's reply text.
    relayed = [s for s in fake_bot.sent if s[0] == 555]
    assert len(relayed) == 1
    assert "Albatta, mana javob" in relayed[0][1]
    assert any("Yuborildi" in t for t in admin_reply.replied)
