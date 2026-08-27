"""Discussion chat (spec sections 11/32) and final reveal + personal
statistics (spec section 22). The Telegram group is never involved in any
of this — it's all inside GameState, scoped to one game."""
import pytest
from app.game_engine.roles import RoleName as R
from app.game_engine.engine import GameEngine, EngineError
from app.game_engine.state import Phase
from tests.conftest import make_engine_with_roles


def _to_discussion(eng):
    """Helper: push a freshly-built engine straight into DAY_DISCUSSION
    with no deaths, so chat tests don't need to care about night resolution."""
    from app.game_engine.managers import PhaseManager
    PhaseManager.to_day(eng.state)


def test_alive_player_can_send_and_everyone_sees_it():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.COMMISSIONER, R.DOCTOR, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    _to_discussion(eng)
    eng.send_chat_message(ids["P1"], "Menimcha Mafioso shubhali")
    view = eng.get_player_view(ids["P2"])
    assert len(view["chat"]) == 1
    assert view["chat"][0]["text"] == "Menimcha Mafioso shubhali"
    assert view["chat"][0]["display_name"] == "P1"


def test_dead_player_cannot_send_but_still_sees_chat():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.COMMISSIONER, R.DOCTOR, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    _to_discussion(eng)
    eng.send_chat_message(ids["P1"], "salom")
    eng.state.players[ids["P2"]].alive = False
    with pytest.raises(EngineError):
        eng.send_chat_message(ids["P2"], "men o'lganman lekin yozaman")
    # still visible to the dead player as a spectator
    view = eng.get_player_view(ids["P2"])
    assert len(view["chat"]) == 1


def test_silenced_player_cannot_send_that_day():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.COMMISSIONER, R.DOCTOR, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    _to_discussion(eng)
    eng.state.players[ids["P2"]].silenced = True
    with pytest.raises(EngineError):
        eng.send_chat_message(ids["P2"], "sukut qilinganman")


def test_chat_only_open_during_discussion_phase():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.COMMISSIONER, R.DOCTOR, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    # engine starts in NIGHT (conftest's make_engine_with_roles ends with to_night)
    with pytest.raises(EngineError):
        eng.send_chat_message(ids["P1"], "tunda yozmoqchiman")


def test_empty_message_rejected():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.COMMISSIONER, R.DOCTOR, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    _to_discussion(eng)
    with pytest.raises(EngineError):
        eng.send_chat_message(ids["P1"], "   ")


def test_chat_history_is_capped():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.COMMISSIONER, R.DOCTOR, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    _to_discussion(eng)
    for i in range(250):
        eng.send_chat_message(ids["P1"], f"msg {i}")
    view = eng.get_player_view(ids["P1"])
    assert len(view["chat"]) == 200
    assert view["chat"][-1]["text"] == "msg 249"  # oldest trimmed, newest kept


def test_final_role_reveal_shows_everyone_once_game_is_over():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.COMMISSIONER, R.DOCTOR, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    # Kill off the lone mafia directly to force a clean town win.
    eng.state.players[ids["P0"]].alive = False
    from app.game_engine.managers import WinConditionManager, PhaseManager
    win = WinConditionManager.check(eng.state)
    assert win is not None
    PhaseManager.to_game_over(eng.state, win)

    # A player who is neither dead nor the viewer would normally have a
    # hidden role — but not anymore, because the game is over.
    view = eng.get_player_view(ids["P3"])  # P3 is an alive Citizen
    roles_by_name = {p["display_name"]: p["role"] for p in view["players"]}
    assert roles_by_name["P1"] == "Commissioner"
    assert roles_by_name["P2"] == "Doctor"
    assert roles_by_name["P0"] == "Mafioso"


def test_personal_stats_present_only_at_game_over():
    eng, ids = make_engine_with_roles([R.MAFIOSO, R.COMMISSIONER, R.DOCTOR, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    mid_game_view = eng.get_player_view(ids["P1"])
    assert "stats" not in mid_game_view["me"]

    eng.state.players[ids["P0"]].alive = False
    from app.game_engine.managers import WinConditionManager, PhaseManager
    win = WinConditionManager.check(eng.state)
    PhaseManager.to_game_over(eng.state, win)
    end_view = eng.get_player_view(ids["P1"])
    stats = end_view["me"]["stats"]
    assert stats["role"] == "Commissioner"
    assert stats["won"] is True
    assert "investigations" in stats and "kills" in stats and "votes_cast" in stats


@pytest.mark.asyncio
async def test_investigation_and_vote_counters_increment():
    eng = GameEngine(game_id="g1", host_telegram_id=1, host_name="Host")
    for i in range(2, 7):
        eng.add_player(telegram_user_id=i, display_name=f"P{i}")
    eng.start_game(eng.state.host_id)
    commissioner_id = next(pid for pid, p in eng.state.players.items() if p.role == R.COMMISSIONER)
    other = next(pid for pid in eng.state.players if pid != commissioner_id)
    eng.submit_night_action(commissioner_id, other)
    assert eng.state.players[commissioner_id].investigations == 1

    eng.resolve_night_if_ready(force=True)
    assert eng.state.phase == Phase.DAY_DISCUSSION
    eng.advance_to_voting()
    alive_ids = list(eng.state.players.keys())
    eng.submit_vote(alive_ids[0], alive_ids[1])
    assert eng.state.players[alive_ids[0]].votes_cast == 1
    eng.submit_vote(alive_ids[2], None)  # abstain must NOT count as a cast vote
    assert eng.state.players[alive_ids[2]].votes_cast == 0


def test_mafia_kill_is_credited_to_the_deciding_voter():
    eng, ids = make_engine_with_roles([R.DON, R.COMMISSIONER, R.DOCTOR, R.CITIZEN,
                                        R.CITIZEN, R.CITIZEN])
    eng.submit_night_action(ids["P0"], ids["P3"])  # Don kills P3
    eng.resolve_night_if_ready(force=True)
    assert eng.state.players[ids["P0"]].kills == 1
