from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, ForeignKey, DateTime, JSON, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class User(Base):
    """A Telegram user. Created/updated on every verified initData login."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    games_played: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    town_wins: Mapped[int] = mapped_column(Integer, default=0)
    mafia_wins: Mapped[int] = mapped_column(Integer, default=0)
    neutral_wins: Mapped[int] = mapped_column(Integer, default=0)


class Role(Base):
    """Read-only catalog of role metadata, kept in sync with app/game_engine/roles.py
    for querying/statistics purposes (e.g. 'favorite role')."""
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    faction: Mapped[str] = mapped_column(String(16))
    description: Mapped[str] = mapped_column(String(512))


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    host_telegram_id: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(16), default="classic")
    phase: Mapped[str] = mapped_column(String(32), default="lobby")
    player_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    winner_faction: Mapped[str | None] = mapped_column(String(16), nullable=True)

    players: Mapped[list["GamePlayer"]] = relationship(back_populates="game")
    settings: Mapped["GameSettings"] = relationship(back_populates="game", uselist=False)


class GamePlayer(Base):
    __tablename__ = "game_players"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    role_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_host: Mapped[bool] = mapped_column(Boolean, default=False)
    alive: Mapped[bool] = mapped_column(Boolean, default=True)
    death_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    death_night: Mapped[int | None] = mapped_column(Integer, nullable=True)
    survived_to_end: Mapped[bool] = mapped_column(Boolean, default=False)

    game: Mapped["Game"] = relationship(back_populates="players")


class GameAction(Base):
    """Append-only log of every night action, for debugging and anti-cheat audits."""
    __tablename__ = "game_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"))
    night_number: Mapped[int] = mapped_column(Integer)
    player_id: Mapped[str] = mapped_column(String(64))
    role_name: Mapped[str] = mapped_column(String(32))
    action_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Vote(Base):
    __tablename__ = "votes"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"))
    day_number: Mapped[int] = mapped_column(Integer)
    voter_id: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class GameEvent(Base):
    """Full event log per game — powers reconnection debugging and game history replay."""
    __tablename__ = "game_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"))
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class GameSettings(Base):
    __tablename__ = "game_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), unique=True)
    day_duration_s: Mapped[int] = mapped_column(Integer, default=90)
    night_duration_s: Mapped[int] = mapped_column(Integer, default=45)
    voting_duration_s: Mapped[int] = mapped_column(Integer, default=60)
    anonymous_voting: Mapped[bool] = mapped_column(Boolean, default=False)
    reveal_role_on_death: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_self_vote: Mapped[bool] = mapped_column(Boolean, default=False)
    tie_rule: Mapped[str] = mapped_column(String(16), default="no_elimination")
    allow_neutral_roles: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_special_roles: Mapped[bool] = mapped_column(Boolean, default=True)

    game: Mapped["Game"] = relationship(back_populates="settings")


class GameHistory(Base):
    """Denormalized per-player summary of a finished game — fast reads for
    'game history' and 'my stats' screens without joining live tables."""
    __tablename__ = "game_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    played_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    player_count: Mapped[int] = mapped_column(Integer)
    role_name: Mapped[str] = mapped_column(String(32))
    faction: Mapped[str] = mapped_column(String(16))
    won: Mapped[bool] = mapped_column(Boolean)
    survived_nights: Mapped[int] = mapped_column(Integer, default=0)
    kills: Mapped[int] = mapped_column(Integer, default=0)
    successful_investigations: Mapped[int] = mapped_column(Integer, default=0)
    successful_protections: Mapped[int] = mapped_column(Integer, default=0)


class KnownGroup(Base):
    """A Telegram group the bot is currently a member of, tracked via
    my_chat_member updates (see app/telegram_bot.py). The Bot API has no
    "list every group I'm in" call, so the bot has to remember them itself
    as they happen — this is what powers the private-chat "which group?"
    picker for starting a match without typing /start in the group."""
    __tablename__ = "known_groups"

    chat_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class BotSetting(Base):
    """Small key/value store for admin-configurable bot settings that
    aren't fixed at deploy time — currently just the mandatory-subscription
    channel, set live from the bot's own /admin panel (app/telegram_bot.py)
    rather than an env var, since the bot owner changes it without a
    redeploy."""
    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(512))


class SupportMessage(Base):
    """One row per (admin, forwarded copy) pairing for the "Admin bilan
    bog'lanish" relay in app/telegram_bot.py. A user's message is copied to
    every admin; whichever admin replies (a Telegram reply-to on their own
    copy) needs to be routed back to that original user, even across a
    restart — this table is what makes that lookup possible, keyed by
    which admin got which copy of which message."""
    __tablename__ = "support_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_telegram_id: Mapped[int] = mapped_column(Integer, index=True)
    user_display_name: Mapped[str] = mapped_column(String(256))
    admin_telegram_id: Mapped[int] = mapped_column(Integer, index=True)
    admin_copy_message_id: Mapped[int] = mapped_column(Integer)
    original_text: Mapped[str] = mapped_column(String(4096))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    replied: Mapped[bool] = mapped_column(Boolean, default=False)


class UserLanguage(Base):
    """A user's preferred interface language — a new table rather than a
    column on the existing users table, since adding a column there
    wouldn't retroactively appear in an already-deployed database (this
    project has no migration tool; see app/database.py's create_all()).
    Set from the bot's own menu (app/telegram_bot.py) and read by both the
    bot's own messages and the webapp (POST /auth/telegram includes it) —
    one shared preference either surface can update, so changing it in the
    bot is reflected in the webapp too."""
    __tablename__ = "user_languages"

    telegram_user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    language: Mapped[str] = mapped_column(String(8), default="uz")
