# AutoE2E
Source code and benchmark subjects for "AutoE2E: Feature-Driven End-To-End Test Generation."

![AutoE2E Workflow](./workflow.png)

## Requirements
- Python 3.9+
- Chrome browser (for Selenium WebDriver)
- MongoDB (local or Atlas)
- LiteLLM API access (for LLM chat + embeddings)

Install the required packages:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage
Copy the example env file and fill in your credentials:
```bash
cp .env.example .env
```

Required environment variables:
1. `APP_NAME`: The name of the application you want to generate E2E test cases for. This needs to match one of the configs in `./configs` folder (e.g. `PETCLINIC`).
2. `LITELLM_API_KEY`: Your LiteLLM API key.
3. `LITELLM_BASE_URL`: LiteLLM proxy URL (defaults to `https://ete-litellm.ai-models.vpc-int.res.ibm.com`).
4. `MONGODB_URI`: MongoDB connection string (defaults to `mongodb://localhost:27017`).

Then run the project:
```bash
source .venv/bin/activate
python main.py
```

## Reproducibility

### The July 2026 run artifacts

`runs/2026-07/` preserves the output of five AutoE2E runs executed 2026-07-21 to 2026-07-22. It
exists because `main.py` opens every run with

```python
action_func_db.delete_many({ 'app': APP_NAME })
func_db.delete_many({ 'app': APP_NAME })
```

so re-running a subject destroys that subject's rows. Those predictions previously lived **only** in
a live MongoDB instance with no on-disk copy.

| subject | actions | states | outcome |
|---|---:|---:|---|
| TASKCAFE | 2 | 1 | complete (queue drained) |
| CYPRESS_RWA | 12 | 1 | complete (queue drained) |
| UMAMI | 5 | 1 | complete (queue drained) |
| REALWORLD | 36 | 3 | complete (queue drained) |
| REACT_BOILERPLATE | 85 | 31 | **INCOMPLETE — 73-minute partial crawl** |

**REACT_BOILERPLATE is not a finished run.** Its final status write has `status: running`,
`current_state` still populated, and **22 states left unexplored in the queue** — it was interrupted
at 73 minutes, not terminated for lack of work. It also holds 197 of the 220 `action-functionality`
rows and 39 of the 57 `functionality` rows, so any aggregate over these five runs is dominated by
one unfinished crawl and should be read as a lower bound. The other four completed, but three of
them discovered exactly one state, so those graphs are single-node.

### Where the artifacts live

| path | contents |
|---|---|
| `runs/2026-07/mongo/` | MongoDB export — `action-functionality.json` (220 docs), `functionality.json` (57 docs, each with a 384-float `all-MiniLM-L6-v2` embedding), `_counts.json` |
| `runs/2026-07/configs-as-run/` | the five configs **as each run actually used them** |
| `runs/2026-07/MANIFEST.md` | full provenance, per-app counts, secret-scan result |
| `runs/2026-07/BENCHMARK_REVISIONS.md` | subject-checkout revisions; the two divergent RWA clones |
| `report/<APP>.json` | state graphs from `save_state_graph()` — `{nodes, edges}` |
| `tmp/status_<APP>.json` | `write_status()` output — timings, loop counter, queue size |

`report/` and `tmp/` remain gitignored as a whole; `.gitignore` carries **narrow per-file
exceptions** for exactly these ten files, so output from a new run is still ignored by default.

Use `runs/2026-07/configs-as-run/` rather than `configs/` for the July targets — `configs/` tracks
live ports and has since moved. In particular `configs/CYPRESS_RWA.json` was repointed from
`http://localhost:3000/` to `http://127.0.0.1:5182/`, because port 3000 no longer serves RWA.

### Restoring the Mongo export

```bash
source .venv/bin/activate
python runs/2026-07/restore_mongo.py            # dry run: reports what it would write
python runs/2026-07/restore_mongo.py --apply    # writes
```

