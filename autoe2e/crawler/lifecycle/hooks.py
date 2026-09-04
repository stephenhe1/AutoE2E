"""Lifecycle hooks: work that must happen once, before a crawl starts.

Two gaps motivated these. AutoE2E could not log in, so every login-gated surface stayed
unexplored; and it could not apply a captured client-state baseline, so subjects that gate
their UI on IndexedDB (bangle-io renders only "Create a workspace to get started" with an
empty database) presented only that empty screen. `lifecycle.on_visit` existed in the config
schema and was parsed, but nothing in the codebase ever read it.

A hook receives the CrawlContext and returns None. Raising aborts the crawl, which is
deliberate: silently crawling a logged-out application produces a confidently wrong result,
and that is worse than stopping.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin

from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from autoe2e.utils import logger
from autoe2e.crawler.lifecycle.idb_js import _IDB_IMPORT_JS

_ENV_REF = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def resolve_secret(value):
    """Expand a whole-string ${ENV_VAR} reference, so real credentials need not be committed.

    A literal is returned unchanged: the benchmark subjects ship well-known fixture
    credentials that are already public in their own repositories, and pinning those in a
    config is what makes a run reproducible. Anything genuinely secret should be written as
    ${VAR} and supplied through the environment.
    """
    if not isinstance(value, str):
        return value
    m = _ENV_REF.match(value.strip())
    if not m:
        return value
    name = m.group(1)
    if name not in os.environ:
        raise RuntimeError(
            f"lifecycle config references ${{{name}}} but that variable is not set"
        )
    return os.environ[name]


class Hook:
    def __init__(self, **params):
        self.params = params

    def run(self, crawl_context) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class FormLogin(Hook):
    """Authenticate through the application's own login form, before the crawl begins.

    Driving the real form rather than injecting a cookie means the session is established the
    way a user establishes it, so nothing about the app's auth path is bypassed or assumed.

    Params:
        url                       login page, absolute or relative to base_url (default: base_url)
        username_selector         CSS selector for the username field
        password_selector         CSS selector for the password field
        submit_selector           CSS selector for the submit control
        username, password        values; a whole-string ${ENV_VAR} is read from the environment
        success_selector          CSS that must appear once logged in (optional)
        success_url_excludes      substring that must be ABSENT from the URL once logged in (optional)
        already_logged_in_selector  if present before we start, skip (optional)
        timeout                   seconds to wait for each condition (default 20)
    """

    def run(self, crawl_context) -> None:
        p = self.params
        driver = crawl_context.driver
        base = crawl_context.config.base_url
        timeout = int(p.get("timeout", 20))

        target = urljoin(base, p["url"]) if p.get("url") else base
        driver.get(target)

        already = p.get("already_logged_in_selector")
        if already:
            try:
                WebDriverWait(driver, 2).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, already)))
                logger.info("FormLogin: already authenticated, skipping")
                return
            except TimeoutException:
                pass

        logger.info(f"FormLogin: authenticating at {target}")
        wait = WebDriverWait(driver, timeout)

        user_el = wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, p["username_selector"])))
        user_el.clear()
        user_el.send_keys(resolve_secret(p["username"]))

        pass_el = driver.find_element(By.CSS_SELECTOR, p["password_selector"])
        pass_el.clear()
        pass_el.send_keys(resolve_secret(p["password"]))

        driver.find_element(By.CSS_SELECTOR, p["submit_selector"]).click()

        # Verify. An unverified login is the failure mode that matters: the crawl would run
        # against the logged-out surface and report it as the application.
        ok_sel = p.get("success_selector")
        ok_url_excl = p.get("success_url_excludes")
        if not ok_sel and not ok_url_excl:
            time.sleep(2)
            logger.warn("FormLogin: no success condition configured; login is UNVERIFIED")
            return

        deadline = time.time() + timeout
        while time.time() < deadline:
            if ok_sel:
                try:
                    driver.find_element(By.CSS_SELECTOR, ok_sel)
                    logger.info(f"FormLogin: authenticated (matched {ok_sel})")
                    return
                except WebDriverException:
                    pass
            if ok_url_excl and ok_url_excl not in driver.current_url:
                logger.info(f"FormLogin: authenticated (URL left {ok_url_excl})")
                return
            time.sleep(0.5)

        raise RuntimeError(
            f"FormLogin failed to confirm authentication within {timeout}s "
            f"(url={driver.current_url}); refusing to crawl a logged-out application"
        )


class ClientState(Hook):
    """Seed browser-local state from a captured baseline, before the crawl begins.

    Needed by subjects whose UI is gated on client state. AutoE2E starts Chrome without a
    --user-data-dir, so IndexedDB and localStorage are empty on every run; without this the
    crawl only ever sees the empty-state screen.

    Params:
        baseline      path to a baseline JSON (repo-relative or absolute), as written by
                      tools/bangle_seed_state.py
        landing_url   where to navigate after applying; defaults to the baseline's
                      captured_landing_url, else base_url
        timeout       seconds allowed for the IndexedDB import (default 30)
    """

    def run(self, crawl_context) -> None:
        p = self.params
        driver = crawl_context.driver
        base = crawl_context.config.base_url
        timeout = int(p.get("timeout", 30))

        path = Path(p["baseline"])
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[3] / path
        if not path.exists():
            raise RuntimeError(f"ClientState: baseline not found: {path}")
        baseline = json.loads(path.read_text())

        # Must be on the target origin before touching its storage.
        driver.get(base)

        local = baseline.get("local_storage") or {}
        if local:
            for k, v in local.items():
                driver.execute_script(
                    "window.localStorage.setItem(arguments[0], arguments[1]);", k, v)
            logger.info(f"ClientState: seeded {len(local)} localStorage key(s)")

        dump = baseline.get("indexed_db") or {}
        if dump:
            driver.set_script_timeout(timeout + 10)
            result = driver.execute_async_script(
                "const cb = arguments[arguments.length - 1];"
                "(" + _IDB_IMPORT_JS + ")(arguments[0])"
                "  .then(r => cb({ok: true, result: r}))"
                "  .catch(e => cb({ok: false, error: String(e)}));",
                dump,
            )
            if not result or not result.get("ok"):
                raise RuntimeError(
                    f"ClientState: IndexedDB import failed: "
                    f"{(result or {}).get('error', 'no result')}"
                )
            logger.info(f"ClientState: restored IndexedDB {sorted(dump)}")

        landing = p.get("landing_url") or baseline.get("captured_landing_url") or base
        if not landing.startswith("http"):
            landing = urljoin(base, landing)
        driver.get(landing)
        logger.info(f"ClientState: landed on {landing}")
