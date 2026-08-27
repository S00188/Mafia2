"""
Balanced role compositions for every supported player count (6–25).

DESIGN: Each count has explicit, hand-tuned roles ensuring:
- Mafia ~27–33% (competitive, not dominant)
- 6–9 only: Don, Mafioso, Commissioner, Doctor, Investigator, Citizen
- 10–12: Add Consigliere (Mafia info), Tracker/Watcher
- 13–15: Add Framer (Mafia disruption), Mayor, Bodyguard, Veteran
- 16–19: Add Silencer, Medium, Gunner
- 20–25: Add Neutral roles (Survivor, Jester, Serial Killer)
- Never: Arsonist, Jester+SerialKiller+Arsonist together
"""
from __future__ import annotations
from app.game_engine.roles import RoleName as R, ROLES

Composition = dict[str, list[R]]

COMPOSITIONS: dict[int, Composition] = {
    6: {
        "mafia": [R.DON, R.MAFIOSO],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.CITIZEN],
        "neutral": [],
    },
    7: {
        "mafia": [R.DON, R.MAFIOSO],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.CITIZEN, R.CITIZEN],
        "neutral": [],
    },
    8: {
        "mafia": [R.DON, R.MAFIOSO],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "neutral": [],
    },
    9: {
        "mafia": [R.DON, R.MAFIOSO],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "neutral": [],
    },
    10: {
        "mafia": [R.DON, R.MAFIOSO, R.CONSIGLIERE],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.TRACKER, R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "neutral": [],
    },
    11: {
        "mafia": [R.DON, R.MAFIOSO, R.CONSIGLIERE],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.TRACKER, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "neutral": [],
    },
    12: {
        "mafia": [R.DON, R.MAFIOSO, R.CONSIGLIERE],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.TRACKER, R.WATCHER, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "neutral": [],
    },
    13: {
        "mafia": [R.DON, R.MAFIOSO, R.CONSIGLIERE, R.FRAMER],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.TRACKER, R.WATCHER, R.MAYOR, R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "neutral": [],
    },
    14: {
        "mafia": [R.DON, R.MAFIOSO, R.CONSIGLIERE, R.FRAMER],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.TRACKER, R.WATCHER, R.MAYOR, R.BODYGUARD, R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "neutral": [],
    },
    15: {
        "mafia": [R.DON, R.MAFIOSO, R.CONSIGLIERE, R.FRAMER],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.TRACKER, R.WATCHER, R.MAYOR, R.BODYGUARD, R.VETERAN, R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "neutral": [],
    },
    16: {
        "mafia": [R.DON, R.MAFIOSO, R.MAFIOSO, R.CONSIGLIERE, R.FRAMER],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.TRACKER, R.WATCHER, R.MAYOR, R.BODYGUARD, R.VETERAN, R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "neutral": [],
    },
    17: {
        "mafia": [R.DON, R.MAFIOSO, R.MAFIOSO, R.CONSIGLIERE, R.FRAMER],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.TRACKER, R.WATCHER, R.MAYOR, R.BODYGUARD, R.VETERAN, R.MEDIUM, R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "neutral": [],
    },
    18: {
        "mafia": [R.DON, R.MAFIOSO, R.MAFIOSO, R.CONSIGLIERE, R.FRAMER, R.SILENCER],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.TRACKER, R.WATCHER, R.MAYOR, R.BODYGUARD, R.VETERAN, R.MEDIUM, R.GUNNER, R.CITIZEN, R.CITIZEN],
        "neutral": [],
    },
    19: {
        "mafia": [R.DON, R.MAFIOSO, R.MAFIOSO, R.CONSIGLIERE, R.FRAMER, R.SILENCER],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.TRACKER, R.WATCHER, R.MAYOR, R.BODYGUARD, R.VETERAN, R.MEDIUM, R.GUNNER, R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "neutral": [],
    },
    20: {
        "mafia": [R.DON, R.MAFIOSO, R.MAFIOSO, R.CONSIGLIERE, R.FRAMER, R.SILENCER],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.TRACKER, R.WATCHER, R.MAYOR, R.BODYGUARD, R.VETERAN, R.MEDIUM, R.GUNNER, R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "neutral": [R.SURVIVOR],
    },
    21: {
        "mafia": [R.DON, R.MAFIOSO, R.MAFIOSO, R.CONSIGLIERE, R.FRAMER, R.SILENCER],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.TRACKER, R.WATCHER, R.MAYOR, R.BODYGUARD, R.VETERAN, R.MEDIUM, R.GUNNER, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "neutral": [R.SURVIVOR],
    },
    22: {
        "mafia": [R.DON, R.MAFIOSO, R.MAFIOSO, R.MAFIOSO, R.CONSIGLIERE, R.FRAMER, R.SILENCER],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.TRACKER, R.WATCHER, R.MAYOR, R.BODYGUARD, R.VETERAN, R.MEDIUM, R.GUNNER, R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "neutral": [R.SURVIVOR, R.JESTER],
    },
    23: {
        "mafia": [R.DON, R.MAFIOSO, R.MAFIOSO, R.MAFIOSO, R.CONSIGLIERE, R.FRAMER, R.SILENCER],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.TRACKER, R.WATCHER, R.MAYOR, R.BODYGUARD, R.VETERAN, R.MEDIUM, R.GUNNER, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "neutral": [R.SURVIVOR, R.JESTER],
    },
    24: {
        "mafia": [R.DON, R.MAFIOSO, R.MAFIOSO, R.MAFIOSO, R.CONSIGLIERE, R.FRAMER, R.SILENCER],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.TRACKER, R.WATCHER, R.MAYOR, R.BODYGUARD, R.VETERAN, R.MEDIUM, R.GUNNER, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "neutral": [R.SURVIVOR, R.SERIAL_KILLER],
    },
    25: {
        "mafia": [R.DON, R.MAFIOSO, R.MAFIOSO, R.MAFIOSO, R.MAFIOSO, R.CONSIGLIERE, R.FRAMER, R.SILENCER],
        "town": [R.COMMISSIONER, R.DOCTOR, R.INVESTIGATOR, R.TRACKER, R.WATCHER, R.MAYOR, R.BODYGUARD, R.VETERAN, R.MEDIUM, R.GUNNER, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN],
        "neutral": [R.SURVIVOR, R.SERIAL_KILLER, R.JESTER],
    },
}


