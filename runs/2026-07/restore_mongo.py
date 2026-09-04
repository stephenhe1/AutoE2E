#!/usr/bin/env python3
"""Restore the July 2026 AutoE2E run output into MongoDB.

The export is bson.json_util extended JSON, so _id round-trips as a real ObjectId and the
func_pointer references from action-functionality into functionality stay valid.

Dry run by default; pass --apply to write. A restore REPLACES existing rows for the five apps
the export covers, so a newer run's CYPRESS_RWA rows would be overwritten.

    python runs/2026-07/restore_mongo.py
    python runs/2026-07/restore_mongo.py --apply
"""
import argparse
import collections
import os
import sys
from pathlib import Path

import pymongo
from bson import json_util

COLLECTIONS = ("action-functionality", "functionality")
EXPECTED = {"action-functionality": 220, "functionality": 57}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="actually write (default is a dry run)")
    parser.add_argument("--uri", default=os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
    parser.add_argument("--db", default="myDatabase")
    args = parser.parse_args()

    here = Path(__file__).resolve().parent
    db = pymongo.MongoClient(args.uri, serverSelectionTimeoutMS=5000)[args.db]

    print(f"{'APPLY' if args.apply else 'DRY RUN'}  ->  {args.uri}  db={args.db}\n")
    failed = False

    for coll in COLLECTIONS:
        path = here / "mongo" / f"{coll}.json"
        docs = json_util.loads(path.read_text())

        if len(docs) != EXPECTED[coll]:
            print(f"  !! {coll}: expected {EXPECTED[coll]} docs, export has {len(docs)}")
            failed = True
        if len({d["_id"] for d in docs}) != len(docs):
            print(f"  !! {coll}: duplicate _id in export")
            failed = True

        apps = sorted({d["app"] for d in docs})
        present = db[coll].count_documents({"app": {"$in": apps}})
        by_app = collections.Counter(d["app"] for d in docs)

        print(f"  {coll}: {len(docs)} docs in export "
              f"({', '.join(f'{a}={by_app[a]}' for a in apps)})")
        print(f"    rows currently in db for these apps: {present}"
              f"{'  <-- WILL BE REPLACED' if present and args.apply else ''}")

        if args.apply:
            db[coll].delete_many({"app": {"$in": apps}})
            db[coll].insert_many(docs)
            print(f"    restored: {db[coll].count_documents({'app': {'$in': apps}})} rows")

    if failed:
        print("\nexport integrity check FAILED; nothing was written" if not args.apply
              else "\nexport integrity check FAILED")
        return 1
    if not args.apply:
        print("\nnothing written. re-run with --apply to restore.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
