#!/usr/bin/env bash
#
# ---------------------------------------------------------------------------
# VENDORED - do not edit here.
#
# Copied verbatim (this provenance block is the only addition) from:
#   repo    git@github.com:stephenhe1/UI-Graph-Explorer.git
#   path    tools/epic_stack_reset.sh
#   commit  bb9da86187ef022d5fed5ab6c2d832d4b83b0a9a
#           (2026-08-23, "subject: epic-stack catalog, witnesses and lifecycle; keystone-blog reset")
#   local checkout  /Users/stephenhe/Projects/ui-graph-explorer-integration
#
# Vendored into AutoE2E on 2026-09-04 because general-agent-eval/resources/scripts/
# services.json refers to these as "tools/..." in "the explorer repo", but they are
# absent from /Users/stephenhe/Projects/ui-graph-explorer/tools/ - the checkout that
# note reads as naming. Vendoring makes the five-subject harness self-contained.
#
# Behaviour is unchanged. Upstream is authoritative: re-sync from the commit above
# rather than editing this copy.
# ---------------------------------------------------------------------------
# Deterministic reset for epic-stack: restore a pristine seeded SQLite database.
#
# Why a snapshot rather than re-running the seed: prisma/seed.ts generates its five ordinary users
# with faker, so running it produces DIFFERENT data every time. A run whose baseline differs between
# episodes is not comparable with itself, let alone with another arm. Restoring one captured file
# makes the baseline byte-identical by construction, whatever the seed script does.
#
# The pristine file is built ONCE, into its own database path so nothing existing is destroyed:
#     cd <epic-stack>
#     rm -f prisma/pristine.db
#     DATABASE_URL="file:./pristine.db?connection_limit=1" npx prisma migrate deploy
#     DATABASE_URL="file:./pristine.db?connection_limit=1" npx tsx prisma/seed.ts
#
# `prisma migrate reset` is deliberately NOT used: it is destructive, and it is gated behind an
# explicit human consent prompt when invoked by an agent. Nothing here needs it.
#
# Roles and permissions come from the migration SQL, not the seed, so a migrated-and-seeded file is
# complete. The cache database is removed rather than restored: it is a derived cache, and the app
# recreates it on boot.
set -euo pipefail

REPO="${EPIC_STACK_REPO:-/Users/stephenhe/Projects/new-benchmark-repos/epic-stack}"
PRISTINE="$REPO/prisma/pristine.db"
LIVE="$REPO/prisma/data.db"

if [ ! -f "$PRISTINE" ]; then
  echo "no pristine snapshot at $PRISTINE; build it with the commands in this script's header" >&2
  exit 1
fi

cp "$PRISTINE" "$LIVE"
rm -f "$REPO/other/cache.db" "$REPO/other/cache.db-shm" "$REPO/other/cache.db-wal"
rm -f "$LIVE-shm" "$LIVE-wal"
echo "[epic-stack] restored pristine database ($(wc -c < "$LIVE" | tr -d ' ') bytes)"