Reads `MONGODB_URI` (default `mongodb://localhost:27017`), database `myDatabase`. The export is
`bson.json_util` extended JSON, so `_id` round-trips as a real `ObjectId` and the `func_pointer`
references from `action-functionality` into `functionality` stay valid. The script verifies document
counts and `_id` uniqueness before writing, and **replaces existing rows for the five apps it
covers**.

### Starting a run

A subject must already be serving before AutoE2E starts; `main.py` navigates straight to
`driver.base_url` and has no service-startup step of its own. Bring the subject up first (see *The
five-subject harness* below), then:

```bash
source .venv/bin/activate
APP_NAME=TODOMVC python main.py          # or set APP_NAME in .env
```

`APP_NAME` must match a file in `./configs` (`configs/TODOMVC.json` → `APP_NAME=TODOMVC`). The crawl
runs until its queue empties, with no built-in cap; `SIGINT`/`SIGTERM` is handled — it finishes the
current action, saves the state graph to `report/<APP>.json`, and writes final status.

### The five-subject harness

Everything needed to bring the five 2026-09 subjects up lives in this repository: the reset/seed
scripts are vendored under `tools/` (see *Vendored reset/seed tools* below), and the launch,
port, health and env facts are recorded here. The subject checkouts themselves are external —
they are large git clones and are referenced by revision, not vendored.

Subject checkouts are rooted at `/Users/stephenhe/Projects/new-benchmark-repos/<subject>`. All five
revisions below were confirmed against the live checkouts on 2026-09-04.

| subject | revision | port | base URL | AutoE2E config | health timeout | auth |
|---|---|---:|---|---|---:|---|
| TodoMVC | `7d727bc458ed` | 5180 | `http://127.0.0.1:5180/` | `TODOMVC` | 30 s | none |
| Keystone-blog | `a92fd4492135` | 3200 | `http://127.0.0.1:3200/` | `KEYSTONE_BLOG` | 180 s | none |
| Epic-stack | `faaa21779c66` | 3000 | `http://127.0.0.1:3000/` | `EPIC_STACK` | 120 s | `kody` / `kodylovesyou` |
| RWA | `6486a7efed0c` | 5182 (+3001 API) | `http://localhost:5182/` | `CYPRESS_RWA` | 30 s | `Heath93` / `s3cret` |
| Bangle-io | `09e9b794e71b` | 5173 | `http://127.0.0.1:5173/` | `BANGLE_IO` | 90 s | none |

Launch commands are quoted from the harness registry
`general-agent-eval/resources/scripts/services.json` (`run` field, `${PORT}` substituted).
`general-agent-eval/resources/scripts/run-with-service.sh` is the wrapper that builds, starts and
health-gates a service before handing off. Health check is `GET <base URL>` for every subject.

To check all five at once — configs, reachability, application identity, MongoDB, reset sources,
and that AutoE2E loads with no LLM credential present:

```bash
source .venv/bin/activate
python tools/preflight.py            # exits non-zero if anything blocking fails
```

It starts nothing and crawls nothing. Identity matching matters: a port answering is never proof
of identity, since a stale clone on a recycled port answers happily as the wrong application.

#### TodoMVC

    cd .../todomvc
    npx vite --port 5180 --host 127.0.0.1

- **Build:** none. **Required env:** none. **Auth:** none.
- **Reset:** no server-side state — state is browser `localStorage`. AutoE2E's Chrome is started
  without `--user-data-dir`, so every run gets a fresh temporary profile and begins empty. There is
  no reset script and none is needed.
- **Pitfall:** the registry command has no `--strictPort`, so if 5180 is taken Vite silently binds
  the next free port. Confirm the listening process's working directory, not just that the port
  answers.

#### Keystone-blog

    cd .../keystone/examples/usecase-blog
    env PORT=3200 npx keystone dev

- **Build:** none (pnpm workspace; dependencies installed at the monorepo root).
- **Required env:** `PORT`, set by the command above. **Auth:** none — this example has no
  authentication.
