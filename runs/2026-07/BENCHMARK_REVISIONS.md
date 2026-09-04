# Benchmark subject revisions

Exact revisions of the benchmark subject checkouts as of 2026-09-04. Recorded here because the
checkouts themselves are **not committed**: they total 3.4 GB (of which 2.9 GB is `node_modules`)
and each is an independent git clone with its own `.git`, so `git add` would embed them as
gitlinks rather than store their contents.

| subject | revision | branch | upstream | working tree |
|---|---|---|---|---|
| umami | `af1b6c6efcadd65136a9ec3db6b8ec20962a8a69` | master | https://github.com/umami-software/umami.git | 1 untracked file: `docker-compose.override.yml` |
| cypress-realworld-app | `bdf6169232b919d9618ec29032addbd865f986cd` | develop | https://github.com/cypress-io/cypress-realworld-app | clean |
| extensive-react-boilerplate | `51ae27fb5057e9a960bf9ca66319e516cafa0d5c` | main | https://github.com/brocoders/extensive-react-boilerplate.git | clean |

To reconstruct any of them:

    git clone <upstream> <path> && git -C <path> checkout <revision>

`umami`'s untracked `docker-compose.override.yml` is local-only and is not reproduced by a clone.

## Two Cypress RealWorld App checkouts exist at different revisions

There are **two independent clones of the same application** on this machine, and they are not at
the same commit:

| path | revision | role | authored |
|---|---|---|---|
| `benchmark/cypress-realworld-app` | **`bdf6169`** (`bdf6169232b919d9618ec29032addbd865f986cd`) | this repo's subject, used by the July `CYPRESS_RWA` run | 2026-07-06 |
| `/Users/stephenhe/Projects/new-benchmark-repos/cypress-realworld-app` | **`6486a7e`** (`6486a7efed0cafe8b6c2b806704fd0b406dc7bff`) | the UI–Entity study's subject, served on port 5182 | 2026-06-21 |

They share history: `6486a7e` is a direct ancestor of `bdf6169`, which sits exactly **one commit
ahead**. That commit is `bdf6169` itself — *"chore: upgrade @percy/cypress to 3.1.8 for
allowCypressEnv support (#1720)"* — a devDependency bump to the Percy visual-testing integration.

So the two checkouts are equivalent for application behaviour, and the difference is confined to
test tooling. The trap is not behavioural drift but identity: `configs/CYPRESS_RWA.json` has been
repointed from `http://localhost:3000/` (the July target) to `http://127.0.0.1:5182/`, which is the
**`new-benchmark-repos` checkout**, not the one in `benchmark/`. A `CYPRESS_RWA` run made now
therefore exercises a different clone than the July run recorded in `runs/2026-07/`, and the two
are not directly comparable on that basis alone.

Port 3000 no longer serves RWA at all; it currently serves `new-benchmark-repos/epic-stack`
("Epic Notes"), which is why the config had to change.

## Missing reproducibility dependency

The harness registry `general-agent-eval/resources/scripts/services.json` names three
deterministic-reset scripts as `tools/...` paths in "the explorer repo". They are **absent from
`/Users/stephenhe/Projects/ui-graph-explorer/tools/`**, the repo those notes read as referring to.

They do exist, in a **different** checkout — `/Users/stephenhe/Projects/ui-graph-explorer-integration`
(remote `git@github.com:stephenhe1/UI-Graph-Explorer.git`), where all three are tracked. All three
have since been **vendored into this repository** under `tools/` with provenance headers; see
*Vendored reset/seed tools* in the README. The per-file commits below are the authoritative
reference — that checkout's HEAD moves (it was `ebfd444` when this file was first written and
`b07e8a84` a few minutes later), so pinning provenance to HEAD would be meaningless:

| script | path | tracked at |
|---|---|---|
| `epic_stack_reset.sh` | `ui-graph-explorer-integration/tools/epic_stack_reset.sh` | `bb9da86` 2026-08-23 *subject: epic-stack catalog, witnesses and lifecycle; keystone-blog reset* |
| `keystone_blog_reset.sh` | `ui-graph-explorer-integration/tools/keystone_blog_reset.sh` | `bb9da86` 2026-08-23 (same commit) |
| `bangle_seed_state.py` | `ui-graph-explorer-integration/tools/bangle_seed_state.py` | `94e2734` 2026-08-23 *subject: bangle-io deterministic workspace baseline* |

The two shell reset scripts are now self-contained in `tools/` and run standalone.
`bangle_seed_state.py` is vendored for provenance but **still is not runnable from this repository**:
it imports `playwright` and `ui_graph.restoration._IDB_EXPORT_JS`, neither of which is part of
AutoE2E. Bangle-io's client-state seeding therefore continues to depend on the
`ui-graph-explorer-integration` checkout. `services.json`'s `tools/` references remain relative to a
repo it does not name.
