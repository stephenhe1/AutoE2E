"""Config section parsing, including the MRO defect that left mixin attributes undefined."""
import json
from pathlib import Path

import pytest

from autoe2e.crawler.config import Config

ROOT = Path(__file__).resolve().parent.parent

EXPERIMENT_APPS = ['TODOMVC', 'KEYSTONE_BLOG', 'EPIC_STACK', 'CYPRESS_RWA', 'BANGLE_IO']


def test_bare_config_has_every_section_initialised():
    """Config's mixins do not cooperate in the MRO, so one chained super().__init__() only
    reached the first base. A config omitting `lifecycle` then raised AttributeError on
    `config.on_visit` rather than defaulting to no hooks."""
    c = Config.from_dict({'driver': {'base_url': 'http://x/'}})
    assert c.on_visit == [] and c.on_state_discovery == []
    assert c.headless is False and c.detach is False
    assert c.max_actions is None and c.max_states is None and c.max_wall_seconds is None
    assert c.base_url == 'http://x/'


def test_empty_config_does_not_raise():
    c = Config.from_dict({})
    assert c.base_url is None
    assert c.on_visit == []


@pytest.mark.parametrize('app', EXPERIMENT_APPS)
def test_experiment_config_declares_browser_and_crawl(app):
    c = Config.from_dict(json.loads((ROOT / 'configs' / f'{app}.json').read_text()))
    assert c.headless is True, f'{app} must run headless for experiments'
    assert c.detach is False, f'{app} must not leave a detached browser'
    assert c.max_actions and c.max_states and c.max_wall_seconds


def test_all_experiment_configs_declare_the_same_budget():
    budgets = set()
    for app in EXPERIMENT_APPS:
        c = Config.from_dict(json.loads((ROOT / 'configs' / f'{app}.json').read_text()))
        budgets.add((c.max_actions, c.max_states, c.max_wall_seconds))
    assert len(budgets) == 1, f'experiment budgets diverge: {budgets}'


def test_every_shipped_config_parses():
    paths = sorted((ROOT / 'configs').glob('*.json'))
    assert paths, 'no configs found; path resolution is wrong'
    for path in paths:
        Config.from_dict(json.loads(path.read_text()))


def test_credential_is_resolved_before_the_destructive_deletes():
    """Ordering invariant, asserted on source because main.py is a script, not importable.

    The deletes clear the previous run's predictions and nothing writes them to disk, so they
    are that run's only copy. They must come after the credential resolves, the driver starts
    and the lifecycle hooks succeed -- otherwise a missing key or a failed login destroys the
    previous results and only then fails.
    """
    src = (ROOT / 'main.py').read_text()
    resolve = src.index('_resolve_api_key()')
    driver = src.index('initialize_driver(config_obj)')
    hooks = src.index('initialize_variables(crawl_context)')
    delete = src.index("action_func_db.delete_many({ 'app': APP_NAME })")
    assert resolve < driver < hooks < delete


def test_teardown_is_guaranteed_on_every_path():
    """driver.quit() must run on completion, failure and interruption."""
    src = (ROOT / 'main.py').read_text()
    assert 'except BaseException' in src, 'KeyboardInterrupt must reach teardown'
    assert '\nfinally:' in src, 'teardown must be in a finally block'
    assert src.index('\nfinally:') < src.index('shutdown_driver_container()')
