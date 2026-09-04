#!/usr/bin/env bash
#
# ---------------------------------------------------------------------------
# VENDORED - do not edit here.
#
# Copied verbatim (this provenance block is the only addition) from:
#   repo    git@github.com:stephenhe1/UI-Graph-Explorer.git
#   path    tools/keystone_blog_reset.sh
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
# Deterministic reset for the Keystone usecase-blog example: restore a pristine seeded SQLite file.
#
# Unlike epic-stack's, this subject's seed IS reproducible -- examples/usecase-blog/seed-data.ts
# inserts fixed authors and posts from examples/example-data.ts and skips anything already present.
# A snapshot is still restored rather than re-seeded, for two reasons: it is much faster than booting
# Keystone's context to run the seed, and it makes the baseline independent of the seed script, so a
# change there cannot silently move the baseline underneath a comparison.
#
# The pristine file is built ONCE:
#     cd <keystone>/examples/usecase-blog
#     npx keystone build                     # generates the client and the migration
#     npx keystone prisma migrate deploy     # or `keystone dev` once, which migrates on boot
#     npx tsx seed-data.ts
#     cp keystone-example.db keystone-example.pristine.db
set -euo pipefail

EXAMPLE="${KEYSTONE_BLOG_DIR:-/Users/stephenhe/Projects/new-benchmark-repos/keystone/examples/usecase-blog}"
PRISTINE="$EXAMPLE/keystone-example.pristine.db"
LIVE="$EXAMPLE/keystone-example.db"

if [ ! -f "$PRISTINE" ]; then
  echo "no pristine snapshot at $PRISTINE; build it with the commands in this script's header" >&2
  exit 1
fi

cp "$PRISTINE" "$LIVE"
rm -f "$LIVE-shm" "$LIVE-wal"
echo "[keystone-blog] restored pristine database ($(wc -c < "$LIVE" | tr -d ' ') bytes)"
