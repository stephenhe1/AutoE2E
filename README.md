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
| RWA | `6486a7efed0c` | 5182 (+3001 API) | `http://127.0.0.1:5182/` | `CYPRESS_RWA` | 30 s | `Heath93` / `s3cret` |
| Bangle-io | `09e9b794e71b` | 5173 | `http://127.0.0.1:5173/` | `BANGLE_IO` | 90 s | none |

Launch commands are quoted from the harness registry
`general-agent-eval/resources/scripts/services.json` (`run` field, `${PORT}` substituted).
`general-agent-eval/resources/scripts/run-with-service.sh` is the wrapper that builds, starts and
health-gates a service before handing off. Health check is `GET <base URL>` for every subject.

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
- **Reset:** `bash tools/keystone_blog_reset.sh` (directory overridable via `KEYSTONE_BLOG_DIR`).
  Restores `keystone-example.pristine.db` over the live database and clears `-shm`/`-wal`.
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
- **Auth:** seeded user `kody` / `kodylovesyou`.
- **Reset:** `bash tools/epic_stack_reset.sh` (directory overridable via `EPIC_STACK_REPO`).
  Restores `prisma/pristine.db` over `prisma/data.db` and removes `-shm`/`-wal` plus
  `other/cache.db`. Note `prisma/pristine.db` is **untracked** in the subject checkout: if it is
  lost it cannot be restored from that repo.
- **Pitfalls:** the repo's own scripts wrap `node` in `cross-env`, a local devDependency that is not
  on PATH for a plain service shell, which is why the command is bare `node index.ts` with the
  environment set externally. Port 3000 has previously been occupied by a baseline clone of this
  same app with an identical page title, so confirm the listening process's working directory.

#### RWA (cypress-realworld-app)

    # frontend
    cd .../cypress-realworld-app && yarn start:react -- --port 5182 --host 127.0.0.1
    # API sidecar, separate process
    cd .../cypress-realworld-app && yarn start:api

- **Build:** none (Yarn 1). **Required env:** none.
- **Auth:** password `s3cret`; the seed database's first user is `Heath93` (the harness resolves the
  username from the live `data/database.json` at scaffold time, falling back to
  `Katharina_Bernier`).
- **Reset:** `cp data/database-seed.json data/database.json`. This is the one subject with no
  vendored script — the reset is a single file copy, performed by the harness arm drivers.
  `data/empty-seed.json` also exists; the harness uses `database-seed.json`.
- **Health:** frontend `GET /` with a 30 s timeout. **The API on 3001 has no health path defined in
  the registry** — the harness simply sleeps 20 s after launching it. Confirm 3001 answers before
  relying on it.
- **Pitfalls:** the registry's `run` starts the **frontend only**; with no API the app renders
  login/signup against a dead backend and nothing persists. The frontend bakes its API URL in at
  build time from `.env` *files* and ignores the shell environment, so exporting
  `VITE_BACKEND_PORT` has no effect and the page keeps calling the committed default of 3001. Two
  checkouts of this application exist at different revisions — see *July-as-run configs* below.

#### Bangle-io

    cd .../bangle-io/packages/tooling/browser-entry
    npx vite --configLoader runner --port 5173 --host 127.0.0.1

- **Build:** none (pnpm workspace). **Required env:** none. **Auth:** none.
- **Seed:** `python tools/bangle_seed_state.py --base-url http://127.0.0.1:5173 --out <path>`
  (also `--workspace`, default `ugx-baseline`). **This script cannot run under this repository's
  virtualenv** — see the limitation note under *Vendored reset/seed tools*.
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

`services.json` refers to these three as `tools/...` "in the explorer repo", but they are **absent
from `/Users/stephenhe/Projects/ui-graph-explorer/tools/`**, the checkout that note reads as naming.
They are vendored here from `ui-graph-explorer-integration` so the harness is self-contained:

| vendored path | upstream commit | reset target |
|---|---|---|
| `tools/epic_stack_reset.sh` | `bb9da86187ef022d5fed5ab6c2d832d4b83b0a9a` | `prisma/data.db` |
| `tools/keystone_blog_reset.sh` | `bb9da86187ef022d5fed5ab6c2d832d4b83b0a9a` | `keystone-example.db` |
| `tools/bangle_seed_state.py` | `94e2734960ebef93c0e9b5900b788c2c3b7fab5c` | IndexedDB workspace baseline |

Upstream repo `git@github.com:stephenhe1/UI-Graph-Explorer.git`, local checkout
`/Users/stephenhe/Projects/ui-graph-explorer-integration`. Each file carries a provenance header and
is otherwise byte-identical to its upstream commit. **Upstream is authoritative** — re-sync from
those commits rather than editing the copies.

**Known limitation — `bangle_seed_state.py` is vendored but not runnable here.** It imports
`playwright` and `ui_graph.restoration._IDB_EXPORT_JS`, and resolves the latter through
`sys.path.insert(<script dir>/../src)`, which in this repository does not exist. Neither dependency
is part of AutoE2E. It runs when invoked with the upstream checkout's interpreter:

    /Users/stephenhe/Projects/ui-graph-explorer-integration/.venv/bin/python \
        tools/bangle_seed_state.py --base-url http://127.0.0.1:5173 --out <path>

So bangle-io's client-state seeding still depends on that external checkout. The two shell reset
scripts have no such dependency and run standalone.

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

### Known limitations affecting reproducibility

- **No authentication support.** `lifecycle.on_visit` / `on_state_discovery` are parsed by
  `autoe2e/crawler/config/lifecycle_config.py` but never read anywhere in the codebase, and form
  values come from an LLM shown only the form's `outerHTML` (`create_form_filling_values`). A crawl
  cannot log in, so login-gated surfaces stay unexplored.
- **Fresh browser profile per run.** `autoe2e/browser/driver.py` starts Chrome without a
  `--user-data-dir`, so `localStorage` and IndexedDB begin empty every run. Subjects that gate their
  UI on client state (bangle-io renders only "Create a workspace to get started" with an empty
  database) present only that empty state unless seeded first.
- **Chrome is not headless** and is created with `detach: True`, so runs open visible windows and
  the browser outlives the process.

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