def get_composition(player_count: int) -> list[R]:
    if player_count not in COMPOSITIONS:
        raise ValueError(f"Unsupported player count: {player_count} (6–25 only)")
    comp = COMPOSITIONS[player_count]
    roles = [*comp["mafia"], *comp["town"], *comp["neutral"]]
    assert len(roles) == player_count, f"composition for {player_count} sums to {len(roles)}"
    return roles


def validate_all_compositions() -> None:
    for n in range(6, 26):
        if n not in COMPOSITIONS:
            raise ValueError(f"{n}: missing from COMPOSITIONS")
    for n, comp in COMPOSITIONS.items():
        roles = [*comp["mafia"], *comp["town"], *comp["neutral"]]
        assert len(roles) == n, f"{n}: wrong role count ({len(roles)})"
        seen_unique = set()
        for r in roles:
            if ROLES[r].unique:
                assert r not in seen_unique, f"{n}: duplicate unique role {r}"
                seen_unique.add(r)
        neutrals = set(comp["neutral"])
        assert not {R.JESTER, R.SERIAL_KILLER, R.ARSONIST}.issubset(neutrals), \
            f"{n}: Jester+SerialKiller+Arsonist together is disallowed"
        assert len(comp["mafia"]) < (len(comp["town"]) + len(comp["neutral"])), \
            f"{n}: mafia is not a minority"
        assert R.ARSONIST not in roles, f"{n}: Arsonist should not appear in default"
        if n <= 9:
            disruptive = {R.FRAMER, R.SILENCER, R.VETERAN, R.BODYGUARD, R.GUNNER,
                          R.MEDIUM, R.WATCHER, R.TRACKER, R.JESTER, R.SERIAL_KILLER, R.ARSONIST}
            for role in roles:
                assert role not in disruptive, f"{n}: disruptive role {role} in small game (6-9)"
        neutral_count = len(comp["neutral"])
        if 6 <= n <= 19:
            assert neutral_count == 0, f"{n}: should have 0 Neutral but has {neutral_count}"
        elif 20 <= n <= 21:
            assert neutral_count <= 1, f"{n}: should have max 1 Neutral but has {neutral_count}"
        elif 22 <= n <= 23:
            assert neutral_count <= 2, f"{n}: should have max 2 Neutral but has {neutral_count}"
        elif 24 <= n <= 25:
            assert neutral_count <= 3, f"{n}: should have max 3 Neutral but has {neutral_count}"
