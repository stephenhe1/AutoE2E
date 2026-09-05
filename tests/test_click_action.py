"""ClickAction must report failure to its caller, never terminate the crawl.

Before: on TimeoutException, ClickAction.execute called driver.quit() then sys.exit(1). One
stale or unlocatable control ended the whole run -- confirmed to have killed EPIC_STACK at
action 3 and BANGLE_IO at action 10, both at click_action.py:35.
"""
from pathlib import Path

import pytest
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
    TimeoutException,
)

from autoe2e.crawler.action import ActionExecutionError, ClickAction

ROOT = Path(__file__).resolve().parent.parent


class FakeElement:
    """Stands in for autoe2e Element; get() raises whatever the test asks for."""

    def __init__(self, raises=None, element_id='el-1'):
        self._raises = raises
        self._id = element_id
        self.outerHTML = '<button>go</button>'
        self.test_id = None

    def get(self, driver):
        if self._raises is not None:
            raise self._raises
        return object()

    def get_id(self):
        return self._id


class FakeDriver:
    def __init__(self):
        self.quit_called = False
        self.current_url = 'http://example.test/page'
        self.scripts = []

    def quit(self):
        self.quit_called = True

    def execute_script(self, *a, **k):
        self.scripts.append(a)


class FakeActionChains:
    """ActionChains needs a real WebDriver; the click path itself is not what we are testing."""
    performed = []

    def __init__(self, driver):
        self._driver = driver

    def move_to_element(self, el):
        return self

    def click(self, el):
        return self

    def perform(self):
        FakeActionChains.performed.append(self._driver)


@pytest.fixture
def no_real_actionchains(monkeypatch):
    import autoe2e.crawler.action.click_action as mod
    FakeActionChains.performed = []
    monkeypatch.setattr(mod, 'ActionChains', FakeActionChains)
    return FakeActionChains


def make_action(exc, state='state-abc'):
    a = ClickAction(FakeElement(raises=exc))
    a.set_parent_state_id(state)
    return a


def test_timeout_raises_action_execution_error_not_systemexit():
    driver = FakeDriver()
    action = make_action(TimeoutException('no such element'))
    with pytest.raises(ActionExecutionError):
        action.execute(driver)


def test_timeout_does_not_raise_systemexit():
    """SystemExit would propagate past `except Exception` and abort the runner."""
    driver = FakeDriver()
    action = make_action(TimeoutException('nope'))
    try:
        action.execute(driver)
    except ActionExecutionError:
        pass
    except SystemExit:  # pragma: no cover
        pytest.fail('ClickAction raised SystemExit; it must not terminate the process')


def test_click_action_does_not_close_the_browser():
    """Global teardown belongs to the runner's finally block, not to an action."""
    driver = FakeDriver()
    action = make_action(TimeoutException('nope'))
    with pytest.raises(ActionExecutionError):
        action.execute(driver)
    assert driver.quit_called is False


@pytest.mark.parametrize('exc', [
    TimeoutException('timed out'),
    StaleElementReferenceException('stale'),
    ElementClickInterceptedException('intercepted'),
])
def test_selenium_failures_are_surfaced_uniformly(exc):
    driver = FakeDriver()
    action = make_action(exc)
    with pytest.raises(ActionExecutionError):
        action.execute(driver)
    assert driver.quit_called is False


def test_failure_carries_diagnostics():
    driver = FakeDriver()
    action = make_action(TimeoutException('boom'), state='state-xyz')
    with pytest.raises(ActionExecutionError) as ei:
        action.execute(driver)
    d = ei.value.as_dict()
    assert d['action_id'] == 'el-1'
    assert d['action_type'] == 'click'
    assert d['parent_state_id'] == 'state-xyz'
    assert d['cause_type'] == 'TimeoutException'
    assert d['url'] == 'http://example.test/page'
    assert d['reason']


def test_successful_click_still_works(no_real_actionchains):
    driver = FakeDriver()
    action = ClickAction(FakeElement(raises=None))
    action.execute(driver)          # must not raise
    assert driver.quit_called is False
    assert driver.scripts, 'scrollIntoView should have been executed'


def test_exploration_continues_past_a_failed_action(no_real_actionchains):
    """The caller's contract: one failed action is skipped, later actions still run."""
    driver = FakeDriver()
    actions = [
        ClickAction(FakeElement(raises=TimeoutException('a'), element_id='bad-1')),
        ClickAction(FakeElement(raises=None, element_id='good-1')),
        ClickAction(FakeElement(raises=TimeoutException('c'), element_id='bad-2')),
        ClickAction(FakeElement(raises=None, element_id='good-2')),
    ]
    executed, failures = [], []
    for a in actions:
        try:
            a.execute(driver)
            executed.append(a.get_id())
        except ActionExecutionError as e:
            failures.append(e.as_dict()['action_id'])
    assert executed == ['good-1', 'good-2']
    assert failures == ['bad-1', 'bad-2']
    assert driver.quit_called is False


def test_runner_skips_transition_handling_on_failure():
    """main.py is a script, so the wiring is asserted on source.

    A failed click must not be recorded as a transition: no state is created or enqueued, and
    functionality is not attributed to it.
    """
    src = (ROOT / 'main.py').read_text()
    assert 'except ActionExecutionError as action_err' in src
    assert 'ACTION_FAILURES.append' in src
    # the transition block is gated on there having been no execution error
    assert 'if execution_error is None:' in src
    gate = src.index('if execution_error is None:')
    for marker in ('crawl_queue.enqueue(new_state)', 'add_state_from_current_state'):
        assert src.index(marker) > gate, f'{marker} must be inside the no-error branch'


def test_click_action_source_has_no_process_or_browser_teardown():
    src = (ROOT / 'autoe2e' / 'crawler' / 'action' / 'click_action.py').read_text()
    assert 'sys.exit' not in src
    assert 'driver.quit' not in src