- **Reset:** `bash tools/ensure_snapshots.sh && bash tools/keystone_blog_reset.sh` (directory
  overridable via `KEYSTONE_BLOG_DIR`). Restores `keystone-example.pristine.db` over the live
  database and clears `-shm`/`-wal`. The snapshot itself is untracked in the subject repo, so
  `ensure_snapshots.sh` installs it from this repository's committed fixture when absent.
- **Pitfalls:** must be launched from the example directory — it resolves its Prisma client through
  the monorepo's `myprisma` alias, so starting from the repo root fails. First boot migrates and
  rebuilds the Admin UI, which is why the health timeout is 180 s, the longest of the five. The repo
  declares `pnpm@11.5.2`; 11.9.0 is what is on PATH here.

#### Epic-stack

    cd .../epic-stack
    NODE_ENV=production MOCKS=true node index.ts

- **Build:** `npm run build` (already performed on host, along with `prisma migrate deploy` and
  `prisma generate --sql`).
- **Required env:** `NODE_ENV=production` **and** `MOCKS=true` — both are required by the registry.
  The server reads `PORT` from the environment.
- **Auth:** seeded user `kody` / `kodylovesyou`, applied automatically by the `FormLogin` lifecycle hook in `configs/EPIC_STACK.json`.
- **Reset:** `bash tools/ensure_snapshots.sh && bash tools/epic_stack_reset.sh` (directory
  overridable via `EPIC_STACK_REPO`). Restores `prisma/pristine.db` over `prisma/data.db` and
  removes `-shm`/`-wal` plus `other/cache.db`. `prisma/pristine.db` is **untracked in the subject
  checkout**, so it is committed here as `harness/fixtures/epic-stack/pristine.db` and
  `ensure_snapshots.sh` installs it when missing — the snapshot cannot be regenerated
  deterministically, because `prisma/seed.ts` uses faker.
- **Pitfalls:** the repo's own scripts wrap `node` in `cross-env`, a local devDependency that is not
  on PATH for a plain service shell, which is why the command is bare `node index.ts` with the
  environment set externally. Port 3000 has previously been occupied by a baseline clone of this
  same app with an identical page title, so confirm the listening process's working directory.

#### RWA (cypress-realworld-app)

    bash tools/rwa_up.sh                 # web 5182, api 3001, both health-gated
    bash tools/rwa_up.sh --reset         # reseed data/database.json first
    bash tools/rwa_up.sh --down          # stop both halves

- **Build:** none (Yarn 1). **Required env:** none — the script sets what the two halves need.
- **Base URL:** `http://localhost:5182/` — **the `localhost` name, not `127.0.0.1`** (see below).
- **Auth:** `Heath93` / `s3cret`, applied automatically by the `FormLogin` lifecycle hook in `configs/CYPRESS_RWA.json`.
- **Reset:** `--reset` copies `data/database-seed.json` over `data/database.json`. This is the one
  subject whose reset is a plain file copy rather than a snapshot restore.
- **Health:** the script gates **both** halves on real identity strings, not a sleep — the API's
  `GET /` must return `Cypress Realworld App - backend` (backend/app.ts:98) and the frontend's `/`
  must return `Cypress Real World App`. It then preflights CORS before reporting READY.

**Why this needs a script.** RWA is the only subject where the two halves resolve their ports by
different mechanisms, and they can silently disagree:

| half | reads | consequence |
|---|---|---|
| frontend | `loadEnv(mode, cwd, "VITE")` in `vite.config.ts` — `.env` **and `.env.local`, the latter winning**; inlined at config time via `define: { "process.env": env }` | ignores the shell entirely |
| backend | `require("dotenv").config()` in `backend/app.ts` — **only `.env`**, and never overrides an existing environment variable | honours the shell |

