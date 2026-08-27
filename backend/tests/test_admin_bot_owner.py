"""The bot-owner global admin panel: /admin/* endpoints, gated by
settings.admin_telegram_ids rather than any single match's host_id, and
usable without the caller ever having joined the game they're managing."""
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
settings.admin_telegram_ids = [900001]

from app.main import app  # noqa: E402
from app.database import init_db  # noqa: E402
from app.services.game_service import registry  # noqa: E402

ADMIN_ID = 900001
NON_ADMIN_ID = 900002


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


async def _login(ac: AsyncClient, user_id: int, name: str) -> dict:
    r = await ac.post("/auth/telegram", json={"init_data": _init_data_for(user_id, name)})
    assert r.status_code == 200
    return r.json()


async def _make_lobby_game(ac: AsyncClient, chat_id: str, n_players: int = 6) -> str:
    """Populates a real match via the normal for-chat path (the chat
    membership check is already mocked to allow everyone by conftest's
    autouse fixture) and returns its game_id."""
    game_id = None
    for i in range(1, n_players + 1):
        body = await _login(ac, 800000 + i, f"P{i}")
        r = await ac.post("/games/for-chat", json={"chat_id": chat_id, "display_name": f"P{i}"},
                           headers={"Authorization": f"Bearer {body['session_token']}"})
        assert r.status_code == 200
        game_id = r.json()["game_id"]
    return game_id


@pytest.fixture(autouse=True)
def _clear_registry():
    yield
    for engine in list(registry.all_engines()):
        registry.remove(engine.state.game_id)


# ---------- login response flags the bot owner ----------

@pytest.mark.asyncio
async def test_login_response_flags_bot_owner():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        admin_body = await _login(ac, ADMIN_ID, "Owner")
        other_body = await _login(ac, NON_ADMIN_ID, "Regular")
    assert admin_body["is_bot_admin"] is True
    assert other_body["is_bot_admin"] is False


# ---------- require_bot_admin gate ----------

@pytest.mark.asyncio
async def test_non_admin_gets_403_on_admin_routes():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        body = await _login(ac, NON_ADMIN_ID, "Regular")
        r = await ac.get("/admin/games", headers={"Authorization": f"Bearer {body['session_token']}"})
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_list_games():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        game_id = await _make_lobby_game(ac, "-100111")
        admin_body = await _login(ac, ADMIN_ID, "Owner")
        r = await ac.get("/admin/games", headers={"Authorization": f"Bearer {admin_body['session_token']}"})
        assert r.status_code == 200
        games = r.json()["games"]
        assert any(g["game_id"] == game_id for g in games)


@pytest.mark.asyncio
async def test_admin_game_detail_exposes_real_roles():
    """The one place in the whole API that's allowed to reveal hidden
    roles — because the caller is the bot owner, not a player."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        game_id = await _make_lobby_game(ac, "-100112")
        admin_body = await _login(ac, ADMIN_ID, "Owner")
        headers = {"Authorization": f"Bearer {admin_body['session_token']}"}
        r = await ac.get(f"/admin/games/{game_id}", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert len(body["players"]) == 6
        assert body["phase"] == "lobby"


@pytest.mark.asyncio
async def test_admin_can_update_settings_without_being_a_player():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        game_id = await _make_lobby_game(ac, "-100113")
        admin_body = await _login(ac, ADMIN_ID, "Owner")
        headers = {"Authorization": f"Bearer {admin_body['session_token']}"}
        r = await ac.post(f"/admin/games/{game_id}/settings",
                           json={"settings": {"night_duration_s": 20}}, headers=headers)
        assert r.status_code == 200
        detail = (await ac.get(f"/admin/games/{game_id}", headers=headers)).json()
        assert detail["settings"]["night_duration_s"] == 20


@pytest.mark.asyncio
async def test_admin_can_remove_a_player():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        game_id = await _make_lobby_game(ac, "-100114")
        admin_body = await _login(ac, ADMIN_ID, "Owner")
        headers = {"Authorization": f"Bearer {admin_body['session_token']}"}
        before = (await ac.get(f"/admin/games/{game_id}", headers=headers)).json()
        target = next(p for p in before["players"] if not p["is_host"])
        r = await ac.post(f"/admin/games/{game_id}/remove/{target['player_id']}", headers=headers)
        assert r.status_code == 200
        after = (await ac.get(f"/admin/games/{game_id}", headers=headers)).json()
        assert len(after["players"]) == 5


@pytest.mark.asyncio
async def test_admin_can_terminate_a_game():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        game_id = await _make_lobby_game(ac, "-100115")
        admin_body = await _login(ac, ADMIN_ID, "Owner")
        headers = {"Authorization": f"Bearer {admin_body['session_token']}"}
        r = await ac.post(f"/admin/games/{game_id}/terminate", headers=headers)
        assert r.status_code == 200
        r2 = await ac.get(f"/admin/games/{game_id}", headers=headers)
        assert r2.status_code == 404


@pytest.mark.asyncio
async def test_admin_stats_reports_active_games():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await _make_lobby_game(ac, "-100116")
        admin_body = await _login(ac, ADMIN_ID, "Owner")
        headers = {"Authorization": f"Bearer {admin_body['session_token']}"}
        r = await ac.get("/admin/stats", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["active_games"] >= 1
        assert "total_users" in body and "total_finished_games" in body


@pytest.mark.asyncio
async def test_admin_route_404s_for_unknown_game():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        admin_body = await _login(ac, ADMIN_ID, "Owner")
        headers = {"Authorization": f"Bearer {admin_body['session_token']}"}
        r = await ac.get("/admin/games/does-not-exist", headers=headers)
        assert r.status_code == 404
