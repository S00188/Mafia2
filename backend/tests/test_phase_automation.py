"""Server-side automatic phase advancement (spec items 1 & 3): every phase's
end is a real server timestamp (TimerManager), and the night -> day ->
discussion -> voting -> results -> next night loop has to keep moving on
its own even if nobody in the WebApp taps anything. Night and voting
already resolved themselves this way; these tests cover the two phases
that didn't (discussion -> voting, vote results -> next night)."""
import time
from app.game_engine.roles import RoleName as R
from app.game_engine.state import Phase
from app.game_engine.managers import PhaseManager
from tests.conftest import make_engine_with_roles


def _to_discussion(eng):
    PhaseManager.to_day(eng.state)


def _to_vote_results(eng):
    """No one votes, so nobody is eliminated and the game isn't over yet —
    lands cleanly in VOTE_RESULTS, matching what resolve_voting_if_ready
    already does in production once the voting timer runs out."""
    PhaseManager.to_day(eng.state)
    PhaseManager.to_voting(eng.state)
    eng.resolve_voting_if_ready(force=True)


def _base_engine():
    return make_engine_with_roles([R.MAFIOSO, R.CITIZEN, R.CITIZEN, R.CITIZEN,
                                    R.CITIZEN, R.CITIZEN])


def test_discussion_does_not_advance_before_timer_expires():
    eng, _ = _base_engine()
    _to_discussion(eng)
    assert eng.advance_to_voting_if_ready() is False
    assert eng.state.phase == Phase.DAY_DISCUSSION


def test_discussion_auto_advances_once_timer_expires():
    eng, _ = _base_engine()
    _to_discussion(eng)
    eng.state.phase_end = time.time() - 1  # simulate the day timer having run out
    assert eng.advance_to_voting_if_ready() is True
    assert eng.state.phase == Phase.VOTING


def test_discussion_advances_immediately_when_forced():
    """The existing manual 'Ovoz berish' button path (advance_to_voting)
    stays untouched; advance_to_voting_if_ready(force=True) is the same
    early-exit behavior, just exposed through the is_ready pattern the
    ticker uses for every other phase."""
    eng, _ = _base_engine()
    _to_discussion(eng)
    assert eng.advance_to_voting_if_ready(force=True) is True
    assert eng.state.phase == Phase.VOTING


def test_vote_results_does_not_advance_before_timer_expires():
    eng, _ = _base_engine()
    _to_vote_results(eng)
    assert eng.state.phase == Phase.VOTE_RESULTS
    assert eng.start_next_night_if_ready() is False
    assert eng.state.phase == Phase.VOTE_RESULTS


def test_vote_results_auto_advances_to_next_night_once_timer_expires():
    eng, _ = _base_engine()
    _to_vote_results(eng)
    eng.state.phase_end = time.time() - 1
    assert eng.start_next_night_if_ready() is True
    assert eng.state.phase == Phase.NIGHT
    assert eng.state.night_number == 2


def test_vote_results_advances_immediately_when_forced():
    eng, _ = _base_engine()
    _to_vote_results(eng)
    assert eng.start_next_night_if_ready(force=True) is True
    assert eng.state.phase == Phase.NIGHT


def test_full_cycle_repeats_automatically_without_any_client_action():
    """The exact loop from the spec: Night -> Day -> Discussion -> Voting ->
    Results -> next Night, driven only by the *_if_ready calls the
    background ticker makes every second — nobody clicks anything here."""
    eng, ids = _base_engine()
    assert eng.state.phase == Phase.NIGHT

    assert eng.resolve_night_if_ready(force=True) is True
    assert eng.state.phase == Phase.DAY_DISCUSSION

    eng.state.phase_end = time.time() - 1
    assert eng.advance_to_voting_if_ready() is True
    assert eng.state.phase == Phase.VOTING

    assert eng.resolve_voting_if_ready(force=True) is True
    assert eng.state.phase == Phase.VOTE_RESULTS

    eng.state.phase_end = time.time() - 1
    assert eng.start_next_night_if_ready() is True
    assert eng.state.phase == Phase.NIGHT
    assert eng.state.night_number == 2
