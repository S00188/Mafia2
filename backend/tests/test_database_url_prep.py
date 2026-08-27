"""_prepare_asyncpg_url is what lets a Neon connection string — pasted in
exactly as their dashboard gives it, sslmode/channel_binding included —
work with asyncpg instead of crashing on the first connection (asyncpg
has no idea what sslmode= or channel_binding= mean; SQLAlchemy forwards
them straight into asyncpg.connect() as kwargs otherwise)."""
from app.database import _prepare_asyncpg_url


def test_sqlite_url_passes_through_unchanged():
    url, connect_args = _prepare_asyncpg_url("sqlite+aiosqlite:///./mafia.db")
    assert url == "sqlite+aiosqlite:///./mafia.db"
    assert connect_args == {}


def test_neon_style_url_strips_sslmode_and_channel_binding():
    raw = ("postgresql+asyncpg://alex:pw@ep-cool-darkness-123456.us-east-2.aws.neon.tech"
           "/neondb?sslmode=require&channel_binding=require")
    url, connect_args = _prepare_asyncpg_url(raw)
    assert "sslmode" not in url
    assert "channel_binding" not in url
    assert url.startswith("postgresql+asyncpg://alex:pw@ep-cool-darkness-123456.us-east-2.aws.neon.tech/neondb")
    assert connect_args["ssl"] == "require"
    assert connect_args["statement_cache_size"] == 0


def test_plain_asyncpg_url_still_gets_statement_cache_disabled():
    """Even with no sslmode at all, statement_cache_size=0 is set — it's
    what keeps asyncpg working behind a transaction-mode pooler (Neon's
    pooled endpoint, PgBouncer, Supabase, ...) regardless of whether SSL
    params were present."""
    url, connect_args = _prepare_asyncpg_url("postgresql+asyncpg://user:pw@localhost/mydb")
    assert url == "postgresql+asyncpg://user:pw@localhost/mydb"
    assert connect_args == {"statement_cache_size": 0}
    assert "ssl" not in connect_args


def test_sslmode_disable_does_not_force_ssl():
    url, connect_args = _prepare_asyncpg_url("postgresql+asyncpg://user:pw@localhost/mydb?sslmode=disable")
    assert "ssl" not in connect_args


def test_other_query_params_are_preserved():
    url, _ = _prepare_asyncpg_url(
        "postgresql+asyncpg://user:pw@host/mydb?sslmode=require&application_name=mafia"
    )
    assert "application_name=mafia" in url
    assert "sslmode" not in url