An untracked `.env.local` left behind by an earlier full-stack helper (`PORT=6182`,
`VITE_BACKEND_PORT=6183`) therefore pointed the frontend at 6183 while the backend defaulted to
`.env`'s 3001 — and both ports were dead. `tools/rwa_up.sh` owns both sides: it writes
`.env.local` for the frontend (backing up any pre-existing one, since it is untracked and
unrecoverable) and passes the ports in the environment for the backend.

**Two failure modes worth knowing**, because both leave a *healthy-looking* service that cannot
work:

1. Starting the API without `PORT=<web port>` in its environment. `backend/app.ts:31` sets
   `origin: http://localhost:${frontendPort}` from `process.env.PORT`, and `.env` pins `PORT=3000`,
   so the API answers health checks while returning
   `Access-Control-Allow-Origin: http://localhost:3000` and refusing every browser call.
2. Loading the page as `http://127.0.0.1:5182`. The CORS allow-list is a **single literal origin on
   the `localhost` hostname**, so `127.0.0.1` is a different origin and every API request is
   blocked — which is why `configs/CYPRESS_RWA.json` uses `http://localhost:5182/`.

Verified end to end with a real browser: `POST /login` → 200, `/notifications` → 200,
`/graphql` → 200, session established, zero failed requests and zero CORS errors.

#### Bangle-io

    cd .../bangle-io/packages/tooling/browser-entry
    npx vite --configLoader runner --port 5173 --host 127.0.0.1

- **Build:** none (pnpm workspace). **Required env:** none. **Auth:** none.
- **Seed:** runs from this repository, no other checkout required:

      python tools/bangle_seed_state.py --base-url http://127.0.0.1:5173 \
          --out harness/state/bangle-io-baseline.json

  (also `--workspace`, default `ugx-baseline`). It drives the app's own creation flow with
  playwright and writes a 900-byte baseline. The capture is **deterministic** — two consecutive
  runs are byte-identical, because the script pins the volatile fields — and the result is
  committed at `harness/state/bangle-io-baseline.json`, so the baseline is recoverable without
  re-running the seed.
- **Pitfalls:** must be launched from the `browser-entry` package — the
  `pnpm -r --filter … --` form does not forward `--host`/`--port`, and Vite then binds IPv6
  localhost only while the readiness gate polls 127.0.0.1. Port 5173 is Vite's default, so it
  collides with any other Vite dev server on the machine. The app is **state-gated**: with an empty
  IndexedDB it renders only "No workspace selected / Create a workspace to get started". Because
  AutoE2E gets a fresh Chrome profile per run, its database is always empty unless seeded first.
  The router is hash-based (`/ws#route=ws-home&wsName=<name>`), not the `/ws/<name>` path the route
  constants suggest; `configs/BANGLE_IO.json` targets the app root rather than the harness's
  workspace entry URL, because a fresh profile has no such workspace.

#### Node version

`node v25.9.0` is on PATH. Epic-stack declares `engines.node ^22.18.0`, and RWA declares
`^22.0.0 || ^24.0.0` with `.nvmrc` `22.20.0` — both narrower than what is installed. The live
services were verified running under v25.9.0 and healthy, so the constraint is advisory for
starting them; a fresh dependency install may still warn or refuse.

### Vendored reset/seed tools

`services.json` refers to three deterministic-reset scripts as `tools/...` "in the explorer repo",
but they are **absent from `/Users/stephenhe/Projects/ui-graph-explorer/tools/`**, the checkout that
note reads as naming. They live in `ui-graph-explorer-integration` and are vendored here, so the
harness needs no other research checkout at runtime:

| vendored path | upstream commit | role |
|---|---|---|
| `tools/epic_stack_reset.sh` | `bb9da86187ef022d5fed5ab6c2d832d4b83b0a9a` | restore `prisma/data.db` |
| `tools/keystone_blog_reset.sh` | `bb9da86187ef022d5fed5ab6c2d832d4b83b0a9a` | restore `keystone-example.db` |
| `tools/bangle_seed_state.py` | `94e2734960ebef93c0e9b5900b788c2c3b7fab5c` | capture the IndexedDB workspace baseline |
| `tools/idb_export_js.py` | `b07e8a846e8d9ec6c34ecf2a68efb9d528eb5879` | the one constant the seed script needs |

