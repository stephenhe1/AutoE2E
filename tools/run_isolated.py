#!/usr/bin/env python3
"""Run one AutoE2E subject with isolated outputs, then put the environment back.

Why this exists
---------------
main.py writes to fixed, APP_NAME-derived locations and clears that app's MongoDB rows:

    report/<APP>.json
    tmp/status_<APP>.json
    mongo: delete_many({'app': APP})

So a run silently destroys any earlier run's artifacts for the same app. Demonstrated by the
CYPRESS_RWA calibration, which overwrote two COMMITTED July artifacts and deleted the July
Mongo rows for that app, because the historical run and the evaluation subject share a name.

This wrapper makes a run non-destructive without touching how main.py works:

  before   snapshot the app's Mongo rows and any existing report/status files
  run      main.py, unchanged, with the log captured
  export   copy the NEW report, status, log and Mongo rows into runs/<run_id>/<APP>/
  restore  put the pre-run Mongo rows and files back, and revert any temporary config edit

Restoration runs in a finally block, so it happens on success, failure and interruption. The
run's own artifacts remain in the run-scoped directory afterwards -- that is the deliverable.

Every Mongo operation is scoped to {'app': APP_NAME}. Rows belonging to any other app are never
read, deleted or rewritten.

    python tools/run_isolated.py TODOMVC
    python tools/run_isolated.py TODOMVC --run-id cal-01 \
        --set-crawl max_actions=10,max_states=30,max_wall_seconds=900
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

COLLECTIONS = ('action-functionality', 'functionality')


def mongo_db():
    import pymongo
    uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017')
    return pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000).myDatabase


def dump_app_rows(db, app: str) -> dict:
    """Export only this app's rows, as extended JSON so _id round-trips."""
    from bson import json_util
    return {c: json_util.dumps(list(db[c].find({'app': app})), indent=2) for c in COLLECTIONS}


def write_dump(dump: dict, directory: Path) -> dict:
    from bson import json_util
    directory.mkdir(parents=True, exist_ok=True)
    counts = {}
    for coll, payload in dump.items():
        (directory / f'{coll}.json').write_text(payload)
        counts[coll] = len(json_util.loads(payload))
    return counts


def restore_app_rows(db, app: str, dump: dict) -> dict:
    """Replace this app's rows with the snapshot. Scoped to {'app': app} only."""
    from bson import json_util
    counts = {}
    for coll, payload in dump.items():
        docs = json_util.loads(payload)
        db[coll].delete_many({'app': app})          # only this app
        if docs:
            db[coll].insert_many(docs)
        counts[coll] = db[coll].count_documents({'app': app})
    return counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('app')
    ap.add_argument('--run-id', default=None)
    ap.add_argument('--set-crawl', default=None,
                    help='temporary crawl overrides, e.g. max_actions=10,max_wall_seconds=900; '
                         'the config is restored byte-for-byte afterwards')
    ap.add_argument('--python', default=sys.executable)
    ap.add_argument('--target', default=None,
                    help='script to run instead of main.py. Exists so the isolation mechanism '
                         'itself can be verified with a stub, without spending LLM calls.')
    args = ap.parse_args()

    app = args.app
    run_id = args.run_id or datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    out = ROOT / 'runs' / run_id / app
    pre = out / 'pre_run'
    out.mkdir(parents=True, exist_ok=True)

    report = ROOT / 'report' / f'{app}.json'
    status = ROOT / 'tmp' / f'status_{app}.json'
    config = ROOT / 'configs' / f'{app}.json'
    if not config.exists():
        print(f'no such config: {config}', file=sys.stderr)
        return 2

    db = mongo_db()

    # ---------- before ----------
    pre_dump = dump_app_rows(db, app)
    pre_counts = write_dump(pre_dump, pre / 'mongo')
    pre.mkdir(parents=True, exist_ok=True)
    had_report, had_status = report.exists(), status.exists()
    if had_report:
        shutil.copy2(report, pre / 'report.json')
    if had_status:
        shutil.copy2(status, pre / 'status.json')
    config_bytes = config.read_bytes()

    print(f'[iso] run_id={run_id} app={app}')
    print(f'[iso] preserved mongo rows: {pre_counts}')
    print(f'[iso] preserved files: report={had_report} status={had_status}')

    if args.set_crawl:
        cfg = json.loads(config.read_text())
        overrides = {}
        for pair in args.set_crawl.split(','):
            k, v = pair.split('=', 1)
            overrides[k.strip()] = float(v) if '.' in v else int(v)
        cfg.setdefault('crawl', {}).update(overrides)
        config.write_text(json.dumps(cfg, indent=2) + '\n')
        print(f'[iso] temporary crawl override: {overrides}')

    exit_code = None
    log_path = out / 'run.log'
    try:
        with open(log_path, 'wb') as log:
            proc = subprocess.run(
                [args.python, args.target or str(ROOT / 'main.py')],
                cwd=str(ROOT),
                env={**os.environ, 'APP_NAME': app},
                stdout=log, stderr=subprocess.STDOUT,
            )
        exit_code = proc.returncode
        print(f'[iso] main.py exit code: {exit_code}')
    finally:
        # ---------- export the NEW run's artifacts ----------
        post_counts = {}
        try:
            post_counts = write_dump(dump_app_rows(db, app), out / 'mongo')
            if report.exists():
                shutil.copy2(report, out / 'report.json')
            if status.exists():
                shutil.copy2(status, out / 'status.json')
            print(f'[iso] exported run mongo rows: {post_counts}')
        except Exception as e:  # noqa: BLE001
            print(f'[iso] export failed: {type(e).__name__}: {e}', file=sys.stderr)

        # ---------- restore the environment ----------
        restored = {}
        try:
            restored = restore_app_rows(db, app, pre_dump)
            print(f'[iso] restored mongo rows for {app}: {restored}')
        except Exception as e:  # noqa: BLE001
            print(f'[iso] mongo restore FAILED: {type(e).__name__}: {e}', file=sys.stderr)

        try:
            if had_report:
                shutil.copy2(pre / 'report.json', report)
            elif report.exists():
                report.unlink()          # the run created it; it did not exist before
            if had_status:
                shutil.copy2(pre / 'status.json', status)
            elif status.exists():
                status.unlink()
            config.write_bytes(config_bytes)
            print('[iso] restored report/status files and config')
        except Exception as e:  # noqa: BLE001
            print(f'[iso] file restore FAILED: {type(e).__name__}: {e}', file=sys.stderr)

        (out / 'manifest.json').write_text(json.dumps({
            'run_id': run_id,
            'app': app,
            'exit_code': exit_code,
            'finished_at': datetime.datetime.now().isoformat(),
            'pre_run_mongo_counts': pre_counts,
            'run_mongo_counts': post_counts,
            'restored_mongo_counts': restored,
            'preexisting_report': had_report,
            'preexisting_status': had_status,
            'crawl_override': args.set_crawl,
            'target': args.target or 'main.py',
            'artifacts': {
                'report': 'report.json', 'status': 'status.json',
                'log': 'run.log', 'mongo': 'mongo/',
            },
        }, indent=2) + '\n')
        print(f'[iso] run artifacts kept in: {out}')

    return exit_code if exit_code is not None else 1


if __name__ == '__main__':
    sys.exit(main())
