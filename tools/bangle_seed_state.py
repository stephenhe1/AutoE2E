#!/usr/bin/env python3
#
# ---------------------------------------------------------------------------
# VENDORED - do not edit here.
#
# Copied from (see LOCAL DEVIATIONS at the end of this block):
#   repo    git@github.com:stephenhe1/UI-Graph-Explorer.git
#   path    tools/bangle_seed_state.py
#   commit  94e2734960ebef93c0e9b5900b788c2c3b7fab5c
#           (2026-08-23, "subject: bangle-io deterministic workspace baseline")
#   local checkout  /Users/stephenhe/Projects/ui-graph-explorer-integration
#
# Vendored into AutoE2E on 2026-09-04 because general-agent-eval/resources/scripts/
# services.json refers to these as "tools/..." in "the explorer repo", but they are
# absent from /Users/stephenhe/Projects/ui-graph-explorer/tools/ - the checkout that
# note reads as naming. Vendoring makes the five-subject harness self-contained.
#
# Behaviour is unchanged. Upstream is authoritative: re-sync from the commit above
# rather than editing this copy.
#
# LOCAL DEVIATIONS (2 lines, so this file is NOT byte-identical to upstream):
#   1. sys.path.insert now points at this script's OWN directory instead of
#      <script dir>/../src, which does not exist in AutoE2E.
#   2. `from ui_graph.restoration import _IDB_EXPORT_JS` becomes
#      `from idb_export_js import _IDB_EXPORT_JS`, the vendored copy of that one
#      constant (tools/idb_export_js.py).
# Both changes exist solely to remove the runtime dependency on another checkout.
# Observable behaviour is unchanged: the same JS string is evaluated.
# ---------------------------------------------------------------------------
"""Capture bangle-io's prerequisite client state by driving the application's OWN creation flow.

Bangle is state-gated: with an empty IndexedDB it renders "No workspace selected / Create a
workspace to get started" and has no note surface at all. Exploring it in that condition explores
its empty-state screen, which is why the first attempt reached three actions.

The baseline is therefore ONE workspace -- the prerequisite, and nothing else. No notes, no starred
paths, no preferences: those are objects a run is supposed to discover it can create, and
pre-creating them would pre-satisfy exactly what is being measured.

Why drive the UI instead of writing the records directly: the records then come from the
application, so the database name, version, store names, key paths and value shape match the real
schema by construction rather than by my reading of it. This script is the subject-specific half;
what consumes its output (``app.client_state_baseline``) knows nothing about bangle.

Volatile fields are pinned so the baseline is byte-identical every time it is applied -- a
non-deterministic baseline would make repeated runs incomparable, which is the whole point of
having one.

Usage:
    python tools/bangle_seed_state.py --base-url http://127.0.0.1:5173 \
        --out frozen/state/bangle-io-baseline.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# vendored-dependency lookup: this script's own directory (see LOCAL DEVIATIONS above)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.async_api import async_playwright  # noqa: E402

from idb_export_js import _IDB_EXPORT_JS  # noqa: E402

# Pinned so the baseline does not change between captures. The application only ever displays or
# orders by this value, so a fixed instant is as valid as the instant of capture.
PINNED_LAST_MODIFIED = 1700000000000


def _pin_timestamps(node):
    """Replace every lastModified with the pinned constant, at any depth."""
    if isinstance(node, dict):
        return {
            key: (PINNED_LAST_MODIFIED if key == "lastModified" else _pin_timestamps(value))
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_pin_timestamps(item) for item in node]
    return node


async def capture(base_url: str, workspace: str) -> dict:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await (await browser.new_context()).new_page()
        try:
            await page.goto(base_url, wait_until="load")
            await page.wait_for_timeout(2500)

            # The app's own e2e helper (packages/tooling/e2e-tests/src/common.ts) closes the
            # responsive sidebar sheet first; without it the welcome workflow is covered.
            try:
                if await page.get_by_role("dialog").first.is_visible():
                    await page.keyboard.press("Escape")
            except Exception:
                pass

            await page.get_by_role("button", name="Create Workspace").click()
            await page.get_by_role("radio", name="Browser Save workspace data").click()
            await page.get_by_role("button", name="Next").click()
            await page.get_by_label("Workspace Name", exact=True).fill(workspace)
            await page.get_by_role("button", name="Create").click()
            await page.wait_for_timeout(4000)

            # The workspace surface, not the landing page, is what proves creation succeeded.
            body = await page.inner_text("body")
            if workspace not in body:
                raise SystemExit(
                    f"workspace {workspace!r} does not appear after the creation flow; "
                    f"page reads: {body[:200]!r}"
                )
            landing_url = page.url

            exported = await page.evaluate(_IDB_EXPORT_JS)
            if not isinstance(exported, dict) or exported.get("status") not in (None, "ok"):
                raise SystemExit(f"indexeddb export not usable: {exported!r}")
            databases = exported.get("databases") or {}
            if not databases:
                raise SystemExit("creation flow left no IndexedDB state to capture")
            # Keep only the databases that actually CARRY the prerequisite. Opening a workspace also
            # brings an empty file-storage database into existence, and seeding an empty shell adds a
            # schema the baseline has to keep matching while contributing no state -- the application
            # creates it on demand anyway. Seed the record, not the container.
            databases = {
                name: db
                for name, db in databases.items()
                if any((store.get("records") or []) for store in (db.get("stores") or {}).values())
            }
            if not databases:
                raise SystemExit("creation flow produced no records; nothing to seed")

            local_storage = await page.evaluate(
                "() => Object.fromEntries(Object.entries(localStorage))"
            )
        finally:
            await browser.close()

    return {
        "indexed_db": _pin_timestamps(databases),
        # Deliberately empty of the app's load counter: "times app loaded" is not a prerequisite for
        # a usable surface, and seeding it would plant a value for an effect the run may observe.
        "local_storage": {},
        "captured_landing_url": landing_url,
        "workspace": workspace,
        "observed_local_storage": local_storage,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--workspace", default="ugx-baseline")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    state = asyncio.run(capture(args.base_url.rstrip("/"), args.workspace))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")

    databases = state["indexed_db"]
    records = sum(
        len(store.get("records") or [])
        for db in databases.values()
        for store in (db.get("stores") or {}).values()
    )
    print(f"wrote {args.out}")
    print(f"  databases : {sorted(databases)}")
    print(f"  records   : {records}")
    print(f"  landing   : {state['captured_landing_url']}")
    print(f"  observed localStorage (NOT seeded): {state['observed_local_storage']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
