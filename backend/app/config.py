import json

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str = "CHANGE_ME"
    database_url: str = "sqlite+aiosqlite:///./mafia.db"
    session_secret: str = "CHANGE_ME_TO_A_LONG_RANDOM_SECRET"
    session_ttl_seconds: int = 60 * 60 * 12
    cors_origins: list[str] = ["*"]
    environment: str = "development"
    # Telegram user IDs allowed into the global, bot-owner-level admin
    # panel (app/api/routes_admin.py) — separate from any single match's
    # host_id, and not tied to being a player in any particular game. Set
    # via .env (or Render's dashboard) as ADMIN_TELEGRAM_IDS: a JSON array
    # ([123456789]), a comma-separated list (123456789,987654321), or a
    # single bare ID (123456789) — admin_telegram_ids below normalizes all
    # three. Kept as a plain string field here (instead of list[int]
    # directly) because pydantic-settings auto-JSON-decodes env values for
    # list-typed fields *before* any validator runs, and that auto-decode
    # crashes the whole app at startup on anything but a strict JSON array
    # (e.g. a bare pasted number, or a comma-separated list) — it never
    # even reaches our own parsing.
    admin_telegram_ids_raw: str = Field(default="", validation_alias="ADMIN_TELEGRAM_IDS")

    @property
    def admin_telegram_ids(self) -> list[int]:
        stripped = self.admin_telegram_ids_raw.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            return [int(x) for x in json.loads(stripped)]
        return [int(part.strip()) for part in stripped.split(",") if part.strip()]

    @admin_telegram_ids.setter
    def admin_telegram_ids(self, value: list[int]) -> None:
        # Keeps direct assignment (settings.admin_telegram_ids = [...],
        # used by tests to monkeypatch the shared settings singleton)
        # working the same way it did when this was a plain list field.
        self.admin_telegram_ids_raw = ",".join(str(v) for v in value)

    # Telegram webhook mode (app/telegram_bot.py): the bot's own logic
    # (posting the join button) runs INSIDE this backend as a webhook
    # route instead of a separate long-polling process — Render's free
    # tier doesn't offer a free instance for background workers, only for
    # web services, so this is what lets the whole stack (backend + bot)
    # run as one free web service. Leave disabled for other deployment
    # targets (a VPS, Fly.io) that keep using bot/bot.py's polling mode
    # instead — a bot token can only be in webhook OR polling mode at once.
    telegram_webhook_enabled: bool = False
    # Render's `generateValue: true` (see render.yaml) produces a standard
    # base64 string — e.g. "B0jrphAPOY7pg92AN0c9MN4yecczLMdwnx4OkA1KFUk=" —
    # which can contain '+', '/', and '=' padding. Telegram's webhook
    # secret_token only allows [A-Za-z0-9_-], and rejects set_webhook()
    # outright (crashing startup) if it sees anything else. Kept as a raw
    # field here and exposed through the sanitizing property below instead
    # of validating the field directly, so whatever Render (or a human)
    # puts in TELEGRAM_WEBHOOK_SECRET always works.
    telegram_webhook_secret_raw: str = Field(default="CHANGE_ME", validation_alias="TELEGRAM_WEBHOOK_SECRET")

    @property
    def telegram_webhook_secret(self) -> str:
        # Standard-base64 -> base64url: same randomness, legal charset.
        return self.telegram_webhook_secret_raw.replace("+", "-").replace("/", "_").replace("=", "")

    @telegram_webhook_secret.setter
    def telegram_webhook_secret(self, value: str) -> None:
        # Keeps direct assignment (settings.telegram_webhook_secret = ...,
        # used by tests) working the same way it did as a plain field.
        self.telegram_webhook_secret_raw = value

    # Public URL this backend is reachable at, used both to register the
    # webhook with Telegram and to build the Mini App's join-button URL.
    # Leave blank on Render — RENDER_EXTERNAL_URL is injected automatically
    # and used as a fallback (see app/telegram_bot.py).
    webapp_url: str = ""


settings = Settings()
