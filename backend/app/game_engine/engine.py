"""
GameEngine: the single authoritative entry point for one running game.
Nothing outside this class is allowed to mutate GameState directly —
the WebSocket layer and API routes only ever call methods here, which is
what makes "never trust the frontend" actually enforceable.
"""
from __future__ import annotations
import uuid
import random
from typing import Optional

from app.game_engine.roles import RoleName, Faction, ActionType, ROLES
from app.game_engine.state import GameState, PlayerState, GameSettings, Phase, NightAction, ChatMessage
from app.game_engine.managers import (
    RoleManager, PhaseManager, NightResolver, VoteManager, DeathManager,
    WinConditionManager, TimerManager, EventManager,
)

CHAT_MAX_LEN = 500
CHAT_HISTORY_LIMIT = 200

# What the admin panel is allowed to change via update_settings(), and the
# bounds each kind of value must fall within. Anything not listed here is
# rejected — this is the only door into GameSettings from a client, so it
# has to be a strict whitelist, not just "set whatever attribute".
ADMIN_SETTINGS_BOUNDS: dict[str, tuple[int, int]] = {
    "night_duration_s": (10, 300),
    "day_duration_s": (30, 600),
    "voting_duration_s": (15, 300),
}
ADMIN_SETTINGS_CHOICES: dict[str, set[str]] = {
    "tie_rule": {"no_elimination", "revote", "random"},
}
ADMIN_SETTINGS_BOOLS: set[str] = {"anonymous_voting", "allow_self_vote", "reveal_role_on_death"}


class EngineError(ValueError):
    """Raised for any client-caused invalid action. Safe to show to the user."""


