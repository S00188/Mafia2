"""Verifies /games/for-chat rejects anyone Telegram doesn't confirm as a
CURRENT member of the chat_id they're claiming (see
app/services/telegram_bot_api.py) — closing the gap where chat_id was just
a client-supplied URL query string with nothing checking it."""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient, ASGITransport

from app.config import settings
settings.telegram_bot_token = "TEST-TOKEN"
settings.database_url = "sqlite+aiosqlite:///:memory:"

from app.main import app  # noqa: E402
from app.database import init_db  # noqa: E402
from app.api import routes_game  # noqa: E402


@pytest.fixture(autouse=True)
async def _ensure_tables():
    await init_db()


def _init_data_for(user_id: int, name: str) -> str:
    fields = {
        "user": json.dumps({"id": user_id, "first_name": name}, separators=(",", ":")),
        "auth_date": str(int(time.time())),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.mark.asyncio
async def test_non_member_is_rejected_with_403(monkeypatch):
    async def _not_a_member(chat_id, telegram_user_id):
        return False
    monkeypatch.setattr(routes_game, "verify_group_membership", _not_a_member)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login = await ac.post("/auth/telegram", json={"init_data": _init_data_for(9001, "Outsider")})
        token = login.json()["session_token"]
        r = await ac.post("/games/for-chat", json={"chat_id": "-100999", "display_name": "Outsider"},
                           headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_real_member_is_let_through(monkeypatch):
    async def _is_a_member(chat_id, telegram_user_id):
        return True
    monkeypatch.setattr(routes_game, "verify_group_membership", _is_a_member)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login = await ac.post("/auth/telegram", json={"init_data": _init_data_for(9002, "RealMember")})
        token = login.json()["session_token"]
        r = await ac.post("/games/for-chat", json={"chat_id": "-100998", "display_name": "RealMember"},
                           headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["created"] is True


@pytest.mark.asyncio
async def test_membership_is_checked_before_a_match_is_created(monkeypatch):
    """A rejected outsider must not leave a phantom match behind for that
    chat_id — the next real member to try should still get to create it."""
    from app.services.game_service import registry

    async def _not_a_member(chat_id, telegram_user_id):
        return False
    monkeypatch.setattr(routes_game, "verify_group_membership", _not_a_member)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login = await ac.post("/auth/telegram", json={"init_data": _init_data_for(9003, "Faker")})
        token = login.json()["session_token"]
        r = await ac.post("/games/for-chat", json={"chat_id": "-100997", "display_name": "Faker"},
                           headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403
        assert registry.get_by_chat("-100997") is None

    async def _is_a_member(chat_id, telegram_user_id):
        return True
    monkeypatch.setattr(routes_game, "verify_group_membership", _is_a_member)

    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login = await ac.post("/auth/telegram", json={"init_data": _init_data_for(9004, "RealOne")})
        token = login.json()["session_token"]
        r = await ac.post("/games/for-chat", json={"chat_id": "-100997", "display_name": "RealOne"},
                           headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["created"] is True
