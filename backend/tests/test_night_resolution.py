from app.game_engine.roles import RoleName as R
from tests.conftest import make_engine_with_roles


def test_mafia_kill_with_no_protection_kills_target():
    eng, ids = make_engine_with_roles([
        R.MAFIOSO, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P3"])  # mafioso kills P3 (citizen)
    ok = eng.resolve_night_if_ready(force=True)
    assert ok
    assert eng.state.players[ids["P3"]].alive is False
    assert eng.state.players[ids["P3"]].death_reason == "mafia"


def test_doctor_protects_target_from_mafia_kill():
    eng, ids = make_engine_with_roles([
        R.MAFIOSO, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P3"])   # mafioso -> P3
    eng.submit_night_action(ids["P2"], ids["P3"])   # doctor protects P3
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P3"]].alive is True


def test_doctor_cannot_self_heal_two_nights_in_a_row():
    eng, ids = make_engine_with_roles([
        R.MAFIOSO, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    # Night 1: doctor self-heals while mafia targets someone else — allowed.
    eng.submit_night_action(ids["P0"], ids["P3"])
    eng.submit_night_action(ids["P2"], ids["P2"])
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P2"]].alive is True

    # Night 2: mafia now targets the doctor; self-heal again should fizzle.
    from app.game_engine.managers import PhaseManager
    PhaseManager.to_night(eng.state)
    eng.submit_night_action(ids["P0"], ids["P2"])
    eng.submit_night_action(ids["P2"], ids["P2"])
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P2"]].alive is False


def test_doctor_can_self_heal_again_after_skipping_a_night():
    eng, ids = make_engine_with_roles([
        R.MAFIOSO, R.COMMISSIONER, R.DOCTOR, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    doc = eng.state.players[ids["P2"]]
    doc.last_self_heal_night = eng.state.night_number - 2  # healed two nights ago, not last night
    eng.submit_night_action(ids["P0"], ids["P2"])   # mafia -> doctor
    eng.submit_night_action(ids["P2"], ids["P2"])   # doctor self-heals again
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P2"]].alive is True


def test_framer_makes_commissioner_read_target_as_mafia():
    eng, ids = make_engine_with_roles([
        R.MAFIOSO, R.FRAMER, R.COMMISSIONER, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P1"], ids["P3"])   # framer frames P3
    eng.submit_night_action(ids["P2"], ids["P3"])   # commissioner investigates P3
    eng.resolve_night_if_ready(force=True)
    result = eng.get_player_view(ids["P2"])["me"]["night_result"]
    assert result["verdict"] == "mafia"


def test_commissioner_gets_clean_read_on_don():
    eng, ids = make_engine_with_roles([
        R.DON, R.MAFIOSO, R.COMMISSIONER, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P2"], ids["P0"])  # commissioner investigates Don
    eng.submit_night_action(ids["P1"], ids["P3"])  # mafioso needs to vote too (don doesn't auto-kill)
    eng.resolve_night_if_ready(force=True)
    result = eng.get_player_view(ids["P2"])["me"]["night_result"]
    assert result["verdict"] == "not_mafia"


def test_bodyguard_intercepts_lone_mafia_attacker_both_die_target_saved():
    eng, ids = make_engine_with_roles([
        R.MAFIOSO, R.BODYGUARD, R.CITIZEN, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P2"])   # mafioso -> citizen P2
    eng.submit_night_action(ids["P1"], ids["P2"])   # bodyguard guards P2
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P2"]].alive is True     # saved
    assert eng.state.players[ids["P1"]].alive is False    # bodyguard died
    assert eng.state.players[ids["P0"]].alive is False    # lone attacker traded


def test_consigliere_gets_exact_role_investigator_gets_group():
    eng, ids = make_engine_with_roles([
        R.MAFIOSO, R.CONSIGLIERE, R.INVESTIGATOR, R.DOCTOR, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P4"])
    eng.submit_night_action(ids["P1"], ids["P3"])   # consigliere -> doctor
    eng.submit_night_action(ids["P2"], ids["P3"])   # investigator -> doctor
    eng.resolve_night_if_ready(force=True)
    consig_result = eng.get_player_view(ids["P1"])["me"]["night_result"]
    inv_result = eng.get_player_view(ids["P2"])["me"]["night_result"]
    assert consig_result["exact_role"] == "Doctor"
    assert "Doctor" in inv_result["possible_roles"]
    assert len(inv_result["possible_roles"]) >= 2


def test_tracker_and_watcher():
    eng, ids = make_engine_with_roles([
        R.MAFIOSO, R.TRACKER, R.WATCHER, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P3"])   # mafioso visits P3
    eng.submit_night_action(ids["P1"], ids["P0"])   # tracker tracks mafioso
    eng.submit_night_action(ids["P2"], ids["P3"])   # watcher watches P3
    eng.resolve_night_if_ready(force=True)
    tracker_result = eng.get_player_view(ids["P1"])["me"]["night_result"]
    watcher_result = eng.get_player_view(ids["P2"])["me"]["night_result"]
    assert tracker_result["visited"] == ids["P3"]
    assert ids["P0"] in watcher_result["visitors"]


def test_serial_killer_kills_independently_of_mafia():
    eng, ids = make_engine_with_roles([
        R.MAFIOSO, R.SERIAL_KILLER, R.CITIZEN, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P2"])
    eng.submit_night_action(ids["P1"], ids["P3"])
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P2"]].alive is False
    assert eng.state.players[ids["P3"]].alive is False


def test_veteran_alert_kills_visitor():
    eng, ids = make_engine_with_roles([
        R.MAFIOSO, R.VETERAN, R.CITIZEN, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P1"])   # mafioso visits veteran (mistake!)
    eng.submit_night_action(ids["P1"], None)         # veteran goes on alert (no target needed)
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P0"]].alive is False


def test_arsonist_douse_then_ignite_kills_all_doused():
    eng, ids = make_engine_with_roles([
        R.ARSONIST, R.CITIZEN, R.CITIZEN, R.CITIZEN, R.CITIZEN,
        R.CITIZEN, R.CITIZEN, R.CITIZEN,
    ])
    eng.submit_night_action(ids["P0"], ids["P1"])   # night 1: douse P1
    eng.resolve_night_if_ready(force=True)
    # night 2: ignite (no target needed)
    from app.game_engine.managers import PhaseManager
    from app.game_engine.state import Phase
    eng.state.phase = Phase.DAY_DISCUSSION
    PhaseManager.to_night(eng.state)
    eng.state.night_actions.clear()
    from app.game_engine.state import NightAction
    from app.game_engine.roles import ActionType
    eng.state.night_actions[ids["P0"]] = NightAction(
        player_id=ids["P0"], role=R.ARSONIST, action_type=ActionType.IGNITE, target_id=None)
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P1"]].alive is False
