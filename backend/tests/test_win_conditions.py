from app.game_engine.roles import RoleName as R, Faction
from app.game_engine.managers import WinConditionManager
from tests.conftest import make_engine_with_roles


def test_town_wins_when_all_mafia_eliminated():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    eng.state.players[ids["P0"]].alive = False
    result = WinConditionManager.check(eng.state)
    assert result is not None and result.faction == Faction.TOWN


def test_mafia_wins_when_mafia_outnumbers_the_rest():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.MAFIOSO, R.MAFIOSO, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    for p in ["P3", "P4", "P5", "P6"]:
        eng.state.players[ids[p]].alive = False
    # alive now: 3 mafia vs 1 citizen (P7)
    result = WinConditionManager.check(eng.state)
    assert result is not None and result.faction == Faction.MAFIA


def test_serial_killer_wins_alone_when_mafia_and_town_gone():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.SERIAL_KILLER, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    for p in ["P0", "P2", "P3", "P4", "P5", "P6", "P7"]:
        eng.state.players[ids[p]].alive = False
    result = WinConditionManager.check(eng.state)
    assert result is not None and result.faction == Faction.NEUTRAL
    assert ids["P1"] in result.winners


def test_no_winner_mid_game():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    result = WinConditionManager.check(eng.state)
    assert result is None
