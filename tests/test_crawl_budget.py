"""Budget mechanism and the outcome contract. No browser, no LLM, no clock sleeping."""
import pytest

from autoe2e.crawler.budget import (
    BUDGET_EXHAUSTED, COMPLETED, FAILED, INTERRUPTED, INTERRUPTED_REASON,
    MAX_ACTIONS, MAX_STATES, MAX_WALL_SECONDS,
    CrawlBudget, classify_outcome,
)
from autoe2e.crawler.config import Config


class FakeClock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


def test_unlimited_never_triggers():
    b = CrawlBudget()
    assert b.is_limited is False
    assert b.exceeded(10_000, 10_000) is None


@pytest.mark.parametrize('limit,actions,states,expected', [
    (dict(max_actions=3), 2, 0, None),
    (dict(max_actions=3), 3, 0, MAX_ACTIONS),
    (dict(max_actions=3), 4, 0, MAX_ACTIONS),
    (dict(max_states=2), 0, 1, None),
    (dict(max_states=2), 0, 2, MAX_STATES),
])
def test_count_limits_are_inclusive(limit, actions, states, expected):
    """Inclusive, so a run never overshoots a declared budget."""
    assert CrawlBudget(**limit).exceeded(actions, states) == expected


def test_wall_clock_limit_uses_injected_clock():
    clock = FakeClock(1000.0)
    b = CrawlBudget(max_wall_seconds=30, clock=clock)
    assert b.exceeded(0, 0) is None
    clock.now = 1029.9
    assert b.exceeded(0, 0) is None
    clock.now = 1030.0
    assert b.exceeded(0, 0) == MAX_WALL_SECONDS
    assert b.elapsed() == pytest.approx(30.0)


def test_any_configured_limit_stops_the_run():
    b = CrawlBudget(max_actions=100, max_states=2, max_wall_seconds=10_000)
    assert b.exceeded(1, 2) == MAX_STATES


def test_action_limit_reported_before_state_limit_when_both_reached():
    """Deterministic precedence, so `budget_triggered` is reproducible."""
    b = CrawlBudget(max_actions=1, max_states=1)
    assert b.exceeded(5, 5) == MAX_ACTIONS


def test_from_config_reads_the_crawl_section():
    cfg = Config.from_dict({
        'driver': {'base_url': 'http://x/'},
        'crawl': {'max_actions': 7, 'max_states': 8, 'max_wall_seconds': 9},
    })
    b = CrawlBudget.from_config(cfg)
    assert b.describe() == {'max_actions': 7, 'max_states': 8, 'max_wall_seconds': 9.0}


def test_omitted_crawl_section_is_unlimited_for_backward_compatibility():
    cfg = Config.from_dict({'driver': {'base_url': 'http://x/'}})
    assert CrawlBudget.from_config(cfg).is_limited is False


@pytest.mark.parametrize('value', [0, -1])
def test_non_positive_limits_are_rejected(value):
    with pytest.raises(ValueError):
        Config.from_dict({'crawl': {'max_actions': value}})


@pytest.mark.parametrize('reason,requested,error,status,code', [
    (None,             False, None,    COMPLETED,        0),
    (MAX_ACTIONS,      False, None,    BUDGET_EXHAUSTED, 0),
    (MAX_STATES,       False, None,    BUDGET_EXHAUSTED, 0),
    (MAX_WALL_SECONDS, False, None,    BUDGET_EXHAUSTED, 0),
    (INTERRUPTED_REASON, False, None,  INTERRUPTED,      130),
    (None,             True,  None,    INTERRUPTED,      130),
    (None,             False, 'boom',  FAILED,           1),
    (MAX_ACTIONS,      False, 'boom',  FAILED,           1),
])
def test_outcome_classification(reason, requested, error, status, code):
    assert classify_outcome(reason, requested, error) == (status, code)


def test_budget_exhaustion_is_a_successful_exit():
    """A declared stopping rule is not an error."""
    status, code = classify_outcome(MAX_WALL_SECONDS)
    assert status == BUDGET_EXHAUSTED and code == 0
