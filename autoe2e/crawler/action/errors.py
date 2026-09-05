"""Action-level execution failures.

Why this exists
---------------
There was no failure-surfacing convention to reuse. The two implementations disagreed:

    FormAction.execute   caught Exception, logged a warning and returned -- the caller could
                         not tell success from failure, so a failed form fill was
                         indistinguishable from a completed one.
    ClickAction.execute  caught TimeoutException and called driver.quit(); sys.exit(1) --
                         one unlocatable control terminated the entire crawl. Confirmed to
                         have killed EPIC_STACK (at action 3) and BANGLE_IO (at action 10).

Neither is usable: one is silent, the other is fatal. This exception is the explicit
middle ground -- the failure reaches the caller, which decides whether exploration can
continue, and an action never owns global browser teardown.
"""
from __future__ import annotations


class ActionExecutionError(Exception):
    """One action could not be executed. The crawl may still be able to continue.

    Carries enough context to identify the failure without re-reading the log: which action,
    what kind of failure, and which state it was attempted from.
    """

    def __init__(self, action, reason: str, cause: BaseException | None = None,
                 url: str | None = None):
        self.action_id = None
        self.action_type = None
        self.parent_state_id = None
        try:
            self.action_id = action.get_id()
            self.action_type = action.get_type().get_value()
            self.parent_state_id = action.get_parent_state_id()
        except Exception:  # noqa: BLE001 - diagnostics must never mask the original failure
            pass
        self.reason = reason
        self.cause = cause
        self.cause_type = type(cause).__name__ if cause is not None else None
        self.url = url
        super().__init__(str(self))

    def __str__(self) -> str:
        return (f"action {self.action_type}:{self.action_id} failed from state "
                f"{self.parent_state_id}: {self.reason}"
                + (f" ({self.cause_type})" if self.cause_type else "")
                + (f" at {self.url}" if self.url else ""))

    def as_dict(self) -> dict:
        return {
            'action_id': self.action_id,
            'action_type': self.action_type,
            'parent_state_id': self.parent_state_id,
            'reason': self.reason,
            'cause_type': self.cause_type,
            'url': self.url,
        }
