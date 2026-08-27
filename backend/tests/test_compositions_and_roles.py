import random
from app.game_engine.compositions import validate_all_compositions, get_composition, COMPOSITIONS
from app.game_engine.engine import GameEngine
from app.game_engine.roles import ROLES


def test_all_compositions_are_internally_consistent():
    validate_all_compositions()


def test_all_player_counts_6_to_25_have_compositions():
    for n in range(6, 26):
        assert n in COMPOSITIONS, f"Missing composition for {n} players"
        assert len(get_composition(n)) == n, f"Composition for {n} has wrong size"


def _make_engine(n_players: int) -> GameEngine:
    eng = GameEngine(game_id="g1", host_telegram_id=1, host_name="Host")
    for i in range(2, n_players + 1):
        eng.add_player(telegram_user_id=i, display_name=f"P{i}")
    return eng


def test_role_assignment_gives_every_player_exactly_one_role_no_illegal_dupes():
    for n in (6, 8, 12, 15, 20, 25):
        eng = _make_engine(n)
        # 25 players now auto-starts as the 25th joins (see test below);
        # only call start_game manually when that didn't already happen.
        if eng.state.phase.value == "lobby":
            eng.start_game(eng.state.host_id)
        roles_assigned = [p.role for p in eng.state.players.values()]
        assert len(roles_assigned) == n
        assert all(r is not None for r in roles_assigned)
        seen_unique = set()
        for r in roles_assigned:
            if ROLES[r].unique:
                assert r not in seen_unique
                seen_unique.add(r)


def test_six_player_classic_mini_composition():
    eng = _make_engine(6)
    eng.start_game(eng.state.host_id)
    roles_assigned = sorted(p.role.value for p in eng.state.players.values())
    expected = sorted(["Don", "Mafioso", "Commissioner", "Doctor", "Investigator", "Citizen"])
    assert roles_assigned == expected


def test_seven_player_composition():
    eng = _make_engine(7)
    eng.start_game(eng.state.host_id)
    roles_assigned = sorted(p.role.value for p in eng.state.players.values())
    expected = sorted(["Don", "Mafioso", "Commissioner", "Doctor", "Investigator", "Citizen", "Citizen"])
    assert roles_assigned == expected


def test_start_game_rejects_under_6():
    eng = _make_engine(5)
    try:
        eng.start_game(eng.state.host_id)
        assert False, "should have rejected 5 players"
    except Exception as e:
        assert "6" in str(e)


def test_lobby_auto_starts_the_instant_the_25th_player_joins():
    # No one has to click anything: hitting the 25-player cap starts the
    # game itself, mid-way through the add_player() call that fills it.
    eng = _make_engine(24)
    assert eng.state.phase.value == "lobby"
    eng.add_player(telegram_user_id=9000, display_name="Player25")
    assert eng.state.phase.value != "lobby"
    assert len(eng.state.players) == 25


def test_start_game_rejects_over_25():
    # _make_engine(25) already auto-started the instant its 25th player
    # joined (see test above), so a 26th is rejected because the game is
    # no longer in the lobby at all — the strongest possible form of
    # "over 25 is impossible".
    eng = _make_engine(25)
    assert eng.state.phase.value != "lobby"
    try:
        eng.add_player(telegram_user_id=9999, display_name="Extra")
        assert False, "should have rejected a 26th player"
    except Exception as e:
        assert "already started" in str(e).lower()
