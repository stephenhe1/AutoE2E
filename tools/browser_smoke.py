#!/usr/bin/env python3
"""Browser lifecycle smoke check. Launches a real browser, navigates, tears down. No LLM calls.

Verifies the guarantee that matters for an experiment run: after teardown, no browser or driver
process started by this run is still alive.

Leftovers are detected by DIFFING the process table around the launch, not by counting Chrome
globally -- a developer machine has plenty of unrelated Chrome processes, and a global count
would be meaningless. Only PIDs that appeared because of this run are checked.

    python tools/browser_smoke.py                 # experiment profile: headless, not detached
    python tools/browser_smoke.py --url URL       # override the target
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autoe2e.browser import get_driver_container, shutdown_driver_container  # noqa: E402
from autoe2e.crawler.config import Config  # noqa: E402

PATTERN = 'Google Chrome|chromedriver|chromium'


def browser_pids() -> set[int]:
    out = subprocess.run(['pgrep', '-f', PATTERN], capture_output=True, text=True).stdout
    return {int(x) for x in out.split() if x.isdigit()}


def alive(pids: set[int]) -> set[int]:
    return {p for p in pids if subprocess.run(['kill', '-0', str(p)],
                                              capture_output=True).returncode == 0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://127.0.0.1:5180/')
    ap.add_argument('--config', default=None, help='subject config name, e.g. TODOMVC')
    args = ap.parse_args()

    if args.config:
        config = Config.from_dict(json.loads((ROOT / 'configs' / f'{args.config}.json').read_text()))
        url = config.base_url
    else:
        config = Config.from_dict({
            'driver': {'base_url': args.url},
            'browser': {'headless': True, 'detach': False},
        })
        url = args.url

    print(f"profile: headless={config.headless} detach={config.detach} "
          f"window={config.window_size}")
    if config.headless is not True or config.detach is not False:
        print("  WARNING: this is not the experiment profile (expected headless=True, detach=False)")

    before = browser_pids()
    print(f"browser-ish processes before launch: {len(before)}")

    failures = []
    driver = None
    spawned: set[int] = set()
    try:
        container = get_driver_container(config)
        driver = container.get_driver()
        time.sleep(1)  # let Chrome's helper processes appear before snapshotting
        spawned = browser_pids() - before
        print(f"processes spawned by this run: {len(spawned)} (chromedriver pid "
              f"{container.service_pid})")
        if not spawned:
            failures.append('no new browser process was detected; the smoke proved nothing')

        driver.get(url)
        title = driver.title
        print(f"navigated to {url} -> title={title!r}")
        if not title:
            failures.append(f'no page title from {url}; is the service up?')

        # Headless must still report a real viewport, or element visibility changes.
        size = driver.get_window_size()
        print(f"viewport: {size['width']}x{size['height']}")
        if size['width'] < 800:
            failures.append(f'viewport unexpectedly small: {size}')

    except Exception as e:  # noqa: BLE001
        failures.append(f'{type(e).__name__}: {e}')
    finally:
        # Exactly what main.py does in its finally block.
        quit_ok = shutdown_driver_container()
        print(f"teardown: {'driver quit' if quit_ok else 'nothing to quit'}")

    # Chrome exits asynchronously; give it a moment before declaring a leak.
    residual = alive(spawned)
    for _ in range(20):
        if not residual:
            break
        time.sleep(0.25)
        residual = alive(spawned)

    print(f"residual processes from this run: {len(residual)}"
          + (f" -> {sorted(residual)}" if residual else ""))
    if residual:
        for pid in sorted(residual):
            cmd = subprocess.run(['ps', '-o', 'command=', '-p', str(pid)],
                                 capture_output=True, text=True).stdout.strip()
            print(f"    LEAKED pid {pid}: {cmd[:110]}")
        failures.append(f'{len(residual)} process(es) left behind after teardown')

    print()
    if failures:
        print("browser smoke FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("browser smoke PASSED: launched headless, navigated, tore down, nothing left behind")
    return 0


if __name__ == '__main__':
    sys.exit(main())
