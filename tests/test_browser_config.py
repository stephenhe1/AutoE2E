"""Browser option construction. Pure: builds ChromeOptions, never launches Chrome."""
import pytest

from autoe2e.browser import build_chrome_options
from autoe2e.crawler.config import Config


def cfg(browser=None):
    d = {'driver': {'base_url': 'http://x/'}}
    if browser is not None:
        d['browser'] = browser
    return Config.from_dict(d)


def test_defaults_are_headed_and_not_detached():
    """detach defaulted to True before and leaked a browser on every run."""
    c = cfg()
    assert c.headless is False
    assert c.detach is False
    o = build_chrome_options(c)
    assert not any('headless' in a for a in o.arguments)
    assert o.experimental_options['detach'] is False


def test_headless_true_uses_the_new_headless_mode():
    o = build_chrome_options(cfg({'headless': True}))
    assert '--headless=new' in o.arguments


def test_experiment_profile_is_headless_and_undetached():
    c = cfg({'headless': True, 'detach': False})
    o = build_chrome_options(c)
    assert '--headless=new' in o.arguments
    assert o.experimental_options['detach'] is False


def test_debugging_profile_can_request_visible_and_detached():
    c = cfg({'headless': False, 'detach': True})
    o = build_chrome_options(c)
    assert not any('headless' in a for a in o.arguments)
    assert o.experimental_options['detach'] is True


def test_window_size_is_pinned_so_headless_matches_headed():
    o = build_chrome_options(cfg({'headless': True}))
    assert '--window-size=1920,1080' in o.arguments


def test_window_size_is_overridable():
    o = build_chrome_options(cfg({'window_size': '800,600'}))
    assert '--window-size=800,600' in o.arguments


def test_timeouts_are_configurable():
    c = cfg({'page_load_timeout': 45, 'implicit_wait': 2})
    assert c.page_load_timeout == 45 and c.implicit_wait == 2


@pytest.mark.parametrize('truthy', [True, 1])
def test_flags_are_coerced_to_bool(truthy):
    assert build_chrome_options(cfg({'detach': truthy})).experimental_options['detach'] is True


def test_baseline_hardening_flags_are_still_present():
    o = build_chrome_options(cfg())
    for flag in ('--disable-gpu', '--disable-dev-shm-usage', '--no-sandbox'):
        assert flag in o.arguments