Upstream repo `git@github.com:stephenhe1/UI-Graph-Explorer.git`, local checkout
`/Users/stephenhe/Projects/ui-graph-explorer-integration`. Provenance is pinned to **per-file
commits**, not that checkout's HEAD, which moves. **Upstream is authoritative** — re-sync from those
commits rather than editing the copies.

The two shell scripts are byte-identical to their upstream commits apart from a provenance header.

`tools/bangle_seed_state.py` differs by **two lines**, recorded in its own header. Upstream it did:

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from ui_graph.restoration import _IDB_EXPORT_JS

`<script dir>/../src` exists in the upstream repo but not here, so the script could not run at all
from AutoE2E; and importing the real `ui_graph.restoration` would pull in structlog and the rest of
that package for the sake of one constant. That constant is a self-contained JavaScript source
string with no Python dependencies, so it alone is vendored as `tools/idb_export_js.py` (verified
byte-identical to upstream) and the import now resolves to it. Observable behaviour is unchanged:
the same JS is evaluated in the page.

Bangle-io's seeding therefore no longer depends on another checkout. Verified by running it from
this repository against the live app and getting byte-identical output twice.

### July-as-run configs

Two independent checkouts of the Cypress RealWorld App exist, at different revisions:

| path | revision | role |
|---|---|---|
| `benchmark/cypress-realworld-app` | `bdf6169` | the July `CYPRESS_RWA` run's target |
| `.../new-benchmark-repos/cypress-realworld-app` | `6486a7e` | the five-subject harness target, port 5182 |

`6486a7e` is a direct ancestor of `bdf6169`, exactly one commit behind; that commit is a
`@percy/cypress` devDependency bump, so the two are equivalent for application behaviour.

The distinction that matters is **which config points where**:

- `runs/2026-07/configs-as-run/CYPRESS_RWA.json` targets `http://localhost:3000/` — the original
  July checkout under `benchmark/`. This is what the historical run recorded in `runs/2026-07/`
  actually used, confirmed by the config's mtime predating the run's start.
- `configs/CYPRESS_RWA.json` targets `http://127.0.0.1:5182/` — the `new-benchmark-repos` clone.
  It was repointed on 2026-09-04 because port 3000 now serves Epic-stack, not RWA.

A `CYPRESS_RWA` run made today therefore exercises a **different clone** than the July run. Use
`runs/2026-07/configs-as-run/` when reproducing the July numbers, and `configs/` for new runs.

### Lifecycle hooks

`lifecycle.on_visit` used to be parsed by `LifecycleConfig` and read by nothing. It now runs, once,
in `initialize_variables()` — after the first navigation and **before** the initial state is
captured. That placement matters: the whole crawl shares one browser, because `load_state()`
re-navigates to `base_url` for each state but never restarts Chrome, so a session cookie or an
IndexedDB record established by a hook persists for the entire run.

A spec entry is `[module, ClassName]` or `[module, ClassName, {params}]`. The two-element form still
parses, so old configs are unaffected. Use `""` or `"autoe2e"` as the module for a built-in. A hook
that raises **aborts the crawl** — deliberately, because crawling a logged-out application produces
a confidently wrong result, which is worse than stopping.

**`FormLogin`** authenticates through the application's own form, so nothing about the auth path is
bypassed or assumed. It verifies the result via `success_selector` or `success_url_excludes` and
raises if it cannot confirm; without one of those it warns that the login is UNVERIFIED. Credentials
may be written as `${ENV_VAR}` to read from the environment — the committed values are the subjects'
public fixture credentials, which is what makes a run reproducible.

    ["autoe2e", "FormLogin", {
      "url": "/login",
      "username_selector": "#login-form-username",
      "password_selector": "#login-form-password",
      "submit_selector": "#login-form button[type=submit]",
      "username": "kody", "password": "kodylovesyou",
      "success_url_excludes": "/login"
    }]

