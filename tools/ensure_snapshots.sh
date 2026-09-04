#!/usr/bin/env bash
# Guarantee the pristine reset snapshots exist in the subject checkouts.
#
# Why this exists
# ---------------
# epic_stack_reset.sh and keystone_blog_reset.sh both restore a "pristine" SQLite snapshot over
# the live database. Neither snapshot is tracked in its own subject repository:
#
#   epic-stack/prisma/pristine.db                              UNTRACKED
#   keystone/examples/usecase-blog/keystone-example.pristine.db UNTRACKED
#
# So a clean re-clone of either subject does NOT produce a working reset, and deleting the file
# loses it permanently. Both snapshots are therefore committed into THIS repository under
# harness/fixtures/, and this script installs them into the subject checkouts when missing or
# when their content does not match.
#
# Rebuilding a snapshot from scratch is possible but not deterministic for epic-stack: its
# prisma/seed.ts uses faker, so re-seeding produces different data every time. That is exactly
# why a byte-exact snapshot has to be preserved rather than regenerated.
#
# Idempotent and non-destructive: it only ever writes the *pristine* file, never the live
# database. Run the subject's reset script afterwards to apply it.
#
# Usage:
#   bash tools/ensure_snapshots.sh          # install any missing/mismatched snapshot
#   bash tools/ensure_snapshots.sh --check  # report only, change nothing (exit 1 if any missing)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURES="$HERE/../harness/fixtures"

EPIC_REPO="${EPIC_STACK_REPO:-/Users/stephenhe/Projects/new-benchmark-repos/epic-stack}"
KEYSTONE_DIR="${KEYSTONE_BLOG_DIR:-/Users/stephenhe/Projects/new-benchmark-repos/keystone/examples/usecase-blog}"

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

rc=0

ensure() {
    local name="$1" fixture="$2" target="$3" want="$4"

    if [ ! -f "$fixture" ]; then
        echo "[$name] FIXTURE MISSING: $fixture" >&2
        rc=1; return
    fi

    local have=""
    [ -f "$target" ] && have="$(shasum -a 256 "$target" | cut -d' ' -f1)"

    if [ "$have" = "$want" ]; then
        echo "[$name] snapshot present and matches fixture"
        return
    fi

    if [ -z "$have" ]; then
        echo "[$name] snapshot MISSING at $target"
    else
        echo "[$name] snapshot at $target does not match the committed fixture"
    fi

    if [ "$CHECK_ONLY" = "1" ]; then
        rc=1; return
    fi

    mkdir -p "$(dirname "$target")"
    cp "$fixture" "$target"
    local now="$(shasum -a 256 "$target" | cut -d' ' -f1)"
    if [ "$now" = "$want" ]; then
        echo "[$name] installed snapshot from fixture ($(wc -c < "$target" | tr -d ' ') bytes)"
    else
        echo "[$name] install FAILED: checksum mismatch after copy" >&2
        rc=1
    fi
}

ensure "epic-stack" \
    "$FIXTURES/epic-stack/pristine.db" \
    "$EPIC_REPO/prisma/pristine.db" \
    "b4900fdbb01fe69e65bc3f77c22059e2b5da86d85ed431c9cd9f38ab058cb7d6"

ensure "keystone-blog" \
    "$FIXTURES/keystone-blog/keystone-example.pristine.db" \
    "$KEYSTONE_DIR/keystone-example.pristine.db" \
    "65152f6f7e911d29de86b2b082b4cc3dcae01f6d9cecaf8807c02c758ac58f3c"

exit $rc
