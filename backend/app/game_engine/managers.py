"""
GameEngine's internal managers. Each class has one job and is fully
unit-testable without any WebSocket/Telegram/HTTP layer involved.
"""
from __future__ import annotations
import random
from time import time
from typing import Optional
from collections import Counter, defaultdict

from app.game_engine.roles import RoleName, Faction, ActionType, ROLES, MAFIA_KILLING_ROLES
from app.game_engine.compositions import get_composition
from app.game_engine.state import (
    GameState, PlayerState, Phase, NightAction, Vote, WinResult,
)

# Investigator never reveals the exact role: it reveals a small group of
# look-alike roles that includes the real one. Grouped by "investigative
# flavor" so the result is meaningfully ambiguous, not random noise.
INVESTIGATOR_GROUPS: list[set[RoleName]] = [
    {RoleName.DOCTOR, RoleName.BODYGUARD, RoleName.VETERAN},
    {RoleName.COMMISSIONER, RoleName.CONSIGLIERE},
    {RoleName.INVESTIGATOR, RoleName.TRACKER, RoleName.WATCHER},
    {RoleName.MAFIOSO, RoleName.DON},
    {RoleName.FRAMER, RoleName.SILENCER},
    {RoleName.SERIAL_KILLER, RoleName.ARSONIST},
    {RoleName.SURVIVOR, RoleName.JESTER},
    {RoleName.CITIZEN, RoleName.MAYOR, RoleName.GUNNER, RoleName.MEDIUM},
]


class TimerManager:
    """Server-authoritative phase timing. Frontend only renders a countdown
    from phase_start/phase_end that this class sets — it never owns time."""

    @staticmethod
    def start_phase(state: GameState, duration_s: int) -> None:
        now = time()
        state.phase_start = now
        state.phase_end = now + duration_s

    @staticmethod
    def remaining_seconds(state: GameState) -> float:
        return max(0.0, state.phase_end - time())

    @staticmethod
    def is_expired(state: GameState) -> bool:
        return time() >= state.phase_end


class EventManager:
    @staticmethod
    def log(state: GameState, event_type: str, **payload) -> None:
        state.log(event_type, **payload)


class RoleManager:
    @staticmethod
    def assign_roles(state: GameState, rng: Optional[random.Random] = None) -> None:
        rng = rng or random.Random()
        player_ids = list(state.players.keys())
        n = len(player_ids)
        if not (6 <= n <= 25):
            raise ValueError("Mafia requires 6–25 players to start")
        roles = get_composition(n)
        shuffled_roles = roles[:]
        rng.shuffle(shuffled_roles)
        rng.shuffle(player_ids)
        for pid, role in zip(player_ids, shuffled_roles):
            state.players[pid].role = role
            state.players[pid].vote_weight = 1
        EventManager.log(state, "roles_assigned", count=n)

    @staticmethod
    def mafia_teammates(state: GameState, player_id: str) -> list[str]:
        p = state.players[player_id]
        if p.role is None or ROLES[p.role].faction != Faction.MAFIA:
            return []
        return [pid for pid, o in state.players.items()
                if pid != player_id and o.role and ROLES[o.role].faction == Faction.MAFIA]


class PhaseManager:
    @staticmethod
    def to_night(state: GameState) -> None:
        state.phase = Phase.NIGHT
        state.night_number += 1
        state.night_actions.clear()
        for p in state.players.values():
            p.framed = False
            p.silenced = False
            p.protected_by_doctor = False
            p.protected_by_bodyguard = None
        TimerManager.start_phase(state, state.settings.night_duration_s)
        EventManager.log(state, "phase_night", night=state.night_number)

    @staticmethod
    def to_day(state: GameState) -> None:
        state.phase = Phase.DAY_DISCUSSION
        state.day_number += 1
        TimerManager.start_phase(state, state.settings.day_duration_s)
        EventManager.log(state, "phase_day", day=state.day_number)

    @staticmethod
    def to_voting(state: GameState) -> None:
        state.phase = Phase.VOTING
        state.votes.clear()
        TimerManager.start_phase(state, state.settings.voting_duration_s)
        EventManager.log(state, "phase_voting")

    @staticmethod
    def to_vote_results(state: GameState) -> None:
        state.phase = Phase.VOTE_RESULTS
        TimerManager.start_phase(state, 10)

    @staticmethod
    def to_game_over(state: GameState, result: WinResult) -> None:
        state.phase = Phase.GAME_OVER
        state.winner = result
        EventManager.log(state, "game_over", faction=result.faction, reason=result.reason)


