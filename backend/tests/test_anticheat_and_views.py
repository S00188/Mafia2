import pytest
from app.game_engine.roles import RoleName as R
from app.game_engine.engine import GameEngine, EngineError
from app.game_engine.state import Phase
from tests.conftest import make_engine_with_roles


def test_player_view_works_in_lobby_before_any_role_is_assigned():
    # Regression test: get_player_view() used to crash with
    # AttributeError('NoneType' object has no attribute 'value') the
    # instant it was called in the lobby, because it unconditionally read
    # p.role.value for your own row without checking p.role was set yet.
    # In production this hit every single player on their very first
    # WebSocket connection (which happens right after joining, well before
    # anyone has started the game) — masked in tests because every other
    # test only calls get_player_view() after start_game().
    eng = GameEngine(game_id="g1", host_telegram_id=1, host_name="Host")
    eng.add_player(telegram_user_id=2, display_name="P2")
    view = eng.get_player_view(eng.state.host_id)
    assert view["phase"] == "lobby"
    assert view["me"]["role"] is None
    assert all(p["role"] is None for p in view["players"])


def test_dead_player_cannot_submit_night_action():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    eng.state.players[ids["P0"]].alive = False
    with pytest.raises(EngineError):
        eng.submit_night_action(ids["P0"], ids["P1"])


def test_cannot_act_outside_night_phase():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    eng.state.phase = Phase.DAY_DISCUSSION
    with pytest.raises(EngineError):
        eng.submit_night_action(ids["P0"], ids["P1"])


def test_duplicate_night_action_rejected():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    eng.submit_night_action(ids["P0"], ids["P1"])
    with pytest.raises(EngineError):
        eng.submit_night_action(ids["P0"], ids["P2"])


def test_citizen_has_no_night_action():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    with pytest.raises(EngineError):
        eng.submit_night_action(ids["P1"], ids["P2"])


def test_player_view_never_leaks_other_alive_players_roles():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.DOCTOR, R.COMMISSIONER, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    view = eng.get_player_view(ids["P1"])  # doctor's own view
    for p in view["players"]:
        if p["player_id"] != ids["P1"]:
            assert p["role"] is None  # nobody else's role leaks while alive
    assert view["me"]["role"] == "Doctor"


def test_mafia_teammates_are_visible_only_to_mafia():
    eng, ids = make_engine_with_roles([R.DON, R.MAFIOSO, R.CONSIGLIERE, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    don_view = eng.get_player_view(ids["P0"])
    citizen_view = eng.get_player_view(ids["P3"])
    assert set(don_view["me"]["mafia_teammates"]) == {ids["P1"], ids["P2"]}
    assert "mafia_teammates" not in citizen_view["me"]


def test_reconnect_returns_consistent_authoritative_state():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.DOCTOR, R.COMMISSIONER, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN])
    eng.submit_night_action(ids["P0"], ids["P3"])
    view_before = eng.get_player_view(ids["P0"])
    # simulate disconnect + reconnect: nothing should change, no re-roll
    view_after = eng.get_player_view(ids["P0"])
    assert view_before["me"]["has_submitted_night_action"] is True
    assert view_after["me"]["has_submitted_night_action"] is True
    assert view_before["me"]["role"] == view_after["me"]["role"]
