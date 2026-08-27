"""Admin panel. These methods have two legitimate callers:
 - the per-match host (a real player_id equal to state.host_id), reached
   via the WebSocket messages the WebApp sends while connected to a match;
 - the bot owner (host_id=None — "system"), reached via the REST endpoints
   in app/api/routes_admin.py once they've been authorized upstream
   against settings.admin_telegram_ids and aren't necessarily even a
   player in the target game.
Every method re-checks this itself via _require_host_or_system — a raw
message/request doesn't go through any UI, so the engine is what actually
enforces "only an admin can do this", the same way kick_player and
start_game already did for the plain host_id case."""
import pytest
from app.game_engine.engine import GameEngine, EngineError
from app.game_engine.roles import RoleName as R
from app.game_engine.state import Phase
from app.game_engine.managers import PhaseManager
from tests.conftest import make_engine_with_roles


def _lobby_engine(n=6):
    eng = GameEngine(game_id="g1", host_telegram_id=1, host_name="Host")
    for i in range(2, n + 1):
        eng.add_player(telegram_user_id=i, display_name=f"P{i}")
    return eng


# ---------- update_settings ----------

def test_non_host_cannot_update_settings():
    eng = _lobby_engine()
    other = next(pid for pid in eng.state.players if pid != eng.state.host_id)
    with pytest.raises(EngineError):
        eng.update_settings(other, {"night_duration_s": 30})


def test_host_can_update_settings_in_lobby():
    eng = _lobby_engine()
    eng.update_settings(eng.state.host_id, {
        "night_duration_s": 30, "day_duration_s": 120, "voting_duration_s": 45,
        "tie_rule": "random", "allow_self_vote": True,
        "reveal_role_on_death": False, "anonymous_voting": True,
    })
    s = eng.state.settings
    assert (s.night_duration_s, s.day_duration_s, s.voting_duration_s) == (30, 120, 45)
    assert s.tie_rule == "random"
    assert s.allow_self_vote is True
    assert s.reveal_role_on_death is False
    assert s.anonymous_voting is True


def test_settings_cannot_change_after_game_starts():
    eng, _ = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                      R.CITIZEN, R.CITIZEN])
    with pytest.raises(EngineError):
        eng.update_settings(eng.state.host_id, {"night_duration_s": 30})


def test_settings_reject_out_of_bounds_duration():
    eng = _lobby_engine()
    with pytest.raises(EngineError):
        eng.update_settings(eng.state.host_id, {"night_duration_s": 5})
    with pytest.raises(EngineError):
        eng.update_settings(eng.state.host_id, {"day_duration_s": 9999})


def test_settings_reject_invalid_tie_rule():
    eng = _lobby_engine()
    with pytest.raises(EngineError):
        eng.update_settings(eng.state.host_id, {"tie_rule": "coin_flip"})


def test_settings_reject_unknown_key():
    eng = _lobby_engine()
    with pytest.raises(EngineError):
        eng.update_settings(eng.state.host_id, {"max_charges": 99})


# ---------- force_advance_phase ----------

def test_non_host_cannot_force_advance():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    other = next(pid for pid in ids.values() if pid != eng.state.host_id)
    with pytest.raises(EngineError):
        eng.force_advance_phase(other)


def test_force_advance_resolves_night_immediately():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    assert eng.state.phase == Phase.NIGHT
    assert eng.force_advance_phase(eng.state.host_id) is True
    assert eng.state.phase == Phase.DAY_DISCUSSION


def test_force_advance_moves_discussion_to_voting():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    PhaseManager.to_day(eng.state)
    assert eng.force_advance_phase(eng.state.host_id) is True
    assert eng.state.phase == Phase.VOTING


def test_force_advance_raises_when_nothing_to_advance():
    eng = _lobby_engine()
    with pytest.raises(EngineError):
        eng.force_advance_phase(eng.state.host_id)


# ---------- extend_current_phase ----------

def test_non_host_cannot_extend_timer():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    other = next(pid for pid in ids.values() if pid != eng.state.host_id)
    with pytest.raises(EngineError):
        eng.extend_current_phase(other, 30)


def test_extend_timer_adds_seconds_to_phase_end():
    eng, _ = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                      R.CITIZEN, R.CITIZEN])
    before = eng.state.phase_end
    eng.extend_current_phase(eng.state.host_id, 30)
    assert eng.state.phase_end == pytest.approx(before + 30, abs=0.5)


def test_extend_timer_rejects_out_of_range_values():
    eng, _ = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                      R.CITIZEN, R.CITIZEN])
    with pytest.raises(EngineError):
        eng.extend_current_phase(eng.state.host_id, 1)
    with pytest.raises(EngineError):
        eng.extend_current_phase(eng.state.host_id, 1000)


