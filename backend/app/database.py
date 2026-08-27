from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool
from app.config import settings


class Base(DeclarativeBase):
    pass


def _prepare_asyncpg_url(url: str) -> tuple[str, dict]:
    """Neon (and most managed Postgres dashboards) hand you a connection
    string with libpq-style query params — ?sslmode=require&channel_binding=require
    — copy-pasted straight from their UI. asyncpg doesn't understand either
    one: SQLAlchemy forwards unrecognized query params as **kwargs straight
    into asyncpg.connect(), which raises TypeError on "sslmode" and
    "channel_binding" since neither is a real asyncpg parameter (asyncpg
    uses ssl=, not sslmode=). Strip them out of the URL and translate into
    the connect_args asyncpg actually accepts, so a connection string
    pasted in verbatim just works instead of crashing on first connect.

    statement_cache_size=0 is set unconditionally for asyncpg+Postgres:
    it's what lets asyncpg work behind a transaction-mode pooler (Neon's
    pooled endpoint, PgBouncer, Supabase, RDS Proxy, ...) without
    "prepared statement already exists" errors — a small, safe tradeoff
    even against a direct (non-pooled) connection.
    """
    if "+asyncpg" not in url or "://" not in url:
        return url, {}
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)
    cleaned = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    connect_args = {"statement_cache_size": 0}
    if sslmode and sslmode != "disable":
        connect_args["ssl"] = sslmode
    return cleaned, connect_args


_database_url, _connect_args = _prepare_asyncpg_url(settings.database_url)
_engine_kwargs = {"echo": False, "connect_args": _connect_args}
if ":memory:" in settings.database_url:
    # An in-memory SQLite DB only survives on a single shared connection —
    # used for tests; production always points at a real file or Postgres.
    _engine_kwargs["poolclass"] = StaticPool
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_async_engine(_database_url, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
