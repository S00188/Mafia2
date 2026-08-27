"""
Holds all currently-running games in memory (fast, simple, correct as long
as the server process doesn't restart mid-game — see README for the
persistence roadmap) and persists a summary to the database when a game
finishes, for history/statistics screens.

This is the seam the WebSocket layer and REST routes both call through —
neither ever touches a GameEngine's internal GameState directly.
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.game_engine.engine import GameEngine
from app.game_engine.roles import ROLES
from app.game_engine.state import Phase
from app.models.models import User, Game, GamePlayer, GameHistory
from app.utils.helpers import new_game_code


class GameRegistry:
    def __init__(self) -> None:
        self._games: dict[str, GameEngine] = {}

    def create(self, host_telegram_id: int, host_name: str, chat_id: Optional[str] = None) -> GameEngine:
        game_id = new_game_code()
        while game_id in self._games:
            game_id = new_game_code()
        engine = GameEngine(game_id=game_id, host_telegram_id=host_telegram_id,
                             host_name=host_name, chat_id=chat_id)
        self._games[game_id] = engine
        return engine

    def get(self, game_id: str) -> GameEngine:
        engine = self._games.get(game_id)
        if not engine:
            raise KeyError("Game no longer exists")
        return engine

    def get_by_chat(self, chat_id: str) -> Optional[GameEngine]:
        """The one active (not finished) match bound to this Telegram group,
        if any. A group gets a fresh match once the previous one reaches
        GAME_OVER — this never returns a finished game."""
        for engine in self._games.values():
            if engine.state.chat_id == chat_id and engine.state.phase != Phase.GAME_OVER:
                return engine
        return None

    def get_or_create_for_chat(self, chat_id: str, host_telegram_id: int,
                                host_name: str) -> tuple[GameEngine, bool]:
        """Idempotent entry point for the 'tap the bot's button in the group'
        flow: no user ever calls create_game directly. Returns (engine, created)."""
        existing = self.get_by_chat(chat_id)
        if existing:
            return existing, False
        return self.create(host_telegram_id, host_name, chat_id), True

    def remove(self, game_id: str) -> None:
        self._games.pop(game_id, None)

    def all_engines(self) -> list[GameEngine]:
        return list(self._games.values())


registry = GameRegistry()


async def get_or_create_user(session: AsyncSession, telegram_user_id: int, first_name: str,
                              last_name: Optional[str], username: Optional[str],
                              photo_url: Optional[str]) -> User:
    result = await session.execute(select(User).where(User.telegram_user_id == telegram_user_id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(telegram_user_id=telegram_user_id, first_name=first_name,
                     last_name=last_name, username=username, photo_url=photo_url)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


async def persist_finished_game(session: AsyncSession, engine: GameEngine) -> None:
    """Called once, right after WinConditionManager produces a result."""
    state = engine.state
    game_row = Game(
        game_id=state.game_id, chat_id=state.chat_id,
        host_telegram_id=state.players[state.host_id].telegram_user_id,
        mode=state.settings.mode, phase=state.phase.value,
        player_count=len(state.players),
        winner_faction=state.winner.faction.value if state.winner and state.winner.faction else "draw",
    )
    session.add(game_row)
    await session.flush()

    for pid, p in state.players.items():
        result = await session.execute(select(User).where(User.telegram_user_id == p.telegram_user_id))
        user = result.scalar_one_or_none()
        if not user:
            continue
        won = bool(state.winner and pid in state.winner.winners)
        session.add(GamePlayer(
            game_id=game_row.id, user_id=user.id, role_name=p.role.value if p.role else None,
            is_host=p.is_host, alive=p.alive, death_reason=p.death_reason,
            death_night=p.death_night, survived_to_end=p.alive,
        ))
        session.add(GameHistory(
            game_id=state.game_id, user_id=user.id, player_count=len(state.players),
            role_name=p.role.value if p.role else "?",
            faction=ROLES[p.role].faction.value if p.role else "?",
            won=won,
        ))
        user.games_played += 1
        if won:
            user.wins += 1
            if state.winner.faction:
                setattr(user, f"{state.winner.faction.value}_wins",
                        getattr(user, f"{state.winner.faction.value}_wins") + 1)
        else:
            user.losses += 1
    await session.commit()