class NightResolver:
    """Resolves an entire night in explicit phases so effects (frame,
    silence, protection) are guaranteed to be applied before the things
    that read them (investigations, kills)."""

    @staticmethod
    def resolve(state: GameState) -> list[dict]:
        actions = list(state.night_actions.values())
        deaths: dict[str, str] = {}          # player_id -> reason
        results: dict[str, dict] = {}        # player_id -> private result payload
        visits: dict[str, list[str]] = defaultdict(list)   # target_id -> [visitor_id]

        for a in actions:
            if a.target_id:
                visits[a.target_id].append(a.player_id)

        # --- Phase 1: protections ---
        for a in actions:
            if a.action_type == ActionType.PROTECT and a.target_id:
                target = state.players[a.target_id]
                if a.player_id == a.target_id:
                    doc = state.players[a.player_id]
                    if doc.last_self_heal_night == state.night_number - 1:
                        continue  # self-heal two nights in a row is not allowed, action fizzles
                    doc.last_self_heal_night = state.night_number
                target.protected_by_doctor = True
            elif a.action_type == ActionType.GUARD and a.target_id:
                state.players[a.target_id].protected_by_bodyguard = a.player_id

        # --- Phase 2: setup effects (frame / silence / douse) ---
        for a in actions:
            if a.action_type == ActionType.FRAME and a.target_id:
                state.players[a.target_id].framed = True
            elif a.action_type == ActionType.SILENCE and a.target_id:
                state.players[a.target_id].silenced = True
            elif a.action_type == ActionType.DOUSE and a.target_id:
                state.players[a.target_id].doused = True
                state.doused_players.add(a.target_id)

        # --- Phase 3: kills ---
        pending_kills: dict[str, list[str]] = defaultdict(list)  # target -> [attacker labels]

        mafia_votes = [a for a in actions
                       if a.action_type == ActionType.KILL and a.role in MAFIA_KILLING_ROLES]
        if mafia_votes:
            target = NightResolver._resolve_mafia_target(state, mafia_votes)
            if target:
                pending_kills[target].append("mafia")

        for a in actions:
            if a.action_type == ActionType.KILL and a.role == RoleName.SERIAL_KILLER and a.target_id:
                pending_kills[a.target_id].append("serial_killer")

        for a in actions:
            if a.action_type == ActionType.ALERT:
                vet = state.players[a.player_id]
                if vet.veteran_alerts_used >= 2:
                    continue
                vet.veteran_alerts_used += 1
                for visitor_id in visits.get(a.player_id, []):
                    if visitor_id != a.player_id:
                        pending_kills[visitor_id].append("veteran_alert")

        for a in actions:
            if a.action_type == ActionType.IGNITE:
                for target_id in list(state.doused_players):
                    pending_kills[target_id].append("arsonist_ignite")
                    state.players[target_id].doused = False
                state.doused_players.clear()

        # --- Phase 4: apply protections against pending kills ---
        for target_id, attackers in pending_kills.items():
            target = state.players[target_id]
            if not target.alive:
                continue
            if target.protected_by_doctor:
                results.setdefault(target_id, {})["saved_by"] = "doctor"
                continue
            if target.protected_by_bodyguard:
                bg_id = target.protected_by_bodyguard
                bg = state.players.get(bg_id)
                if bg and bg.alive:
                    deaths[bg_id] = "died protecting a teammate"
                    if len(attackers) == 1 and attackers[0] == "mafia":
                        # lone mafia attacker trades with the bodyguard
                        mafia_attacker = NightResolver._last_mafia_attacker(mafia_votes, state)
                        if mafia_attacker:
                            deaths[mafia_attacker] = "killed intercepting a Bodyguard"
                    results.setdefault(target_id, {})["saved_by"] = "bodyguard"
                    continue
            deaths[target_id] = "/".join(sorted(set(attackers)))

        for pid, reason in deaths.items():
            p = state.players[pid]
            if p.alive:
                p.alive = False
                p.death_reason = reason
                p.death_night = state.night_number

        # --- Phase 5: investigations (after deaths, so results are final) ---
        for a in actions:
            if a.action_type != ActionType.INVESTIGATE or not a.target_id:
                continue
            target = state.players[a.target_id]
            if a.role == RoleName.CONSIGLIERE:
                results.setdefault(a.player_id, {})["exact_role"] = target.role.value
            elif a.role == RoleName.COMMISSIONER:
                if target.role == RoleName.DON:
                    verdict = "not_mafia"          # Don reads clean by design
                elif target.framed:
                    verdict = "mafia"
                else:
                    verdict = "mafia" if ROLES[target.role].faction == Faction.MAFIA else "not_mafia"
                results.setdefault(a.player_id, {})["verdict"] = verdict
            elif a.role == RoleName.INVESTIGATOR:
                group = next((g for g in INVESTIGATOR_GROUPS if target.role in g),
                             {target.role})
                results.setdefault(a.player_id, {})["possible_roles"] = sorted(r.value for r in group)

        for a in actions:
            if a.action_type == ActionType.TRACK and a.target_id:
                target_actions = [x for x in actions if x.player_id == a.target_id]
                results.setdefault(a.player_id, {})["visited"] = (
                    target_actions[0].target_id if target_actions and target_actions[0].target_id else None
                )
            elif a.action_type == ActionType.WATCH and a.target_id:
                results.setdefault(a.player_id, {})["visitors"] = [
                    v for v in visits.get(a.target_id, []) if v != a.player_id
                ]
            elif a.action_type == ActionType.SEANCE and a.target_id:
                results.setdefault(a.player_id, {})["seance_open_with"] = a.target_id

        state.last_night_deaths = [
            {"player_id": pid, "reason": reason} for pid, reason in deaths.items()
        ]
        EventManager.log(state, "night_resolved", deaths=list(deaths.keys()))
        return state.last_night_deaths, results  # type: ignore[return-value]

    @staticmethod
    def _resolve_mafia_target(state: GameState, mafia_votes: list[NightAction]) -> Optional[str]:
        targets = [a.target_id for a in mafia_votes if a.target_id]
        if not targets:
            return None
        counts = Counter(targets)
        top = max(counts.values())
        tied = [t for t, c in counts.items() if c == top]
        if len(tied) == 1:
            return tied[0]
        # tie-break: Don's vote wins if Don is alive and voted for one of the tied targets
        don_vote = next((a for a in mafia_votes if a.role == RoleName.DON and a.target_id in tied), None)
        if don_vote:
            return don_vote.target_id
        # otherwise: earliest submitted vote among the tied targets (deterministic)
        earliest = min((a for a in mafia_votes if a.target_id in tied), key=lambda a: a.submitted_at)
        return earliest.target_id

    @staticmethod
    def _last_mafia_attacker(mafia_votes: list[NightAction], state: GameState) -> Optional[str]:
        alive_votes = [a for a in mafia_votes if state.players[a.player_id].alive]
        if not alive_votes:
            return None
        return sorted(alive_votes, key=lambda a: a.submitted_at)[-1].player_id


