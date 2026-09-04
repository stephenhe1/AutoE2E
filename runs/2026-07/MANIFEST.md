# July 2026 AutoE2E run artifacts

Five AutoE2E runs executed 2026-07-21 to 2026-07-22, preserved here on 2026-09-04.

Everything in this directory was previously excluded from git by `.gitignore` (`report/*.json`,
`tmp/*`) or existed only inside a live MongoDB instance. The `.gitignore` now carries **narrow,
per-file exceptions** for exactly these artifacts — see the `runs/2026-07` block there. New runs
remain ignored by default; preserving a future run means adding its files explicitly.

## Why this exists

`main.py` opens every run with

    action_func_db.delete_many({ 'app': APP_NAME })
    func_db.delete_many({ 'app': APP_NAME })

so re-running any subject destroys that subject's rows. The July feature predictions lived **only**
in `myDatabase` on `localhost:27017` and had no on-disk representation at all. `mongo/` is that
export. `CYPRESS_RWA` is also a subject of the pending five-repo run, so its rows were one command
from being lost.

## Runs covered

Timings come from the runs' own status files, which `main.py` wrote as they progressed.

| subject | started | elapsed | actions | states | queue at end | terminal state |
|---|---|---:|---:|---:|---:|---|
| TASKCAFE | 2026-07-21 15:24 | 82 s | 2 | 1 | 0 | DONE (queue drained) |
| CYPRESS_RWA | 2026-07-21 11:33 | 82 s | 12 | 1 | 0 | DONE (queue drained) |
| UMAMI | 2026-07-21 17:48 | 136 s | 5 | 1 | 0 | DONE (queue drained) |
| REALWORLD | 2026-07-21 15:24 | 498 s | 36 | 3 | 0 | DONE (queue drained) |
| REACT_BOILERPLATE | 2026-07-22 13:26 | 4380.7 s | 85 | 31 | 22 | **INCOMPLETE** |

### REACT_BOILERPLATE is an incomplete partial crawl

**Do not read REACT_BOILERPLATE as a finished run.** Its last status write is 2026-07-22 14:39
with `status: running`, `current_state` still populated, and **22 states left unexplored in the
queue**. It is a **73-minute partial crawl that was interrupted**, not a crawl that terminated
because it ran out of work.

It also dominates the totals: 197 of the 220 `action-functionality` rows and 39 of the 57
`functionality` rows are REACT_BOILERPLATE. Any aggregate across these five runs is therefore
mostly one unfinished crawl, and its counts are a lower bound that would have grown had it run to
completion.

The other four reached `current_state: DONE`. Note that three of those discovered exactly **one**
state, so their graphs are single-node and their feature counts are correspondingly small — the
runs are complete, but the crawls are shallow.

## Contents

| path | files | what it is |
|---|---:|---|
| `mongo/action-functionality.json` | 220 docs | action-to-functionality associations with `rank_score`, `depth`, `final`, `should_execute` |
| `mongo/functionality.json` | 57 docs | functionality texts with a 384-float `all-MiniLM-L6-v2` `embedding` each (the reason this file is 615 KB), plus `score`, `final`, `executable` |
| `mongo/_counts.json` | — | per-app document counts |
| `BENCHMARK_REVISIONS.md` | — | exact subject-checkout revisions the runs were executed against |
| `restore_mongo.py` | — | restores the two collections into MongoDB |
| `configs-as-run/` | 5 | the five subject configs **as each run actually used them**, verified by mtime predating each run's start. `CYPRESS_RWA.json` here is the pre-2026-09-04 copy targeting `http://localhost:3000/`; the live `configs/CYPRESS_RWA.json` has since been repointed to `http://127.0.0.1:5182/` |

Held in place rather than copied here, via narrow per-file `.gitignore` exceptions:

| path | files | what it is |
|---|---:|---|
| `report/<APP>.json` | 5 | state graphs from `save_state_graph()` — `{nodes, edges}`; all 5 parse as valid JSON |
| `tmp/status_<APP>.json` | 5 | `write_status()` output: start time, elapsed, loop counter, queue size, states discovered |

## Per-app document counts

| app | action-functionality | functionality | state graph nodes / edges |
|---|---:|---:|---|
| REACT_BOILERPLATE | 197 | 39 | 29 / 8 |
| REALWORLD | 12 | 9 | 3 / 1 |
| UMAMI | 4 | 4 | 1 / 1 |
| CYPRESS_RWA | 4 | 3 | 1 / 1 |
| TASKCAFE | 3 | 2 | 1 / 1 |
| **total** | **220** | **57** | |

## Restoring the MongoDB export

    python runs/2026-07/restore_mongo.py            # dry run, reports what it would write
    python runs/2026-07/restore_mongo.py --apply    # actually writes

The export is `bson.json_util` extended JSON, so `_id` round-trips as a real `ObjectId` and the
`func_pointer` references from `action-functionality` into `functionality` stay valid. Verified on
creation: 220 and 57 documents reload with 220 and 57 distinct `ObjectId` `_id`s.

**A restore overwrites current rows for the five apps it covers.** If a newer AutoE2E run has
populated `CYPRESS_RWA`, restoring will replace it.

## Secret scan

Scanned before committing: `report/*.json`, `tmp/status_*.json`, `configs/*.json` and both Mongo
exports.

- **No credential values.** Zero matches for value-style assignments
  (`password: "..."`, `api_key: "..."`) and zero for high-entropy token shapes
  (`sk-*`, JWT, `ghp_*`, `AKIA*`).
- The `password` / `credential` substring hits are **login-form DOM markup only** — 17 distinct
  snippets, all `<input type="password">`, `id="password"`, `autocomplete` attributes and a
  "Forgot Password?" link, captured as `outerHTML` by the crawler. They contain no values.
- No `LITELLM_API_KEY`, no `ete-litellm` base URL, and no `.env` value anywhere in the artifacts.
  The only `.env`-derived string present is `APP_NAME`'s value (`CYPRESS_RWA`), which is a subject
  label, not a secret.
- The subjects' own demo fixture credentials are non-production test data belonging to the public
  benchmark applications; none appear as values in these artifacts in any case.

## Deliberately not committed

Archived separately in `autoe2e-previous-runs-2026-07.zip`
(SHA-256 `45fbfce9df442c97765a6f2538809d6ac7997e7fec40b05141a58dae35d2b324`), which also contains
everything above:

- `autoe2e/logs/activity.log` (3.6 MB LLM prompt/response trace) and `error.log`
- `tmp/crawl_output*.log` (5 files, 1.1 MB)
- `tmp/screenshot_*.png` (29 content-addressed captures, 2.3 MB)

Never committed: the three `benchmark/` subject checkouts (3.4 GB, each its own git clone — see
`BENCHMARK_REVISIONS.md`), `node_modules`, `.venv`, browser and runtime caches, the zip archive
itself, and `.env`.
