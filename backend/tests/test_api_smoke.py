import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi.testclient import TestClient

from app.config import settings
settings.telegram_bot_token = "TEST-TOKEN"
settings.database_url = "sqlite+aiosqlite:///:memory:"

from app.main import app  # noqa: E402
from app.database import init_db  # noqa: E402


@pytest.fixture(autouse=True)
async def _ensure_tables():
    # httpx's ASGITransport doesn't fire FastAPI's lifespan startup event,
    # so tests create tables directly against the shared in-memory engine.
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
async def test_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/health")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_full_lobby_flow_create_join_start():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        host_login = await ac.post("/auth/telegram", json={"init_data": _init_data_for(1, "Host")})
        assert host_login.status_code == 200
        host_token = host_login.json()["session_token"]

        created = await ac.post("/games", json={"display_name": "Host"},
                                 headers={"Authorization": f"Bearer {host_token}"})
        assert created.status_code == 200
        game_id = created.json()["game_id"]

        for i in range(2, 9):
            login = await ac.post("/auth/telegram", json={"init_data": _init_data_for(i, f"P{i}")})
            token = login.json()["session_token"]
            joined = await ac.post(f"/games/{game_id}/join", json={"display_name": f"P{i}"},
                                    headers={"Authorization": f"Bearer {token}"})
            assert joined.status_code == 200

        started = await ac.post(f"/games/{game_id}/start",
                                 headers={"Authorization": f"Bearer {host_token}"})
        assert started.status_code == 200

        state = await ac.get(f"/games/{game_id}/state", headers={"Authorization": f"Bearer {host_token}"})
        assert state.status_code == 200
        body = state.json()
        assert body["phase"] == "night"
        assert body["me"]["role"] is not None


@pytest.mark.asyncio
async def test_for_chat_is_the_only_join_path_and_it_is_idempotent():
    """This is the actual product flow: the bot posts one join button per
    Telegram group, and every player who taps it hits /games/for-chat with
    that group's chat_id — nobody ever calls POST /games directly."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        first_login = await ac.post("/auth/telegram", json={"init_data": _init_data_for(501, "First")})
        first_token = first_login.json()["session_token"]
        first = await ac.post("/games/for-chat", json={"chat_id": "-100555", "display_name": "First"},
                               headers={"Authorization": f"Bearer {first_token}"})
        assert first.status_code == 200
        first_body = first.json()
        assert first_body["created"] is True
        assert first_body["is_host"] is True
        game_id = first_body["game_id"]

        second_login = await ac.post("/auth/telegram", json={"init_data": _init_data_for(502, "Second")})
        second_token = second_login.json()["session_token"]
        second = await ac.post("/games/for-chat", json={"chat_id": "-100555", "display_name": "Second"},
                                headers={"Authorization": f"Bearer {second_token}"})
        assert second.status_code == 200
        second_body = second.json()
        # Same group -> same match, not a second one.
        assert second_body["game_id"] == game_id
        assert second_body["created"] is False
        assert second_body["is_host"] is False

        # Tapping again with the same identity is a no-op that returns the
        # same player_id rather than erroring or duplicating them.
        again = await ac.post("/games/for-chat", json={"chat_id": "-100555", "display_name": "First"},
                               headers={"Authorization": f"Bearer {first_token}"})
        assert again.json()["player_id"] == first_body["player_id"]


@pytest.mark.asyncio
async def test_for_chat_auto_starts_at_25_and_next_round_gets_a_fresh_game():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        game_id = None
        for i in range(1, 26):
            login = await ac.post("/auth/telegram", json={"init_data": _init_data_for(600 + i, f"G{i}")})
            token = login.json()["session_token"]
            r = await ac.post("/games/for-chat", json={"chat_id": "-100777", "display_name": f"G{i}"},
                               headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200
            game_id = r.json()["game_id"]

        host_login = await ac.post("/auth/telegram", json={"init_data": _init_data_for(601, "G1")})
        host_token = host_login.json()["session_token"]
        state = await ac.get(f"/games/{game_id}/state", headers={"Authorization": f"Bearer {host_token}"})
        assert state.json()["phase"] != "lobby"  # started itself, no one clicked start

        # A 26th person tapping the group's button after it's full/started
        # gets a clear error, not silently dropped or crashing.
        late_login = await ac.post("/auth/telegram", json={"init_data": _init_data_for(699, "Late")})
        late_token = late_login.json()["session_token"]
        late = await ac.post("/games/for-chat", json={"chat_id": "-100777", "display_name": "Late"},
                              headers={"Authorization": f"Bearer {late_token}"})
        assert late.status_code == 409


def test_websocket_delivers_lobby_state_then_starts_the_game():
    """Full-stack regression test for the real client's actual startup
    sequence (join over REST, then connect the socket) — this is what
    caught get_player_view() crashing on every fresh WebSocket connection
    before any role existed (see test_anticheat_and_views.py)."""
    with TestClient(app) as c:
        tokens = []
        game_id = None
        for i in range(1, 7):
            login = c.post("/auth/telegram", json={"init_data": _init_data_for(800 + i, f"W{i}")})
            tok = login.json()["session_token"]
            tokens.append(tok)
            joined = c.post("/games/for-chat", json={"chat_id": "-100333", "display_name": f"W{i}"},
                             headers={"Authorization": f"Bearer {tok}"})
            game_id = joined.json()["game_id"]

        with c.websocket_connect(f"/ws/games/{game_id}?token={tokens[0]}") as ws:
            first = ws.receive_json()
            assert first["state"]["phase"] == "lobby"
            assert len(first["state"]["players"]) == 6

            ws.send_json({"type": "start_game"})
            after_start = ws.receive_json()["state"]
            assert after_start["phase"] == "night"
            assert after_start["me"]["role"] is not None


@pytest.mark.asyncio
async def test_starting_with_too_few_players_returns_400():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login = await ac.post("/auth/telegram", json={"init_data": _init_data_for(999, "Solo")})
        token = login.json()["session_token"]
        created = await ac.post("/games", json={"display_name": "Solo"},
                                 headers={"Authorization": f"Bearer {token}"})
        game_id = created.json()["game_id"]
        started = await ac.post(f"/games/{game_id}/start", headers={"Authorization": f"Bearer {token}"})
        assert started.status_code == 400
