"""Mayor-reveal and Gunner-shoot are day_action roles (see ROLES) and the
WebApp only ever shows their buttons on the day/discussion screen — but
nothing stopped a raw WebSocket message from calling them at night, during
voting, or even in the lobby. These tests lock in that the engine itself
now enforces "day only", the same way every night action already enforces
"only during night"."""
import pytest
from app.game_engine.roles import RoleName as R
from app.game_engine.engine import EngineError
from app.game_engine.state import Phase
from app.game_engine.managers import PhaseManager
from tests.conftest import make_engine_with_roles


def _base_engine_with_mayor_and_gunner():
    return make_engine_with_roles([R.MAFIOSO, R.MAYOR, R.GUNNER, R.CITIZEN,
                                    R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])


def test_reveal_mayor_rejected_at_night():
    eng, ids = _base_engine_with_mayor_and_gunner()
    assert eng.state.phase == Phase.NIGHT
    with pytest.raises(EngineError):
        eng.reveal_mayor(ids["P1"])
    assert eng.state.players[ids["P1"]].mayor_revealed is False


def test_reveal_mayor_rejected_during_voting():
    eng, ids = _base_engine_with_mayor_and_gunner()
    PhaseManager.to_day(eng.state)
    PhaseManager.to_voting(eng.state)
    with pytest.raises(EngineError):
        eng.reveal_mayor(ids["P1"])


def test_reveal_mayor_allowed_during_discussion():
    eng, ids = _base_engine_with_mayor_and_gunner()
    PhaseManager.to_day(eng.state)
    eng.reveal_mayor(ids["P1"])
    assert eng.state.players[ids["P1"]].mayor_revealed is True
    assert eng.state.players[ids["P1"]].vote_weight == 3


def test_gunner_shoot_rejected_at_night():
    eng, ids = _base_engine_with_mayor_and_gunner()
    assert eng.state.phase == Phase.NIGHT
    with pytest.raises(EngineError):
        eng.gunner_shoot(ids["P2"], ids["P3"])
    assert eng.state.players[ids["P3"]].alive is True


def test_gunner_shoot_rejected_during_voting():
    eng, ids = _base_engine_with_mayor_and_gunner()
    PhaseManager.to_day(eng.state)
    PhaseManager.to_voting(eng.state)
    with pytest.raises(EngineError):
        eng.gunner_shoot(ids["P2"], ids["P3"])


def test_gunner_shoot_allowed_during_discussion():
    eng, ids = _base_engine_with_mayor_and_gunner()
    PhaseManager.to_day(eng.state)
    eng.gunner_shoot(ids["P2"], ids["P3"])
    assert eng.state.players[ids["P3"]].alive is False
    assert eng.state.players[ids["P2"]].gunner_bullets_used == 1
