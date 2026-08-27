from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Optional
from app.game_engine.roles import RoleName, Faction, ActionType


class Phase(str, Enum):
    LOBBY = "lobby"
    ROLE_ASSIGNMENT = "role_assignment"
    NIGHT = "night"
    DAY_DISCUSSION = "day_discussion"
    VOTING = "voting"
    VOTE_RESULTS = "vote_results"
    GAME_OVER = "game_over"


@dataclass
class GameSettings:
    mode: str = "classic"                 # classic | advanced | custom
    day_duration_s: int = 90
    night_duration_s: int = 45
    voting_duration_s: int = 60
    lobby_duration_s: int = 300
    anonymous_voting: bool = False
    reveal_role_on_death: bool = True
    allow_self_vote: bool = False
    tie_rule: str = "no_elimination"      # no_elimination | revote | random
    allow_neutral_roles: bool = True
    allow_special_roles: bool = True


@dataclass
class PlayerState:
    player_id: str                        # internal uuid
    telegram_user_id: int
    display_name: str
    avatar_url: Optional[str] = None
    role: Optional[RoleName] = None
    alive: bool = True
    is_host: bool = False
    connected: bool = True
    death_reason: Optional[str] = None
    death_night: Optional[int] = None
    # per-night transient effects (cleared every night)
    framed: bool = False
    silenced: bool = False
    doused: bool = False
    protected_by_doctor: bool = False
    protected_by_bodyguard: Optional[str] = None   # bodyguard's player_id
    # per-game counters
    last_self_heal_night: Optional[int] = None
    veteran_alerts_used: int = 0
    gunner_bullets_used: int = 0
    mayor_revealed: bool = False
    vote_weight: int = 1
    jester_won: bool = False
    # personal stats — spec section 22 "personal statistics" (shown to a
    # player about themself at game end, alongside the shared final role
    # reveal). Deliberately simple counters, bumped at the exact points
    # actions are validated/resolved; see engine.py.
    kills: int = 0
    investigations: int = 0
    protections: int = 0
    votes_cast: int = 0


@dataclass
class ChatMessage:
    """One in-app discussion message (spec sections 11/32) — the Telegram
    group never sees this; it exists only inside a single game's state."""
    message_id: str
    player_id: str
    display_name: str
    text: str
    day_number: int
    ts: float = field(default_factory=time)


@dataclass
class NightAction:
    player_id: str
    role: RoleName
    action_type: ActionType
    target_id: Optional[str] = None
    submitted_at: float = field(default_factory=time)


@dataclass
class Vote:
    voter_id: str
    target_id: Optional[str]              # None = abstain
    weight: int = 1


@dataclass
class GameEvent:
    ts: float
    event_type: str
    payload: dict = field(default_factory=dict)


@dataclass
class WinResult:
    faction: Optional[Faction]
    winners: list[str]
    reason: str


@dataclass
class GameState:
    game_id: str
    chat_id: Optional[str]
    host_id: str
    settings: GameSettings = field(default_factory=GameSettings)
    players: dict[str, PlayerState] = field(default_factory=dict)
    phase: Phase = Phase.LOBBY
    night_number: int = 0
    day_number: int = 0
    phase_start: float = field(default_factory=time)
    phase_end: float = field(default_factory=time)
    night_actions: dict[str, NightAction] = field(default_factory=dict)   # player_id -> action
    votes: dict[str, Vote] = field(default_factory=dict)                  # voter_id -> vote
    events: list[GameEvent] = field(default_factory=list)
    doused_players: set[str] = field(default_factory=set)
    winner: Optional[WinResult] = None
    last_night_deaths: list[dict] = field(default_factory=list)
    last_vote_result: Optional[dict] = None
    chat_messages: list[ChatMessage] = field(default_factory=list)

    def alive_players(self) -> list[PlayerState]:
        return [p for p in self.players.values() if p.alive]

    def get(self, player_id: str) -> PlayerState:
        return self.players[player_id]

    def log(self, event_type: str, **payload) -> None:
        self.events.append(GameEvent(ts=time(), event_type=event_type, payload=payload))
