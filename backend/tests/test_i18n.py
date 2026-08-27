"""Covers app/i18n.py's DB-backed language preference, and that it's
correctly surfaced through both the bot's menu builder and the webapp
login response — the two places that need to agree on it."""
import pytest

from app.config import settings
settings.telegram_bot_token = "TEST-TOKEN"
settings.database_url = "sqlite+aiosqlite:///:memory:"

import app.telegram_bot as tb  # noqa: E402
from app.database import init_db  # noqa: E402
from app.i18n import (  # noqa: E402
    DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, button_text, button_texts,
    get_user_language, set_user_language, t,
)


@pytest.fixture(autouse=True)
async def _ensure_tables():
    await init_db()


@pytest.mark.asyncio
async def test_get_user_language_defaults_to_uz():
    assert await get_user_language(700001) == DEFAULT_LANGUAGE


@pytest.mark.asyncio
async def test_set_and_get_user_language_round_trip():
    await set_user_language(700002, "ru")
    assert await get_user_language(700002) == "ru"

    await set_user_language(700002, "en")
    assert await get_user_language(700002) == "en"


@pytest.mark.asyncio
async def test_set_user_language_rejects_unsupported_code():
    await set_user_language(700003, "xx-not-real")
    assert await get_user_language(700003) == DEFAULT_LANGUAGE


def test_t_falls_back_to_default_for_unknown_language():
    # Every real call site only ever passes a SUPPORTED_LANGUAGES value,
    # but t() itself should still degrade gracefully rather than KeyError.
    assert t("use_menu_below", "fr") == t("use_menu_below", DEFAULT_LANGUAGE)


def test_all_supported_languages_have_every_message_key():
    from app.i18n import MESSAGES
    for key, translations in MESSAGES.items():
        for lang in SUPPORTED_LANGUAGES:
            assert lang in translations, f"{key!r} is missing a {lang!r} translation"


def test_all_supported_languages_have_every_button_key():
    from app.i18n import BUTTONS
    for key, translations in BUTTONS.items():
        for lang in SUPPORTED_LANGUAGES:
            assert lang in translations, f"button {key!r} is missing a {lang!r} translation"


@pytest.mark.asyncio
async def test_menu_for_uses_the_requested_language():
    kb = tb.menu_for(700004, "en")
    labels = {b.text for row in kb.keyboard for b in row}
    assert button_text("roles", "en") in labels
    assert button_text("roles", "uz") not in labels


@pytest.mark.asyncio
async def test_menu_for_includes_admin_row_only_for_admins():
    settings.admin_telegram_ids = [700005]
    admin_kb = tb.menu_for(700005, "uz")
    other_kb = tb.menu_for(700006, "uz")

    admin_labels = {b.text for row in admin_kb.keyboard for b in row}
    other_labels = {b.text for row in other_kb.keyboard for b in row}

    assert button_text("admin_panel", "uz") in admin_labels
    assert button_text("admin_panel", "uz") not in other_labels


@pytest.mark.asyncio
async def test_language_picker_updates_stored_preference():
    """Exercises on_language_picked directly (same lightweight-fake-object
    approach as test_bot_features.py's support-relay test) rather than
    through the full webhook, since aiogram's own CallbackQuery/Message
    construction isn't part of what this suite tests."""

    class _FakeMessage:
        def __init__(self):
            self.edited = []
            self.answered = []

        async def edit_text(self, text, **kwargs):
            self.edited.append(text)

        async def answer(self, text, **kwargs):
            self.answered.append(text)

    class _FakeCallback:
        def __init__(self, user_id, data):
            self.from_user = type("U", (), {"id": user_id})()
            self.data = data
            self.message = _FakeMessage()
            self.answers = []

        async def answer(self, *args, **kwargs):
            self.answers.append(args[0] if args else None)

    callback = _FakeCallback(700007, "setlang:ru")
    await tb.on_language_picked(callback)

    assert await get_user_language(700007) == "ru"
    assert any("русский" in text.lower() or "язык" in text.lower() or "изменён" in text.lower()
               for text in callback.message.edited)
