"""app/telegram_bot.py — the webhook endpoint that lets the bot run inside
this backend instead of a separate worker (see that module's docstring for
why). These tests cover what's safely testable without making a real
Telegram API call: the guard paths, URL resolution, and — most
importantly — that importing this module (and app.main, which pulls it
in) never constructs a real Bot, since that would crash on the
placeholder tokens this whole test suite uses."""
import pytest
from httpx import AsyncClient, ASGITransport

from app.config import settings
settings.telegram_bot_token = "TEST-TOKEN"
settings.database_url = "sqlite+aiosqlite:///:memory:"

from app.main import app  # noqa: E402
from app.database import init_db  # noqa: E402
import app.telegram_bot as telegram_bot  # noqa: E402


@pytest.fixture(autouse=True)
async def _ensure_tables():
    await init_db()


def test_importing_the_module_never_constructs_a_real_bot():
    """The regression this guards against: aiogram's Bot() validates its
    token's format at construction time and raises immediately for
    anything that doesn't look like a real token — which "TEST-TOKEN"
    (used throughout this suite) does not. If Bot() were built at import
    time, every test in this project would already have failed to even
    import app.main, not just this one."""
    assert telegram_bot._bot is None


def test_webapp_base_url_prefers_explicit_setting(monkeypatch):
    monkeypatch.setattr(settings, "webapp_url", "https://example.com/")
    assert telegram_bot.webapp_base_url() == "https://example.com"


def test_webapp_base_url_falls_back_to_render_external_url(monkeypatch):
    monkeypatch.setattr(settings, "webapp_url", "")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://mafia-abcd.onrender.com")
    assert telegram_bot.webapp_base_url() == "https://mafia-abcd.onrender.com"


def test_webapp_base_url_empty_when_nothing_is_set(monkeypatch):
    monkeypatch.setattr(settings, "webapp_url", "")
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    assert telegram_bot.webapp_base_url() == ""


@pytest.mark.asyncio
async def test_webhook_route_404s_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_enabled", False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/bot/webhook", json={})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_webhook_route_rejects_wrong_secret(monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_enabled", True)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "correct-secret")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/bot/webhook", json={},
                           headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"})
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_webhook_route_rejects_missing_secret(monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_enabled", True)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "correct-secret")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/bot/webhook", json={})
        assert r.status_code == 401
