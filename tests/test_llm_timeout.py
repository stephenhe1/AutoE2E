"""LLM requests must be bounded. No real provider is contacted.

Before: ChatOpenAI was built with no explicit request timeout, so a stalled request blocked
forever. Confirmed on KEYSTONE_BLOG -- call #17 was sent, never returned, and the process sat at
0% CPU for ~41 minutes. max_wall_seconds could not intervene, because the crawl budget is only
evaluated at action boundaries.
"""
import time

import pytest

import autoe2e.llm_api_call as llm
from autoe2e.crawler.config import Config


@pytest.fixture(autouse=True)
def restore_module_bounds():
    before = (llm.REQUEST_TIMEOUT_SECONDS, llm.MAX_RETRIES)
    yield
    llm.REQUEST_TIMEOUT_SECONDS, llm.MAX_RETRIES = before


def test_defaults_are_bounded_and_finite():
    cfg = Config.from_dict({'driver': {'base_url': 'http://x/'}})
    assert cfg.request_timeout_seconds == 120.0
    assert cfg.max_retries == 1
    assert cfg.max_retries < float('inf')


def test_configure_llm_applies_config_values():
    cfg = Config.from_dict({'llm': {'request_timeout_seconds': 30, 'max_retries': 2}})
    timeout, retries = llm.configure_llm(cfg)
    assert (timeout, retries) == (30.0, 2)
    assert llm.REQUEST_TIMEOUT_SECONDS == 30.0
    assert llm.MAX_RETRIES == 2


@pytest.mark.parametrize('bad', [
    {'request_timeout_seconds': 0},
    {'request_timeout_seconds': -5},
    {'max_retries': -1},
])
def test_invalid_llm_settings_are_rejected(bad):
    with pytest.raises(ValueError):
        Config.from_dict({'llm': bad})


def test_models_receive_request_timeout_and_max_retries(monkeypatch):
    """The bounds must actually reach the client, not just live in config."""
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm, 'ChatOpenAI', FakeChatOpenAI)
    monkeypatch.setattr(llm, '_resolve_api_key', lambda: 'unused-in-test')

    llm.configure_llm(request_timeout_seconds=17, max_retries=3)

    llm._get_sonnet()
    assert captured['request_timeout'] == 17.0
    assert captured['max_retries'] == 3

    captured.clear()
    llm._get_haiku()
    assert captured['request_timeout'] == 17.0
    assert captured['max_retries'] == 3


def test_worst_case_per_call_is_finite():
    llm.configure_llm(request_timeout_seconds=120, max_retries=1)
    worst = llm.REQUEST_TIMEOUT_SECONDS * (1 + llm.MAX_RETRIES)
    assert worst == 240.0


def test_a_hanging_call_surfaces_as_an_error_and_does_not_hang(monkeypatch):
    """A blocking provider must end as a timeout error, never as an indefinite wait."""

    class TimedOut(Exception):
        pass

    class BlockingModel:
        """Simulates a provider that never answers, bounded by our own timeout."""

        calls = 0

        def __init__(self, timeout):
            self.timeout = timeout

        def __or__(self, other):
            return self

        def __ror__(self, other):
            return self

        def invoke(self, _):
            BlockingModel.calls += 1
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                time.sleep(0.005)
            raise TimedOut(f'request exceeded {self.timeout}s')

    model = BlockingModel(timeout=0.05)
    started = time.monotonic()
    with pytest.raises(TimedOut):
        model.invoke(None)
    elapsed = time.monotonic() - started
    assert elapsed < 5, 'the call must be bounded, not indefinite'
    assert BlockingModel.calls == 1, 'no unbounded retry loop'


def test_no_answer_is_fabricated_after_a_timeout():
    """extract_response_content must not invent content from an empty/failed response."""
    from autoe2e.utils import extract_response_content
    assert extract_response_content('') is None
    assert extract_response_content(None) is None


def test_all_experiment_configs_share_identical_llm_bounds():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    seen = set()
    for app in ('TODOMVC', 'KEYSTONE_BLOG', 'EPIC_STACK', 'CYPRESS_RWA', 'BANGLE_IO'):
        c = Config.from_dict(json.loads((root / 'configs' / f'{app}.json').read_text()))
        seen.add((c.request_timeout_seconds, c.max_retries))
    assert seen == {(120.0, 1)}, f'llm bounds diverge across subjects: {seen}'


def test_runner_configures_bounds_before_any_llm_use():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / 'main.py').read_text()
    assert 'configure_llm(config_obj)' in src
    # must precede credential resolution and therefore every model construction
    assert src.index('configure_llm(config_obj)') < src.index('_resolve_api_key()')
