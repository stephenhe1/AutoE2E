#!/usr/bin/env python3
"""Run a subject's on_visit lifecycle hooks through the real code path, then stop. No crawl.

This exercises exactly what initialize_variables() runs before a crawl begins -- same Config,
same driver, same run_hooks -- so a pass here means the pre-crawl phase works, without
spending LLM budget or touching the crawl loop.

    python tools/verify_hooks.py EPIC_STACK CYPRESS_RWA BANGLE_IO
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autoe2e.crawler.config import Config          # noqa: E402
from autoe2e.crawler.crawl_context import CrawlContext  # noqa: E402
from autoe2e.crawler.lifecycle import run_hooks    # noqa: E402
from autoe2e.init_utils import initialize_driver   # noqa: E402

# A cheap post-condition per subject: substring that must appear in the page after the hooks
# ran. Deliberately generic (a logged-in shell, a workspace name), not a feature inventory.
POST = {
    'EPIC_STACK': 'kody',
    'CYPRESS_RWA': 'Heath93',
    'BANGLE_IO': 'ugx-baseline',
}


def verify(app: str) -> bool:
    cfg_path = ROOT / 'configs' / f'{app}.json'
    config = Config.from_dict(json.loads(cfg_path.read_text()))
    if not config.on_visit:
        print(f"  {app:14} no on_visit hooks configured")
        return True

    ctx = CrawlContext().set_config(config)
    driver = initialize_driver(config)
    ctx = ctx.set_driver(driver)
    try:
        driver.get(config.base_url)
        run_hooks(config.on_visit, ctx, phase='on_visit')

        url = driver.current_url
        source = driver.page_source
        needle = POST.get(app)
        ok = needle is None or needle in source
        print(f"  {app:14} hooks ok | url={url}")
        print(f"  {'':14} post-condition {needle!r}: {'FOUND' if ok else 'MISSING'}")
        return ok
    except Exception as e:  # noqa: BLE001
        print(f"  {app:14} FAILED: {type(e).__name__}: {str(e)[:160]}")
        return False
    finally:
        try:
            driver.quit()
        except Exception:  # noqa: BLE001
            pass


if __name__ == '__main__':
    apps = sys.argv[1:] or sorted(POST)

    # One subject per PROCESS. DriverContainer is an AbstractSingleton, so initialize_driver
    # hands back the same WebDriver for the life of the interpreter; verifying a second subject
    # in-process would reuse the driver the first one already quit. main.py is unaffected -- it
    # crawls a single APP_NAME per run -- but this checker deliberately does several.
    if len(apps) > 1:
        import subprocess
        print("Verifying on_visit lifecycle hooks (no crawl)")
        bad = []
        for a in apps:
            r = subprocess.run([sys.executable, __file__, a], capture_output=True, text=True)
            for line in r.stdout.splitlines():
                if line.strip() and not line.startswith('Verifying'):
                    print(line)
            if r.returncode != 0:
                bad.append(a)
        print()
        print("all hooks verified" if not bad else f"FAILED: {', '.join(bad)}")
        sys.exit(1 if bad else 0)

    print("Verifying on_visit lifecycle hooks (no crawl)")
    ok = verify(apps[0])
    sys.exit(0 if ok else 1)