class VoteManager:
    @staticmethod
    def submit_vote(state: GameState, voter_id: str, target_id: Optional[str]) -> None:
        voter = state.players[voter_id]
        if not voter.alive:
            raise ValueError("Dead players cannot vote")
        if state.phase != Phase.VOTING:
            raise ValueError("Voting is not open")
        if target_id and not state.players[target_id].alive:
            raise ValueError("Cannot vote for a dead player")
        if target_id == voter_id and not state.settings.allow_self_vote:
            raise ValueError("Self-voting is disabled")
        if getattr(voter, "silenced", False):
            raise ValueError("You are silenced today and cannot vote")
        state.votes[voter_id] = Vote(voter_id=voter_id, target_id=target_id, weight=voter.vote_weight)

    @staticmethod
    def tally(state: GameState) -> dict:
        totals: dict[str, int] = defaultdict(int)
        for v in state.votes.values():
            if v.target_id:
                totals[v.target_id] += v.weight
        if not totals:
            return {"eliminated": None, "totals": {}, "reason": "no_votes"}
        top = max(totals.values())
        leaders = [pid for pid, c in totals.items() if c == top]
        if len(leaders) > 1:
            if state.settings.tie_rule == "random":
                eliminated = random.choice(leaders)
            else:
                eliminated = None  # no_elimination or revote both stop the lynch this round
        else:
            eliminated = leaders[0]
        result = {"eliminated": eliminated, "totals": dict(totals), "reason": "tie" if len(leaders) > 1 else "majority"}
        state.last_vote_result = result
        return result


class DeathManager:
    @staticmethod
    def eliminate(state: GameState, player_id: str, reason: str) -> None:
        p = state.players[player_id]
        if not p.alive:
            return
        p.alive = False
        p.death_reason = reason
        if p.role == RoleName.JESTER and reason == "day_vote":
            p.jester_won = True
        EventManager.log(state, "player_eliminated", player_id=player_id, reason=reason)


class WinConditionManager:
    @staticmethod
    def check(state: GameState) -> Optional[WinResult]:
        alive = state.alive_players()
        mafia = [p for p in alive if p.role and ROLES[p.role].faction == Faction.MAFIA]
        town = [p for p in alive if p.role and ROLES[p.role].faction == Faction.TOWN]
        killing_neutrals = [p for p in alive if p.role in (RoleName.SERIAL_KILLER, RoleName.ARSONIST)]
        other_neutrals = [p for p in alive if p.role in (RoleName.SURVIVOR, RoleName.JESTER)]

        if not mafia and not killing_neutrals:
            return WinResult(Faction.TOWN, [p.player_id for p in town], "All Mafia and killing neutrals eliminated")

        if mafia and len(mafia) >= len(town) + len(killing_neutrals):
            return WinResult(Faction.MAFIA, [p.player_id for p in mafia], "Mafia can no longer be outvoted")

        if killing_neutrals and not mafia and not town:
            winners = [p.player_id for p in killing_neutrals]
            return WinResult(Faction.NEUTRAL, winners, "Only killing neutral(s) remain")

        if len(alive) == 1 and alive[0].role in (RoleName.SURVIVOR,):
            return WinResult(Faction.NEUTRAL, [alive[0].player_id], "Survivor is the last one standing")

        return None
