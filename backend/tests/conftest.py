import pytest

from app.game_engine.engine import GameEngine
from app.game_engine.managers import PhaseManager
from app.game_engine.state import Phase


@pytest.fixture(autouse=True)
def _default_allow_group_membership(monkeypatch):
    """/games/for-chat now calls Telegram's real Bot API to confirm chat
    membership (see app/services/telegram_bot_api.py). The whole point of
    this test suite is to run fast and offline, so by default every test
    gets a stand-in that says "yes, they're a member" — this is what all
    the existing lobby/night/vote/etc. tests implicitly rely on. Tests that
    specifically exercise the membership check itself (test_chat_membership.py)
    install their own monkeypatch inside the test, which simply overrides
    this one for that test."""
    from app.api import routes_game as routes_game_module

    async def _always_a_member(chat_id, telegram_user_id):
        return True

    monkeypatch.setattr(routes_game_module, "verify_group_membership", _always_a_member)


def make_engine_with_roles(role_list):
    """Build a GameEngine with an exact, deterministic role assignment
    (bypassing the random RoleManager) so night-resolution logic can be
    tested precisely. Returns (engine, {display_name: player_id})."""
    eng = GameEngine(game_id="test-game", host_telegram_id=1, host_name="P0")
    for i in range(1, len(role_list)):
        eng.add_player(telegram_user_id=100 + i, display_name=f"P{i}")
    ids = {}
    for (name, p), role in zip(eng.state.players.items(), role_list):
        eng.state.players[name].role = role
        ids[eng.state.players[name].display_name] = name
    eng.state.phase = Phase.LOBBY
    PhaseManager.to_night(eng.state)
    return eng, ids
