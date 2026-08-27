import pytest
from app.game_engine.roles import RoleName as R
from app.game_engine.state import Phase
from app.game_engine.managers import PhaseManager
from tests.conftest import make_engine_with_roles


def _to_voting(eng):
    eng.state.phase = Phase.DAY_DISCUSSION
    PhaseManager.to_voting(eng.state)


def test_majority_vote_eliminates_target():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    _to_voting(eng)
    for p in ["P1", "P2", "P3"]:
        eng.submit_vote(ids[p], ids["P0"])
    eng.submit_vote(ids["P4"], ids["P1"])
    eng.resolve_voting_if_ready(force=True)
    assert eng.state.players[ids["P0"]].alive is False


def test_tie_with_default_rule_results_in_no_elimination():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    _to_voting(eng)
    eng.submit_vote(ids["P0"], ids["P1"])
    eng.submit_vote(ids["P2"], ids["P0"])
    eng.resolve_voting_if_ready(force=True)
    assert eng.state.players[ids["P0"]].alive is True
    assert eng.state.players[ids["P1"]].alive is True


def test_mayor_reveal_boosts_vote_weight_to_three():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.MAYOR, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    eng.state.phase = Phase.DAY_DISCUSSION
    eng.reveal_mayor(ids["P1"])
    _to_voting(eng)
    eng.submit_vote(ids["P1"], ids["P0"])   # weight 3 alone beats 2 regular votes
    eng.submit_vote(ids["P2"], ids["P3"])
    eng.submit_vote(ids["P4"], ids["P3"])
    eng.resolve_voting_if_ready(force=True)
    assert eng.state.players[ids["P0"]].alive is False


def test_dead_player_cannot_vote():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    eng.state.players[ids["P1"]].alive = False
    _to_voting(eng)
    with pytest.raises(Exception):
        eng.submit_vote(ids["P1"], ids["P0"])


def test_self_vote_disabled_by_default():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    _to_voting(eng)
    with pytest.raises(Exception):
        eng.submit_vote(ids["P0"], ids["P0"])
