"""Crawl budget evaluation.

Deliberately knows nothing about crawling: it is handed counters and answers whether a limit
has been reached. The exploration algorithm is untouched -- main.py asks this class after each
action and stops scheduling new work when it says so.

The clock is injectable so wall-clock behaviour is unit-testable without sleeping.
"""
from __future__ import annotations

import time
from typing import Callable

# Reported in status as `budget_triggered`.
MAX_ACTIONS = 'max_actions'
MAX_STATES = 'max_states'
MAX_WALL_SECONDS = 'max_wall_seconds'

BUDGET_REASONS = (MAX_ACTIONS, MAX_STATES, MAX_WALL_SECONDS)

# Terminal run statuses, written to tmp/status_<APP>.json.
COMPLETED = 'completed'
BUDGET_EXHAUSTED = 'budget_exhausted'
INTERRUPTED = 'interrupted'
FAILED = 'failed'

INTERRUPTED_REASON = 'interrupted'


def classify_outcome(stop_reason=None, stop_requested=False, error=None):
    """Map how a run ended onto (status, exit_code). Pure, so the contract is testable.

    Reaching a declared budget is a successful outcome, not an error: the limit is a stopping
    rule the experiment asked for, so it exits 0 with everything produced so far preserved.
    An interruption exits 130 by convention; a genuine failure exits 1.
    """
    if error is not None:
        return FAILED, 1
    if stop_reason in BUDGET_REASONS:
        return BUDGET_EXHAUSTED, 0
    if stop_requested or stop_reason == INTERRUPTED_REASON:
        return INTERRUPTED, 130
    return COMPLETED, 0


class CrawlBudget:
    def __init__(
        self,
        max_actions: int | None = None,
        max_states: int | None = None,
        max_wall_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_actions = max_actions
        self.max_states = max_states
        self.max_wall_seconds = max_wall_seconds
        self._clock = clock
        self._started_at = clock()

    @classmethod
    def from_config(cls, config, clock: Callable[[], float] = time.monotonic) -> 'CrawlBudget':
        return cls(
            max_actions=getattr(config, 'max_actions', None),
            max_states=getattr(config, 'max_states', None),
            max_wall_seconds=getattr(config, 'max_wall_seconds', None),
            clock=clock,
        )

    @property
    def is_limited(self) -> bool:
        return any(v is not None for v in
                   (self.max_actions, self.max_states, self.max_wall_seconds))

    def elapsed(self) -> float:
        return self._clock() - self._started_at

    def exceeded(self, actions_executed: int, states_discovered: int) -> str | None:
        """Return the name of the first limit reached, or None.

        Limits are inclusive: max_actions=10 stops once 10 actions have been executed, so a run
        never exceeds a declared budget.
        """
        if self.max_actions is not None and actions_executed >= self.max_actions:
            return MAX_ACTIONS
        if self.max_states is not None and states_discovered >= self.max_states:
            return MAX_STATES
        if self.max_wall_seconds is not None and self.elapsed() >= self.max_wall_seconds:
            return MAX_WALL_SECONDS
        return None

    def describe(self) -> dict:
        return {
            'max_actions': self.max_actions,
            'max_states': self.max_states,
            'max_wall_seconds': self.max_wall_seconds,
        }