class GameEngine:
    def __init__(self, game_id: str, host_telegram_id: int, host_name: str,
                 chat_id: Optional[str] = None, settings: Optional[GameSettings] = None,
                 rng: Optional[random.Random] = None):
        host_pid = str(uuid.uuid4())
        self.state = GameState(
            game_id=game_id, chat_id=chat_id, host_id=host_pid,
            settings=settings or GameSettings(),
        )
        self.state.players[host_pid] = PlayerState(
            player_id=host_pid, telegram_user_id=host_telegram_id,
            display_name=host_name, is_host=True,
        )
        self._rng = rng or random.Random()
        self._night_results: dict[str, dict] = {}

    # ---------- lobby ----------

    def add_player(self, telegram_user_id: int, display_name: str,
                    avatar_url: Optional[str] = None) -> str:
        if self.state.phase != Phase.LOBBY:
            raise EngineError("Game already started")
        if any(p.telegram_user_id == telegram_user_id for p in self.state.players.values()):
            raise EngineError("You already joined this game")
        if len(self.state.players) >= 25:
            raise EngineError("Lobby is full (25 max)")
        pid = str(uuid.uuid4())
        self.state.players[pid] = PlayerState(
            player_id=pid, telegram_user_id=telegram_user_id,
            display_name=display_name, avatar_url=avatar_url,
        )
        EventManager.log(self.state, "player_joined", player_id=pid)
        if len(self.state.players) >= 25:
            # Lobby is at max capacity: start immediately, same as a manual
            # host start — no one has to notice and click anything.
            self._begin(auto=True)
        return pid

    def kick_player(self, host_id: Optional[str], target_id: str) -> None:
        self._require_host_or_system(host_id)
        if self.state.phase != Phase.LOBBY:
            raise EngineError("Cannot kick after the game has started")
        if host_id is not None and target_id == host_id:
            raise EngineError("Host cannot kick themselves")
        self.state.players.pop(target_id, None)

    def start_game(self, host_id: str) -> None:
        self._require_host(host_id)
        if self.state.phase != Phase.LOBBY:
            raise EngineError("Game already started")
        n = len(self.state.players)
        if not (6 <= n <= 25):
            raise EngineError(f"Need 6–25 players to start (have {n})")
        self._begin(auto=False)

    def _begin(self, auto: bool) -> None:
        """Shared by the host's manual 'start game' and the automatic
        start once the lobby hits 25 players — identical role assignment
        and phase transition either way."""
        RoleManager.assign_roles(self.state, self._rng)
        self.state.phase = Phase.ROLE_ASSIGNMENT
        EventManager.log(self.state, "game_started",
                          player_count=len(self.state.players), auto=auto)
        PhaseManager.to_night(self.state)

    # ---------- night ----------

    def submit_night_action(self, player_id: str, target_id: Optional[str]) -> None:
        if self.state.phase != Phase.NIGHT:
            raise EngineError("It is not night")
        player = self._require_alive(player_id)
        if player_id in self.state.night_actions:
            raise EngineError("Action already submitted")
        role_def = ROLES[player.role]
        action_type = role_def.night_action
        if action_type is None:
            raise EngineError("Your role has no night action")
        if role_def.max_charges is not None:
            used = {
                RoleName.VETERAN: player.veteran_alerts_used,
                RoleName.DOCTOR: 0,  # doctor charge cap only applies to self-heal, checked in resolver
            }.get(player.role, 0)
            if used >= role_def.max_charges:
                raise EngineError("No charges remaining")
        no_target_actions = (ActionType.IGNITE, ActionType.ALERT)
        if target_id is not None:
            if target_id not in self.state.players:
                raise EngineError("Invalid target")
            if not self.state.players[target_id].alive:
                raise EngineError("Target is not alive")
            if target_id == player_id and not role_def.can_target_self:
                raise EngineError("This role cannot target itself")
        elif action_type not in no_target_actions:
            raise EngineError("This action requires a target")
        self.state.night_actions[player_id] = NightAction(
            player_id=player_id, role=player.role, action_type=action_type, target_id=target_id,
        )
        if action_type == ActionType.INVESTIGATE:
            player.investigations += 1
        elif action_type in (ActionType.PROTECT, ActionType.GUARD):
            player.protections += 1
        EventManager.log(self.state, "night_action_submitted", player_id=player_id)

    def resolve_night_if_ready(self, force: bool = False) -> bool:
        """Returns True if the night was resolved (either everyone with an
        action submitted, or the server timer expired and force=True)."""
        if self.state.phase != Phase.NIGHT:
            return False
        if not force and not TimerManager.is_expired(self.state):
            eligible = [p for p in self.state.alive_players() if ROLES[p.role].night_action]
            if len(self.state.night_actions) < len(eligible):
                return False
        deaths, results = NightResolver.resolve(self.state)
        self._night_results = results
        self._credit_night_kills(deaths)
        win = WinConditionManager.check(self.state)
        if win:
            PhaseManager.to_game_over(self.state, win)
        else:
            PhaseManager.to_day(self.state)
        return True

    def _credit_night_kills(self, deaths: list[dict]) -> None:
        """Personal-stats bookkeeping only (spec section 22) — never
        changes who dies or why; that's already decided by the time this
        runs. Reads night_actions, which PhaseManager.to_night() doesn't
        clear until the *next* night, so this is still the actions that
        actually produced `deaths`."""
        actions = list(self.state.night_actions.values())
        for d in deaths:
            pid, reason = d["player_id"], d["reason"]
            if reason == "mafia":
                for a in actions:
                    if a.action_type == ActionType.KILL and a.role in (RoleName.DON, RoleName.MAFIOSO) \
                            and a.target_id == pid:
                        self.state.players[a.player_id].kills += 1
            elif reason == "serial_killer":
                for a in actions:
                    if a.role == RoleName.SERIAL_KILLER and a.target_id == pid:
                        self.state.players[a.player_id].kills += 1
            elif reason == "arsonist":
                for a in actions:
                    if a.role == RoleName.ARSONIST and a.action_type == ActionType.IGNITE:
                        self.state.players[a.player_id].kills += 1

    # ---------- day / voting ----------

    def advance_to_voting(self) -> None:
        if self.state.phase != Phase.DAY_DISCUSSION:
            raise EngineError("Not in discussion phase")
        PhaseManager.to_voting(self.state)

    def submit_vote(self, voter_id: str, target_id: Optional[str]) -> None:
        VoteManager.submit_vote(self.state, voter_id, target_id)
        if target_id is not None:
            self.state.players[voter_id].votes_cast += 1
        EventManager.log(self.state, "vote_submitted", voter_id=voter_id)

    def resolve_voting_if_ready(self, force: bool = False) -> bool:
        if self.state.phase != Phase.VOTING:
            return False
        alive = self.state.alive_players()
        if not force and not TimerManager.is_expired(self.state) and len(self.state.votes) < len(alive):
            return False
        result = VoteManager.tally(self.state)
        if result["eliminated"]:
            DeathManager.eliminate(self.state, result["eliminated"], "day_vote")
        PhaseManager.to_vote_results(self.state)
        win = WinConditionManager.check(self.state)
        if win:
            PhaseManager.to_game_over(self.state, win)
        return True

    def start_next_night(self) -> None:
        if self.state.phase != Phase.VOTE_RESULTS:
            raise EngineError("Not ready for the next night")
        PhaseManager.to_night(self.state)

    def advance_to_voting_if_ready(self, force: bool = False) -> bool:
        """Server-timer counterpart to advance_to_voting(): returns True if
        discussion was ended and voting started. force=True ends it right
        away (a client asked to move on early); force=False only ends it
        once the server's own day timer has actually run out. This is what
        lets the day -> voting step happen on its own, the same way night
        and voting already resolve themselves, instead of sitting there
        forever if nobody in the WebApp taps anything."""
        if self.state.phase != Phase.DAY_DISCUSSION:
            return False
        if not force and not TimerManager.is_expired(self.state):
            return False
        PhaseManager.to_voting(self.state)
        return True

    def start_next_night_if_ready(self, force: bool = False) -> bool:
        """Server-timer counterpart to start_next_night(): returns True if
        the brief vote-results pause ended and the next night began.
        force=True ends it immediately (a client's "continue" tap);
        force=False only ends it once that phase's own server timer has
        expired, so the night/day cycle keeps repeating on its own."""
        if self.state.phase != Phase.VOTE_RESULTS:
            return False
        if not force and not TimerManager.is_expired(self.state):
            return False
        PhaseManager.to_night(self.state)
        return True

    # ---------- admin controls (per-match host, or the bot owner) ----------
    # Two different callers can reach these:
    #  - the per-match host (host_id == a real player_id in this game), via
    #    the WebSocket messages the WebApp sends while connected to a match;
    #  - the bot owner, who isn't necessarily a player in this match at all
    #    (see app/api/routes_admin.py) — those calls pass host_id=None,
    #    having already been authorized upstream against
    #    settings.admin_telegram_ids, not against this game's host_id.
    # _require_host_or_system is what tells the two apart.

    def update_settings(self, host_id: Optional[str], updates: dict) -> None:
        """Lets an admin tune the match before it starts instead of
        everyone being stuck with GameSettings' defaults — those fields
        already existed, nothing about the game itself changes here, this
        just makes them reachable."""
        self._require_host_or_system(host_id)
        if self.state.phase != Phase.LOBBY:
            raise EngineError("Settings can only be changed before the game starts")
        if not isinstance(updates, dict) or not updates:
            raise EngineError("No settings provided")
        for key, value in updates.items():
            if key in ADMIN_SETTINGS_BOUNDS:
                lo, hi = ADMIN_SETTINGS_BOUNDS[key]
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    raise EngineError(f"Invalid value for {key}")
                if not (lo <= value <= hi):
                    raise EngineError(f"{key} must be between {lo} and {hi} seconds")
                setattr(self.state.settings, key, value)
            elif key in ADMIN_SETTINGS_CHOICES:
                if value not in ADMIN_SETTINGS_CHOICES[key]:
                    raise EngineError(f"Invalid value for {key}")
                setattr(self.state.settings, key, value)
            elif key in ADMIN_SETTINGS_BOOLS:
                setattr(self.state.settings, key, bool(value))
            else:
                raise EngineError(f"Unknown setting: {key}")
        EventManager.log(self.state, "settings_updated", updates=updates)

    def force_advance_phase(self, host_id: Optional[str]) -> bool:
        """The admin's "move things along" button — same underlying
        transitions the server timer would eventually trigger on its own
        (see the *_if_ready methods), just triggered on demand instead of
        waiting, for when everyone's clearly done or something's stuck."""
        self._require_host_or_system(host_id)
        if self.state.phase == Phase.NIGHT:
            return self.resolve_night_if_ready(force=True)
        if self.state.phase == Phase.DAY_DISCUSSION:
            return self.advance_to_voting_if_ready(force=True)
        if self.state.phase == Phase.VOTING:
            return self.resolve_voting_if_ready(force=True)
        if self.state.phase == Phase.VOTE_RESULTS:
            return self.start_next_night_if_ready(force=True)
        raise EngineError("Nothing to advance right now")

    def extend_current_phase(self, host_id: Optional[str], seconds: int) -> None:
        """Gives an admin a way to add breathing room to whichever phase
        is running — e.g. discussion is going well and 90 seconds wasn't
        enough — without touching the settings players already agreed to
        for every other night/day/vote."""
        self._require_host_or_system(host_id)
        if self.state.phase not in (Phase.NIGHT, Phase.DAY_DISCUSSION, Phase.VOTING, Phase.VOTE_RESULTS):
            raise EngineError("This phase has no timer to extend")
        try:
            seconds = int(seconds)
        except (TypeError, ValueError):
            raise EngineError("Invalid duration")
        if not (5 <= seconds <= 120):
            raise EngineError("Extension must be between 5 and 120 seconds")
        self.state.phase_end += seconds
        EventManager.log(self.state, "phase_extended", seconds=seconds)

    def admin_remove_player(self, host_id: Optional[str], target_id: str) -> None:
        """Removes a disruptive or unreachable player. Before the game
        starts this is exactly kick_player (gone without a trace, no role
        was ever dealt to reshuffle). Mid-game a role, night actions, and
        stats already exist for them, so 'removed' means eliminated —
        same mechanism a Gunner's shot or the day's vote already use —
        rather than trying to erase them from a game in progress. A
        per-match host can't remove themselves this way; the bot owner
        (host_id=None) has no such restriction — they can remove anyone,
        including the current host."""
        self._require_host_or_system(host_id)
        if host_id is not None and target_id == host_id:
            raise EngineError("Host cannot remove themselves")
        if self.state.phase == Phase.LOBBY:
            self.kick_player(host_id, target_id)
            return
        target = self.state.players.get(target_id)
        if not target:
            raise EngineError("Unknown player")
        if not target.alive:
            raise EngineError("Player is already out of the game")
        DeathManager.eliminate(self.state, target_id, "removed_by_admin")
        win = WinConditionManager.check(self.state)
        if win:
            PhaseManager.to_game_over(self.state, win)

    # ---------- discussion chat (spec sections 11 & 32) ----------
    # The Telegram group never sees any of this — it exists only inside
    # this one game's state, scoped to exactly its own players, exactly
    # like a real discussion phase demands.

    def send_chat_message(self, player_id: str, text: str) -> None:
        if self.state.phase != Phase.DAY_DISCUSSION:
            raise EngineError("Discussion is not open right now")
        player = self.state.players.get(player_id)
        if not player:
            raise EngineError("Unknown player")
        if not player.alive:
            raise EngineError("Dead players can only spectate the discussion")
        if player.silenced:
            raise EngineError("You are silenced today and cannot send messages")
        text = text.strip()
        if not text:
            raise EngineError("Message is empty")
        if len(text) > CHAT_MAX_LEN:
            text = text[:CHAT_MAX_LEN]
        self.state.chat_messages.append(ChatMessage(
            message_id=str(uuid.uuid4()), player_id=player_id,
            display_name=player.display_name, text=text, day_number=self.state.day_number,
        ))
        if len(self.state.chat_messages) > CHAT_HISTORY_LIMIT:
            del self.state.chat_messages[: len(self.state.chat_messages) - CHAT_HISTORY_LIMIT]
        EventManager.log(self.state, "chat_message", player_id=player_id)

    # ---------- mayor / gunner day actions ----------
    # These are day_action roles (see ROLES), and the WebApp only ever shows
    # their buttons on the day/discussion screen — but a raw WebSocket
    # message doesn't go through the UI, so the engine has to enforce that
    # itself instead of trusting the client to only ask at the right time.

    def reveal_mayor(self, player_id: str) -> None:
        if self.state.phase != Phase.DAY_DISCUSSION:
            raise EngineError("Mayor can only reveal during the day")
        p = self._require_alive(player_id)
        if p.role != RoleName.MAYOR:
            raise EngineError("Only the Mayor can reveal")
        if p.mayor_revealed:
            raise EngineError("Already revealed")
        p.mayor_revealed = True
        p.vote_weight = 3
        EventManager.log(self.state, "mayor_revealed", player_id=player_id)

    def gunner_shoot(self, player_id: str, target_id: str) -> None:
        if self.state.phase != Phase.DAY_DISCUSSION:
            raise EngineError("Gunner can only shoot during the day")
        p = self._require_alive(player_id)
        if p.role != RoleName.GUNNER:
            raise EngineError("Only the Gunner can shoot")
        if p.gunner_bullets_used >= (ROLES[RoleName.GUNNER].max_charges or 0):
            raise EngineError("Out of ammunition")
        target = self._require_alive(target_id)
        p.gunner_bullets_used += 1
        p.kills += 1
        DeathManager.eliminate(self.state, target_id, "gunner")
        win = WinConditionManager.check(self.state)
        if win:
            PhaseManager.to_game_over(self.state, win)

    # ---------- reconnection / hidden-info view ----------

    def get_player_view(self, player_id: str) -> dict:
        """The ONLY information a given player (or their reconnecting client)
        is allowed to see. This is what makes hidden roles actually hidden."""
        s = self.state
        me = s.players.get(player_id)
        game_over = s.phase == Phase.GAME_OVER
        view = {
            "game_id": s.game_id,
            "phase": s.phase.value,
            "night_number": s.night_number,
            "day_number": s.day_number,
            "phase_ends_in": TimerManager.remaining_seconds(s),
            "host_id": s.host_id,
            "players": [
                {
                    "player_id": p.player_id,
                    "display_name": p.display_name,
                    "avatar_url": p.avatar_url,
                    "alive": p.alive,
                    "is_host": p.is_host,
                    "connected": p.connected,
                    # Final role reveal (spec section 22): once the game is
                    # over, this is no longer hidden info for anyone — same
                    # rule everyone gets the same shared reveal.
                    "role": (p.role.value if p.role and (game_over or p.player_id == player_id
                             or (not p.alive and s.settings.reveal_role_on_death)) else None),
                }
                for p in s.players.values()
            ],
            "last_night_deaths": s.last_night_deaths if s.phase != Phase.NIGHT else [],
            "last_vote_result": s.last_vote_result,
            "winner": (
                {"faction": s.winner.faction.value if s.winner.faction else None,
                 "winners": s.winner.winners, "reason": s.winner.reason}
                if s.winner else None
            ),
            # Discussion chat (spec sections 11/32): visible to everyone in
            # THIS game regardless of phase or alive status — dead players
            # spectate (they can see it, just can't call send_chat_message).
            "chat": [
                {"message_id": m.message_id, "player_id": m.player_id,
                 "display_name": m.display_name, "text": m.text,
                 "day_number": m.day_number, "ts": m.ts}
                for m in s.chat_messages
            ],
        }
        if me:
            role_def = ROLES[me.role] if me.role else None
            no_target_actions = (ActionType.IGNITE, ActionType.ALERT)
            view["me"] = {
                "player_id": me.player_id,
                "role": me.role.value if me.role else None,
                "faction": role_def.faction.value if role_def else None,
                "role_description": role_def.description if role_def else None,
                "alive": me.alive,
                "can_chat": me.alive and not me.silenced and s.phase == Phase.DAY_DISCUSSION,
                "has_submitted_night_action": player_id in s.night_actions,
                "has_voted": player_id in s.votes,
                "vote_weight": me.vote_weight,
                "night_result": self._night_results.get(player_id),
                # Tells the frontend how to draw the night-action screen
                # without it needing to know any role rules itself.
                "night_action_type": role_def.night_action.value if role_def and role_def.night_action else None,
                "night_action_needs_target": bool(
                    role_def and role_def.night_action and role_def.night_action not in no_target_actions
                ),
                "can_target_self": bool(role_def and role_def.can_target_self),
                "day_action_type": role_def.day_action.value if role_def and role_def.day_action else None,
                "max_charges": role_def.max_charges if role_def else None,
                "charges_used": (
                    me.veteran_alerts_used if me.role == RoleName.VETERAN
                    else me.gunner_bullets_used if me.role == RoleName.GUNNER
                    else None
                ),
                "mayor_revealed": me.mayor_revealed if me.role == RoleName.MAYOR else None,
            }
            if me.role and ROLES[me.role].faction == Faction.MAFIA:
                view["me"]["mafia_teammates"] = RoleManager.mafia_teammates(s, player_id)
            if game_over:
                # Personal statistics (spec section 22) — shown alongside
                # the shared final role reveal above, but these numbers are
                # specifically about *you*, not a leaderboard of everyone.
                view["me"]["stats"] = {
                    "role": me.role.value if me.role else None,
                    "won": bool(s.winner and player_id in s.winner.winners),
                    "survived": me.alive,
                    "death_night": me.death_night,
                    "kills": me.kills,
                    "investigations": me.investigations,
                    "protections": me.protections,
                    "votes_cast": me.votes_cast,
                }
        if player_id == s.host_id:
            # Admin panel data (WebApp shows this UI only to the host, but
            # the gate that actually matters is this one: nobody else's
            # get_player_view ever includes it, same principle as hidden
            # roles above).
            timed_phases = (Phase.NIGHT, Phase.DAY_DISCUSSION, Phase.VOTING, Phase.VOTE_RESULTS)
            eligible_night = [p for p in s.players.values() if p.alive and p.role and ROLES[p.role].night_action]
            view["admin"] = {
                "settings": {
                    "night_duration_s": s.settings.night_duration_s,
                    "day_duration_s": s.settings.day_duration_s,
                    "voting_duration_s": s.settings.voting_duration_s,
                    "tie_rule": s.settings.tie_rule,
                    "anonymous_voting": s.settings.anonymous_voting,
                    "allow_self_vote": s.settings.allow_self_vote,
                    "reveal_role_on_death": s.settings.reveal_role_on_death,
                },
                "night_actions_submitted": len(s.night_actions) if s.phase == Phase.NIGHT else None,
                "night_actions_expected": len(eligible_night) if s.phase == Phase.NIGHT else None,
                "votes_cast": len(s.votes) if s.phase == Phase.VOTING else None,
                "votes_expected": len(s.alive_players()) if s.phase == Phase.VOTING else None,
                "can_force_advance": s.phase in timed_phases,
                "can_extend_timer": s.phase in timed_phases,
            }
        return view

    def find_player_id(self, telegram_user_id: int) -> Optional[str]:
        for pid, p in self.state.players.items():
            if p.telegram_user_id == telegram_user_id:
                return pid
        return None

    # ---------- helpers ----------

    def _require_host(self, player_id: str) -> PlayerState:
        if player_id != self.state.host_id:
            raise EngineError("Only the host can do that")
        return self.state.players[player_id]

    def _require_host_or_system(self, actor_id: Optional[str]) -> None:
        """actor_id is a real player_id when the per-match host is calling
        (must equal state.host_id, same rule as _require_host) — or None
        for a system-level caller who's already been authorized upstream
        (the bot owner's global admin panel, see routes_admin.py) and
        isn't necessarily even a player in this particular match."""
        if actor_id is not None and actor_id != self.state.host_id:
            raise EngineError("Only the host can do that")

    def _require_alive(self, player_id: str) -> PlayerState:
        p = self.state.players.get(player_id)
        if not p:
            raise EngineError("Unknown player")
        if not p.alive:
            raise EngineError("You are no longer alive")
        return p
