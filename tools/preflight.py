#!/usr/bin/env python3
"""Harness preflight for the five AutoE2E subjects. Starts nothing, crawls nothing.

Checks, per subject: the config parses and yields a base_url; the service answers; and the thing
answering is really that subject (identity match, because a port answering is never proof of
identity -- a stale clone on a recycled port answers happily as the wrong application).

Also checks the shared prerequisites: MongoDB, the reset/seed sources, and that AutoE2E's modules
and configs load WITHOUT any LLM credential present.

    python tools/preflight.py            # table + exit 1 if anything blocking fails
    python tools/preflight.py --verbose  # include the detail lines

No secret is ever read or printed: credential checks report presence only.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# identity: a string that must appear in the response body. Schema-agnostic on purpose.
SUBJECTS = [
    # config,           label,           identity,                          note
    ("TODOMVC",        "TodoMVC",       "React TypeScript TodoMVC 2022",   None),
    ("KEYSTONE_BLOG",  "Keystone-blog", "buildId",                          "graphql"),
    ("EPIC_STACK",     "Epic-stack",    "Epic Notes",                       None),
    ("CYPRESS_RWA",    "RWA",           "Cypress Real World App",           "rwa-api"),
    ("BANGLE_IO",      "Bangle-io",     "Bangle App",                       None),
]

RWA_API_IDENTITY = "Cypress Realworld App - backend"


def get(url: str, timeout: int = 10, data: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    rows, blocking, notes = [], [], []

    for cfg_name, label, identity, extra in SUBJECTS:
        cfg_path = ROOT / "configs" / f"{cfg_name}.json"
        if not cfg_path.exists():
            rows.append((label, "MISSING CONFIG", "-", "-"))
            blocking.append(f"{label}: no configs/{cfg_name}.json")
            continue
        try:
            base = json.loads(cfg_path.read_text())["driver"]["base_url"]
        except Exception as e:  # noqa: BLE001
            rows.append((label, "BAD CONFIG", "-", "-"))
            blocking.append(f"{label}: {cfg_name}.json unreadable: {e}")
            continue

        status, body = get(base)
        if status != 200:
            rows.append((label, base, f"DOWN ({body[:40]})", "-"))
            blocking.append(f"{label}: {base} did not answer 200")
            continue

        ident = "ok" if identity in body else "WRONG APP"
        if ident != "ok":
            blocking.append(f"{label}: {base} answered but identity {identity!r} absent")

        detail = ""
        if extra == "graphql":
            s, b = get(base.rstrip("/") + "/api/graphql",
                       data=b'{"query":"{ __typename }"}',
                       headers={"Content-Type": "application/json"})
            ok = s == 200 and '"__typename":"Query"' in b
            detail = f"graphql={'ok' if ok else 'FAIL'}"
            if not ok:
                blocking.append(f"{label}: GraphQL endpoint not answering")
        elif extra == "rwa-api":
            s, b = get("http://localhost:3001/")
            api_ok = s == 200 and RWA_API_IDENTITY in b
            detail = f"api={'ok' if api_ok else 'DOWN'}"
            if not api_ok:
                blocking.append("RWA: API on :3001 not live (run tools/rwa_up.sh)")
            else:
                # CORS allow-list must match the page origin exactly, or every call is refused.
                import urllib.parse as up
                origin = f"{up.urlparse(base).scheme}://{up.urlparse(base).netloc}"
                req = urllib.request.Request(
                    "http://localhost:3001/login", method="OPTIONS",
                    headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
                try:
                    with urllib.request.urlopen(req, timeout=8) as r:
                        allow = r.headers.get("Access-Control-Allow-Origin")
                except Exception:  # noqa: BLE001
                    allow = None
                if allow == origin:
                    detail += " cors=ok"
                else:
                    detail += f" cors=MISMATCH({allow})"
                    blocking.append(
                        f"RWA: API allows origin {allow!r} but the config loads {origin!r}")

        rows.append((label, base, ident, detail or "-"))

    # ---- shared prerequisites ----
    print("Subjects")
    print(f"  {'subject':14} {'base_url':34} {'identity':10} detail")
    for label, base, ident, detail in rows:
        print(f"  {label:14} {base:34} {ident:10} {detail}")

    print("\nShared prerequisites")

    # MongoDB
    try:
        import pymongo
        uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        pymongo.MongoClient(uri, serverSelectionTimeoutMS=4000).list_database_names()
        print(f"  mongodb            ok ({uri})")
    except Exception as e:  # noqa: BLE001
        print(f"  mongodb            FAIL ({type(e).__name__})")
        blocking.append("MongoDB not reachable")

    # reset/seed sources
    rc = subprocess.run(["bash", str(ROOT / "tools" / "ensure_snapshots.sh"), "--check"],
                        capture_output=True, text=True)
    print(f"  reset snapshots    {'ok' if rc.returncode == 0 else 'FAIL'}")
    if rc.returncode != 0:
        blocking.append("pristine snapshots missing (run tools/ensure_snapshots.sh)")
    if args.verbose:
        for line in rc.stdout.strip().splitlines():
            print(f"                       {line}")

    seed = ROOT / "harness" / "state" / "bangle-io-baseline.json"
    print(f"  bangle baseline    {'ok' if seed.exists() else 'MISSING'} ({seed.name})")

    rwa_seed = Path("/Users/stephenhe/Projects/new-benchmark-repos/cypress-realworld-app/data/database-seed.json")
    print(f"  rwa seed file      {'ok' if rwa_seed.exists() else 'MISSING'}")

    # ---- credentials: presence only, never a value, and `op` is never invoked ----
    print("\nLLM credential (presence only; no value is read or printed)")
    env_key = bool(os.getenv("LITELLM_API_KEY"))
    dotenv_key = False
    dotenv = ROOT / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            if line.startswith("LITELLM_API_KEY=") and line.split("=", 1)[1].strip():
                dotenv_key = True
    op_present = shutil.which("op") is not None
    print(f"  LITELLM_API_KEY in environment  {'yes' if env_key else 'no'}")
    print(f"  LITELLM_API_KEY in .env         {'yes' if dotenv_key else 'no'}")
    print(f"  `op` CLI fallback available     {'yes (not invoked here)' if op_present else 'no'}")
    if not (env_key or dotenv_key):
        notes.append("No LITELLM_API_KEY in the environment or .env. autoe2e.llm_api_call falls "
                     "back to `op read op://Employee/API Credentials/credential`; if that cannot "
                     "run, a crawl fails on its first LLM call.")

    # ---- the actual Priority-D assertion: config loads with NO credential present ----
    print("\nImport / config resolution without credentials")
    probe = (
        "import os, json, sys\n"
        "os.environ.pop('LITELLM_API_KEY', None)\n"
        "sys.path.insert(0, %r)\n"
        "import autoe2e.llm_api_call, autoe2e.mongo_utils, autoe2e.infer_utils, autoe2e.loop_utils\n"
        "from autoe2e.crawler.config import Config\n"
        "import glob\n"
        "n=0\n"
        "for p in glob.glob(os.path.join(%r,'configs','*.json')):\n"
        "    Config.from_dict(json.load(open(p))); n+=1\n"
        "print('MODULES_OK', n)\n" % (str(ROOT), str(ROOT))
    )
    rc2 = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, cwd=ROOT)
    ok = "MODULES_OK" in rc2.stdout
    count = rc2.stdout.strip().split()[-1] if ok else "?"
    print(f"  modules import + all {count} configs parse with LITELLM_API_KEY unset: "
          f"{'ok' if ok else 'FAIL'}")
    if not ok:
        blocking.append("AutoE2E cannot import/resolve config without a credential")
        print("   ", (rc2.stderr.strip().splitlines() or ["<no stderr>"])[-1])

    print()
    for n in notes:
        print(f"NOTE: {n}")
    if blocking:
        print(f"\nBLOCKING ({len(blocking)}):")
        for b in blocking:
            print(f"  - {b}")
        return 1
    print("preflight: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