**`ClientState`** seeds browser-local state from a baseline captured by
`tools/bangle_seed_state.py`, applying `local_storage` and then importing `indexed_db` through the
vendored `autoe2e/crawler/lifecycle/idb_js.py`, and finally navigating to the baseline's landing URL.

    ["autoe2e", "ClientState", { "baseline": "harness/state/bangle-io-baseline.json" }]

Configured for three subjects: `EPIC_STACK` and `CYPRESS_RWA` log in; `BANGLE_IO` seeds its
workspace. Verify without crawling:

```bash
python tools/verify_hooks.py                 # all three
python tools/verify_hooks.py EPIC_STACK      # one
```

It runs the same `Config`, driver and `run_hooks` that a crawl would, then stops — so a pass means
the pre-crawl phase works, with no LLM spend.

### Browser configuration

The `browser` section of a subject config. Chrome used to be hardcoded headed with
`detach: True`, which opened a visible window per run and left the browser alive after the
driver exited.

| key | default | meaning |
|---|---|---|
| `headless` | `false` | run Chrome with `--headless=new` |
| `detach` | `false` | leave the browser running after the driver exits — debugging only |
| `page_load_timeout` | `30` | seconds, passed to `set_page_load_timeout` |
| `implicit_wait` | `5` | seconds, passed to `implicitly_wait` |
| `window_size` | `"1920,1080"` | `--window-size`; pinned because headless otherwise picks a small viewport, which changes which elements count as visible and therefore which actions are discovered |

All five experiment configs declare the experiment profile:

```json
"browser": { "headless": true, "detach": false }
```

`detach` now defaults to **false**, a deliberate change from the old hardcoded `true`: a detached
browser survives `driver.quit()` and leaks a process per run. Debugging can still ask for
`{"headless": false, "detach": true}` explicitly.

`driver.quit()` is guaranteed. `main.py` tears down in a `finally` block and catches
`BaseException`, so a `KeyboardInterrupt` reaches teardown instead of skipping it;
`shutdown_driver_container()` is idempotent, never raises, and clears the singleton.

    python tools/browser_smoke.py                    # launch, navigate, tear down, check for leaks
    python tools/browser_smoke.py --config TODOMVC   # use a subject's real profile

It detects leftovers by diffing the process table around the launch rather than counting Chrome
globally — a developer machine has plenty of unrelated Chrome processes, so a global count would
prove nothing.

### Crawl budget

The `crawl` section. A run stops as soon as **any** configured limit is reached. Every limit
defaults to `null` (unlimited), which is the behaviour before budgets existed, so an older config
is unaffected.

| key | default | meaning |
|---|---|---|
| `max_actions` | `null` | stop once this many actions have been executed |
| `max_states` | `null` | stop once this many states have been discovered |
| `max_wall_seconds` | `null` | stop once this much wall-clock time has elapsed |

Limits are **inclusive** and checked *before* each action, so a declared budget is never
overshot. Non-positive values are rejected at config-parse time.

All five experiment configs declare the same budget:

```json
"crawl": { "max_actions": 500, "max_states": 100, "max_wall_seconds": 3600 }
```

**These three numbers are provisional.** They were chosen so the mechanism is exercised and the
five subjects are directly comparable, not from any analysis of how much exploration is
scientifically adequate. The only datapoint available is the July `REACT_BOILERPLATE` run, which
reached 85 actions and 31 states in 4380 s and was still going, so on a large subject
`max_wall_seconds` is the limit that binds first and the other two act as guards. Set them
deliberately before the real evaluation.

#### Graceful stop

Reaching a budget is a declared stopping rule, not an error. On exhaustion the run:

1. stops scheduling new exploration work — it breaks out of the action loop and the state loop,
   so nothing further is dequeued or explored;
