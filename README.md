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

### Launching a subject and starting a run

A subject must already be serving before AutoE2E starts; `main.py` navigates straight to
`driver.base_url` and has no service-startup step of its own.

The authoritative per-subject launch commands live in the harness registry
`general-agent-eval/resources/scripts/services.json` (`run` field, `${PORT}` substituted), with
`general-agent-eval/resources/scripts/run-with-service.sh` as the wrapper that builds, starts and
health-gates a service before handing off. As recorded there:

| subject | run from | command | port |
|---|---|---|---|
| todomvc | repo root | `npx vite --port 5180 --host 127.0.0.1` | 5180 |
| keystone-blog | `examples/usecase-blog` | `env PORT=3200 npx keystone dev` | 3200 |
| epic-stack | repo root | `node index.ts` (needs `NODE_ENV=production`, `MOCKS=true`) | 3000 |
| cypress-realworld-app | repo root | `yarn start:react -- --port 5182 --host 127.0.0.1` | 5182 |
| bangle-io | `packages/tooling/browser-entry` | `npx vite --configLoader runner --port 5173 --host 127.0.0.1` | 5173 |

Then point a config at it and run:

```bash
source .venv/bin/activate
APP_NAME=TODOMVC python main.py          # or set APP_NAME in .env
```

`APP_NAME` must match a file in `./configs` (`configs/TODOMVC.json` → `APP_NAME=TODOMVC`). The crawl
runs until its queue empties, with no built-in cap; `SIGINT`/`SIGTERM` is handled — it finishes the
current action, saves the state graph to `report/<APP>.json`, and writes final status.

### Required reset / seed scripts (external dependency)

The five 2026-09 subjects need deterministic state resets between runs. `services.json` refers to
these as `tools/...` "in the explorer repo", but they are **absent from
`ui-graph-explorer/tools/`**. They live in a *different* checkout,
`ui-graph-explorer-integration/tools/` (remote `UI-Graph-Explorer.git`), where all three are
tracked:

| script | purpose | invocation |
|---|---|---|
| `epic_stack_reset.sh` | restores a pristine seeded SQLite snapshot (the seed uses faker, so re-seeding is not reproducible) | no arguments; directory via `EPIC_STACK_REPO` |
| `keystone_blog_reset.sh` | restores `keystone-example.pristine.db` | no arguments; directory via `KEYSTONE_BLOG_DIR` |
| `bangle_seed_state.py` | captures the one prerequisite workspace by driving the app's own creation flow | `python tools/bangle_seed_state.py --base-url http://127.0.0.1:5173 --out <path>` (also `--workspace`, default `ugx-baseline`) |

**Treat the harness as not self-contained**: reproducing a reset requires the
`ui-graph-explorer-integration` checkout in addition to `general-agent-eval`, and `services.json`'s
`tools/` paths are relative to a repo it does not name. The July subjects in `benchmark/` used none
of these scripts — they have no reset tooling in this repository.

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