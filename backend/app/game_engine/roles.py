"""
Role system for the Mafia game engine.

Every role is pure data + declared capabilities. All *logic* for what a
role's action actually does lives in NightResolver (managers.py) — this
module only says WHO can do WHAT, HOW OFTEN, and WHAT FACTION they belong to.
Keeping it data-driven means adding/removing roles from a game mode never
touches resolution logic.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Faction(str, Enum):
    MAFIA = "mafia"
    TOWN = "town"
    NEUTRAL = "neutral"


class ActionType(str, Enum):
    KILL = "kill"                # mafioso/don mafia-kill vote
    PROTECT = "protect"          # doctor
    GUARD = "guard"              # bodyguard
    INVESTIGATE = "investigate"  # commissioner / consigliere / investigator
    FRAME = "frame"              # framer
    SILENCE = "silence"          # silencer
    TRACK = "track"              # tracker
    WATCH = "watch"              # watcher
    ALERT = "alert"              # veteran night-alert
    SHOOT = "shoot"              # gunner (day, limited ammo)
    DOUSE = "douse"              # arsonist step 1
    IGNITE = "ignite"            # arsonist step 2 (no target needed)
    SEANCE = "seance"            # medium <-> dead player
    REVEAL = "reveal"            # mayor reveals to gain vote weight
    NONE = "none"


class RoleName(str, Enum):
    DON = "Don"
    MAFIOSO = "Mafioso"
    CONSIGLIERE = "Consigliere"
    FRAMER = "Framer"
    SILENCER = "Silencer"
    COMMISSIONER = "Commissioner"
    DOCTOR = "Doctor"
    INVESTIGATOR = "Investigator"
    TRACKER = "Tracker"
    WATCHER = "Watcher"
    BODYGUARD = "Bodyguard"
    MAYOR = "Mayor"
    VETERAN = "Veteran"
    MEDIUM = "Medium"
    GUNNER = "Gunner"
    CITIZEN = "Citizen"
    SURVIVOR = "Survivor"
    JESTER = "Jester"
    SERIAL_KILLER = "Serial Killer"
    ARSONIST = "Arsonist"


@dataclass(frozen=True)
class RoleDefinition:
    name: RoleName
    faction: Faction
    night_action: Optional[ActionType]
    day_action: Optional[ActionType] = None
    max_charges: Optional[int] = None      # None = unlimited while alive
    can_target_self: bool = False
    unique: bool = True                    # only one copy per game
    description: str = ""


ROLES: dict[RoleName, RoleDefinition] = {
    RoleName.DON: RoleDefinition(
        RoleName.DON, Faction.MAFIA, ActionType.KILL,
        description="Mafia leader. Casts the deciding mafia-kill vote. "
                     "Commissioner investigations return a clean result on the Don."),
    RoleName.MAFIOSO: RoleDefinition(
        RoleName.MAFIOSO, Faction.MAFIA, ActionType.KILL, unique=False,
        description="Mafia muscle. Votes on the nightly kill. If Don is dead, "
                     "the highest-priority living Mafioso becomes the deciding vote."),
    RoleName.CONSIGLIERE: RoleDefinition(
        RoleName.CONSIGLIERE, Faction.MAFIA, ActionType.INVESTIGATE,
        description="Investigates one player per night and learns their exact role."),
    RoleName.FRAMER: RoleDefinition(
        RoleName.FRAMER, Faction.MAFIA, ActionType.FRAME,
        description="Frames one player per night; if investigated that night, "
                     "the target reads as Mafia to the Commissioner."),
    RoleName.SILENCER: RoleDefinition(
        RoleName.SILENCER, Faction.MAFIA, ActionType.SILENCE,
        description="Silences one player; they cannot speak or vote the next day."),
    RoleName.COMMISSIONER: RoleDefinition(
        RoleName.COMMISSIONER, Faction.TOWN, ActionType.INVESTIGATE,
        description="Investigates one player per night; learns Mafia-aligned or not "
                     "(Don and framed targets are special-cased server-side)."),
    RoleName.DOCTOR: RoleDefinition(
        RoleName.DOCTOR, Faction.TOWN, ActionType.PROTECT,
        can_target_self=True, max_charges=None,
        description="Protects one player per night from being killed. "
                     "May self-heal, but not on two consecutive nights."),
    RoleName.INVESTIGATOR: RoleDefinition(
        RoleName.INVESTIGATOR, Faction.TOWN, ActionType.INVESTIGATE,
        description="Investigates one player per night; learns a short list of "
                     "possible roles (their real role plus decoys), not the exact role."),
    RoleName.TRACKER: RoleDefinition(
        RoleName.TRACKER, Faction.TOWN, ActionType.TRACK,
        description="Learns who their target visited during the night (or nobody)."),
    RoleName.WATCHER: RoleDefinition(
        RoleName.WATCHER, Faction.TOWN, ActionType.WATCH,
        description="Learns everyone who visited their watched player during the night."),
    RoleName.BODYGUARD: RoleDefinition(
        RoleName.BODYGUARD, Faction.TOWN, ActionType.GUARD,
        description="Guards one player. If that player is attacked, the Bodyguard "
                     "intercepts: the guarded player survives, the Bodyguard dies, and "
                     "a lone attacker dies with them."),
    RoleName.MAYOR: RoleDefinition(
        RoleName.MAYOR, Faction.TOWN, None, day_action=ActionType.REVEAL,
        description="Hidden vote weight is 1. Once revealed (day action, irreversible), "
                     "vote weight becomes 3, validated server-side."),
    RoleName.VETERAN: RoleDefinition(
        RoleName.VETERAN, Faction.TOWN, ActionType.ALERT, max_charges=2,
        description="May go on alert up to 2 times per game; anyone who visits an "
                     "alerted Veteran that night dies."),
    RoleName.MEDIUM: RoleDefinition(
        RoleName.MEDIUM, Faction.TOWN, ActionType.SEANCE,
        description="May open a one-way seance channel with one dead player per night "
                     "(simplified v1: opens a channel flag; chat bridging is a frontend feature)."),
    RoleName.GUNNER: RoleDefinition(
        RoleName.GUNNER, Faction.TOWN, None, day_action=ActionType.SHOOT, max_charges=2,
        description="Has 2 bullets. May publicly shoot a player during the day; "
                     "server validates ammo and target."),
    RoleName.CITIZEN: RoleDefinition(
        RoleName.CITIZEN, Faction.TOWN, None, unique=False,
        description="No night ability. Discusses and votes."),
    RoleName.SURVIVOR: RoleDefinition(
        RoleName.SURVIVOR, Faction.NEUTRAL, None,
        description="Wins by being alive when the game ends, regardless of who else wins."),
    RoleName.JESTER: RoleDefinition(
        RoleName.JESTER, Faction.NEUTRAL, None,
        description="Wins immediately if lynched by the town's day vote. "
                     "By default the game continues afterward for the remaining factions."),
    RoleName.SERIAL_KILLER: RoleDefinition(
        RoleName.SERIAL_KILLER, Faction.NEUTRAL, ActionType.KILL,
        description="Kills one player per night. Wins when alive at the same time as "
                     "no Mafia or Town remain (or is the sole survivor)."),
    RoleName.ARSONIST: RoleDefinition(
        RoleName.ARSONIST, Faction.NEUTRAL, ActionType.DOUSE,
        description="Douses one player per night; a separate Ignite action (no target) "
                     "kills every currently-doused player at once, then clears the list."),
}

# Roles that cast a vote in the shared Mafia night-kill.
MAFIA_KILLING_ROLES = (RoleName.DON, RoleName.MAFIOSO)

# Roles allowed to repeat within a single game (filler roles).
NON_UNIQUE_ROLES = {name for name, r in ROLES.items() if not r.unique}


def role_def(name: RoleName) -> RoleDefinition:
    return ROLES[name]