2. keeps everything produced so far, in MongoDB and in the state graph;
3. persists `report/<APP>.json` and `tmp/status_<APP>.json` normally, in the `finally` block;
4. closes the browser via `shutdown_driver_container()`;
5. exits **0**.

Results are persisted *before* the browser is closed, so a failure to quit cannot cost the run's
output. The exploration algorithm itself is unchanged — the budget only decides whether more work
is scheduled.

`tmp/status_<APP>.json` records a real terminal status. It previously only ever said `running` or
`error`, which is why a finished July run is indistinguishable from one that died mid-flight —
those files say `"status": "running"` with `current_state: "DONE"`.

| status | exit code | meaning |
|---|---|---|
| `completed` | 0 | the queue drained |
| `budget_exhausted` | 0 | a declared limit was reached |
| `interrupted` | 130 | SIGINT/SIGTERM, or `KeyboardInterrupt` |
| `failed` | 1 | an exception; `error` carries the message |

Alongside it: `budget_triggered` (which limit fired, else `null`), `budget` (the limits in
force), `actions_executed`, `states_discovered` and `elapsed_seconds`. `loop_counter` is kept as
an alias of `actions_executed` so tooling that reads the older files still works.

The mapping lives in `autoe2e/crawler/budget.py::classify_outcome`, kept as a pure function so
the contract is unit-tested rather than buried in a script.

### Tests

```bash
source .venv/bin/activate
python -m pytest tests -q
```

43 focused tests covering budget evaluation and the outcome/exit-code contract
(`tests/test_crawl_budget.py`), Chrome option construction without launching a browser
(`tests/test_browser_config.py`), and config-section parsing including the ordering invariants in
`main.py` (`tests/test_config_sections.py`). None of them needs a browser, a subject or an LLM
credential.

### Known limitations affecting reproducibility

- **`on_state_discovery` is still inert.** `lifecycle.on_visit` now runs (see *Lifecycle hooks*),
  but `on_state_discovery` is parsed and read nowhere. Configs leave it empty.
- **Form values are still LLM-generated.** Outside the login handled by a hook,
  `create_form_filling_values` sees only a form's `outerHTML`, so it cannot know
  domain-specific valid values.
- **Fresh browser profile per run.** `autoe2e/browser/driver.py` starts Chrome without a
  `--user-data-dir`, so `localStorage` and IndexedDB begin empty every run. Subjects that gate their
  UI on client state (bangle-io renders only "Create a workspace to get started" with an empty
  database) present only that empty state unless seeded first.
- **One WebDriver per process.** `DriverContainer` is an `AbstractSingleton`, so
  `initialize_driver` returns the same browser for the life of the interpreter. `main.py` crawls a
  single `APP_NAME` per run so this is fine there, but a script handling several subjects must fork
  per subject — `tools/verify_hooks.py` does.

### LLM credential

`autoe2e/llm_api_call.py` resolves the key once, lazily, in this order:

1. `LITELLM_API_KEY` from the environment (`.env` is loaded via `python-dotenv`);
2. failing that, `op read op://Employee/API Credentials/credential` via the 1Password CLI;
3. failing that, `RuntimeError` — raised on **first use**, not at import.

`.env.example` carries the variable with an empty value. **The real key is never committed**; `.env`
itself is gitignored (`.gitignore:123`). `python tools/preflight.py` reports only whether a key is
*present*, never its value, and does not invoke `op`.

`main.py` resolves the credential **before** anything slow or destructive, in particular before the
`delete_many` calls that clear the previous run's rows for this app. Those deletes used to be the
first statements in the file, so a typo in `APP_NAME`, a dead service, a missing credential or a
failed login destroyed the previous run's output and only then failed — and nothing writes those
rows to disk, so they were the only copy.

Because models and chains are constructed lazily (`_LazyModel` / `_LazyChain`), importing AutoE2E
and parsing every config works with no credential at all — verified by preflight, which imports
`llm_api_call`, `mongo_utils`, `infer_utils` and `loop_utils` and parses all 15 configs with
`LITELLM_API_KEY` unset. A missing key blocks the **first LLM call of a crawl**, nothing earlier.