def test_extend_timer_rejected_in_lobby():
    eng = _lobby_engine()
    with pytest.raises(EngineError):
        eng.extend_current_phase(eng.state.host_id, 30)


# ---------- admin_remove_player ----------

def test_non_host_cannot_remove_player():
    eng = _lobby_engine()
    ids = list(eng.state.players.keys())
    other, target = [pid for pid in ids if pid != eng.state.host_id][:2]
    with pytest.raises(EngineError):
        eng.admin_remove_player(other, target)


def test_host_cannot_remove_themselves():
    eng = _lobby_engine()
    with pytest.raises(EngineError):
        eng.admin_remove_player(eng.state.host_id, eng.state.host_id)


def test_admin_remove_in_lobby_kicks_outright():
    eng = _lobby_engine()
    target = next(pid for pid in eng.state.players if pid != eng.state.host_id)
    eng.admin_remove_player(eng.state.host_id, target)
    assert target not in eng.state.players


def test_admin_remove_mid_game_eliminates_target():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    target = ids["P1"]
    eng.admin_remove_player(eng.state.host_id, target)
    assert eng.state.players[target].alive is False
    assert eng.state.players[target].death_reason == "removed_by_admin"
    # still a player of the match — role/stats aren't erased, unlike a lobby kick
    assert target in eng.state.players


def test_admin_remove_mid_game_can_end_the_game():
    """Removing the last Mafia mid-game should trigger the same win check
    any other elimination does. Host (P0 by conftest's construction) is
    kept as a Citizen here so the target being removed isn't the host."""
    eng, ids = make_engine_with_roles([R.CITIZEN, R.MAFIOSO, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    eng.admin_remove_player(eng.state.host_id, ids["P1"])  # P1 is the lone Mafioso
    assert eng.state.phase == Phase.GAME_OVER


def test_cannot_remove_already_eliminated_player():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    eng.state.players[ids["P1"]].alive = False
    with pytest.raises(EngineError):
        eng.admin_remove_player(eng.state.host_id, ids["P1"])


# ---------- get_player_view admin block ----------

def test_admin_block_only_visible_to_host():
    eng = _lobby_engine()
    other = next(pid for pid in eng.state.players if pid != eng.state.host_id)
    host_view = eng.get_player_view(eng.state.host_id)
    other_view = eng.get_player_view(other)
    assert "admin" in host_view
    assert "admin" not in other_view


def test_admin_block_reports_night_action_progress():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.COMMISSIONER, R.DOCTOR, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    eng.submit_night_action(ids["P0"], ids["P3"])
    view = eng.get_player_view(eng.state.host_id)
    assert view["admin"]["night_actions_submitted"] == 1
    assert view["admin"]["night_actions_expected"] == 3  # Mafioso, Commissioner, Doctor


# ---------- system caller (host_id=None — the bot owner's global panel) ----------
# These mirror the host_id-required tests above, but exercise the path
# app/api/routes_admin.py actually uses: no per-match player identity at
# all, authorization already having happened one layer up.

def test_system_caller_can_update_settings_regardless_of_who_is_host():
    eng = _lobby_engine()
    eng.update_settings(None, {"night_duration_s": 20})
    assert eng.state.settings.night_duration_s == 20


def test_system_caller_can_force_advance():
    eng, _ = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                      R.CITIZEN, R.CITIZEN])
    assert eng.force_advance_phase(None) is True
    assert eng.state.phase == Phase.DAY_DISCUSSION


def test_system_caller_can_extend_timer():
    eng, _ = make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                      R.CITIZEN, R.CITIZEN])
    before = eng.state.phase_end
    eng.extend_current_phase(None, 30)
    assert eng.state.phase_end == pytest.approx(before + 30, abs=0.5)


def test_system_caller_can_remove_any_player_including_the_host():
    eng, ids = make_engine_with_roles([R.CITIZEN, R.MAFIOSO, R.CITIZEN, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    # P0 is host here (conftest's construction) — a per-match host could
    # never remove themselves, but the bot owner isn't bound by that.
    eng.admin_remove_player(None, ids["P0"])
    assert eng.state.players[ids["P0"]].alive is False
    assert eng.state.players[ids["P0"]].death_reason == "removed_by_admin"


def test_system_caller_lobby_kick_works_without_a_real_host_id():
    eng = _lobby_engine()
    target = next(pid for pid in eng.state.players if pid != eng.state.host_id)
    eng.admin_remove_player(None, target)
    assert target not in eng.state.players