### Repository data and provenance

- **`dataset_repos.json`** — 353 `{repo, url}` records: the candidate repository pool the study's
  subjects were drawn from, including TodoMVC, Keystone, Epic-stack, RWA, Bangle-io and umami. No
  duplicate URLs, every record well-formed. It is referenced by no code, so it is committed as
  provenance data rather than as an input. It is byte-identical to an untracked copy in
  `general-agent-eval`, so this is now the preserved copy.
- **`benchmark/dimeshift/dimeshift`** — a submodule pinned to
  `440898e8e48b9a85f4d3c7dfa374e4abd7e27423` of `https://github.com/jeka-kiselyov/dimeshift.git`.
  That is the upstream's `master` head, and the same short SHA that names the benchmark's Docker
  image tag `webappdockers/dimeshift:440898e`, so the pin records which application revision the
  image under test was built from. The application runs from that image, never from a source
  checkout, so the submodule is deliberately left uninitialised — `git submodule status` showing a
  `-` prefix is the expected state. Until 2026-09-04 the gitlink had **no `.gitmodules` entry** and
  so could not be resolved at all; the mapping was added without changing the recorded commit. See
  `benchmark/dimeshift/README.md`.

## LLM Prompts
The prompts used for different parts of our workflow is available in `./autoe2e/prompts.py` file. We use the following prompt for context extraction:

> Given the provided information about a webpage, your task is to provide a brief and abstract description of the webpage's primary purpose or function.
> Output Guidelines:
> * Brevity: Keep the description concise (aim for 1-2 sentences).
> * Abstraction: Avoid specific details or variable names. Use general terms to describe the content and function. (Example: Instead of "a page showing results for searching for a TV," say "a page displaying search results for a product query.")
> * Focus on Purpose: Prioritize describing the main intent of the page. What is it designed for the user to do or learn?
> * No Extra Explanations: Just provide the context. Avoid adding commentary or assumptions.


and the following for feature extraction:


> Given a webpage's purpose and content (webpage_context), the outerHTML of an action element (action_element), and optionally the user's last action that led to this state, your task is to infer the most likely functionalities associated with that action element.
> These functionalities should be user-centric actions that produce measurable outcomes within the application, are testable through E2E testing, and are essential to the presence of the action element.
> Output Format:
> Your is enclosed in two tags:
> \<Reasoning>:
> - An enumerated list of at most five functionalities potentially connected to the element.
> - For each functionality, answer the following questions concisely:
>     1. Would developers write E2E test cases for this in the real world? It should be non-navigational, not menu-related, and not validation.
>     2. Is the functionality a final user goal in itself or is it always a step in doing something else?
>     3. Is this overly abstract/vague? If so, break it down into more testable sub-functionalities.
> - Avoid repeating the questions in your responses every time.
> \<Response>:
> - A JSON array of objects, each containing:
>     - probability: (0.0 to 1.0) Likelihood of this functionality exists.
>     - feature: A concise description of the user action (e.g., "add item to cart").
> - Sorted by probability in descending order.
> - Parsable by `json.loads`.
> - Can be an empty array if no valid functionalities are found.


Furthermore, the baseline prompts are available in `./baseline-prompts.md`.

## Subjects
The subjects used in our evaluations are available in `./benchmark` folder. Furthermore, the server created for tracking the execution of features is available in `./benchmark/_log-server` folder. You need to have a `Redis` server installed and running to be able to use the server.

To run the server:

```bash
cd benchmark/_log-server

pip install -r requirements.txt

flask --app extract.py --debug run
```

### Server Endpoints
The server has the following endpoints:

1. `/start-evaluate/<app-name>`: Start the coverage evaluation for the given application.
2. `/end-evaluate`: End the coverage evaluation for the given application. It will return the coverage rate.

To test the server, you can run the `PetClinic` application located in `./benchmark/pet-clinic` and use the server.