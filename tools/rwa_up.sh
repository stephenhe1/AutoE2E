#!/usr/bin/env bash
# Bring the Cypress RealWorld App up FULL-STACK and health-gate both halves.
#
# Why this exists
# ---------------
# services.json starts RWA frontend-only: "Frontend-only mode (no API backend); app renders
# login/signup UI without backend." With no API, nothing persists and the app renders its
# login/signup screens against a dead backend. The harness's own arm drivers start the API
# separately and then just `sleep 20` -- an un-gated wait that reports success whether or not the
# API ever came up.
#
# Worse, the two halves resolve their port DIFFERENTLY, and can silently disagree:
#
#   frontend  vite.config.ts -> loadEnv(mode, cwd, "VITE"), so it reads .env AND .env.local,
#             with .env.local taking PRECEDENCE. The value is inlined into the bundle at
#             config time via `define: { "process.env": env }`, and src/machines/*.ts build
#             `http://localhost:${backendPort}/...` from it. The SHELL environment is ignored.
#   backend   backend/app.ts calls require("dotenv").config(), which reads ONLY .env and does
#             NOT override variables already in the environment. So it honours the shell.
#
# A leftover `.env.local` (PORT=6182, VITE_BACKEND_PORT=6183, written by an earlier full-stack
# helper and untracked in the subject repo) therefore pointed the frontend at 6183 while the
# backend defaulted to .env's 3001. Both ports were dead. This script removes that class of
# failure by owning both sides of the wiring explicitly.
#
# What it does
#   1. writes .env.local so the FRONTEND bakes in the API port this script actually starts
#      (backing up any pre-existing .env.local once, since it is untracked and unrecoverable)
#   2. starts the API with VITE_BACKEND_PORT in the shell so the BACKEND binds the same port
#   3. health-gates the API on a REAL liveness endpoint -- GET / must return the backend's own
#      identity string -- polling to a deadline instead of sleeping
#   4. starts the frontend and health-gates it on its own identity
#   5. asserts the two agree before declaring success
#
# Usage:
#   bash tools/rwa_up.sh                       # web 5182, api 3001
#   bash tools/rwa_up.sh --reset               # reseed data/database.json first
#   bash tools/rwa_up.sh --web-port N --api-port N
#   bash tools/rwa_up.sh --down                # stop both halves
set -uo pipefail

REPO="${RWA_REPO:-/Users/stephenhe/Projects/new-benchmark-repos/cypress-realworld-app}"
WEB_PORT=5182
API_PORT=3001
RESET=0
DOWN=0
API_DEADLINE=90
WEB_DEADLINE=60

# The string backend/app.ts:98 returns from GET / . Matching it proves the process answering
# is the RWA API and not some other service that inherited the port.
API_IDENTITY="Cypress Realworld App - backend"
WEB_IDENTITY="Cypress Real World App"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --web-port) WEB_PORT="${2:?}"; shift 2 ;;
        --api-port) API_PORT="${2:?}"; shift 2 ;;
        --reset)    RESET=1; shift ;;
        --down)     DOWN=1; shift ;;
        *) echo "[rwa] unexpected argument: $1" >&2; exit 2 ;;
    esac
done

[ -d "$REPO" ] || { echo "[rwa] no such repo: $REPO" >&2; exit 1; }

# Only ever kill a listener we can prove belongs to this subject checkout. A port answering is
# never sufficient evidence of identity -- a stale clone on a recycled port answers happily as
# the wrong application.
stop_ours() {
    local port="$1" label="$2" pid cwd
    pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1)"
    [ -z "$pid" ] && return 0
    cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1)"
    case "$cwd" in
        "$REPO"|"$REPO"/*)
            echo "[rwa] stopping existing $label on :$port (pid $pid, cwd $cwd)"
            kill "$pid" 2>/dev/null
            for _ in $(seq 1 20); do
                kill -0 "$pid" 2>/dev/null || return 0
                sleep 0.25
            done
            kill -9 "$pid" 2>/dev/null ;;
        *)
            echo "[rwa] REFUSING to touch :$port -- pid $pid is not this subject (cwd: ${cwd:-unknown})" >&2
            return 1 ;;
    esac
}

if [ "$DOWN" = "1" ]; then
    stop_ours "$API_PORT" "API" || exit 1
    stop_ours "$WEB_PORT" "frontend" || exit 1
    echo "[rwa] down"
    exit 0
fi

cd "$REPO" || exit 1

if [ "$RESET" = "1" ]; then
    if [ ! -f data/database-seed.json ]; then
        echo "[rwa] missing data/database-seed.json; cannot reset" >&2; exit 1
    fi
    cp data/database-seed.json data/database.json
    echo "[rwa] reseeded data/database.json ($(wc -c < data/database.json | tr -d ' ') bytes)"
fi

# (1) frontend port wiring. .env.local outranks .env for Vite, so this file -- not the shell --
# is the only way to tell the frontend which API port to call.
if [ -f .env.local ] && [ ! -f .env.local.harness-backup ]; then
    cp .env.local .env.local.harness-backup
    echo "[rwa] backed up pre-existing .env.local -> .env.local.harness-backup"
    echo "[rwa]   it contained: $(tr '\n' ' ' < .env.local.harness-backup)"
fi
printf 'PORT=%s\nVITE_BACKEND_PORT=%s\n' "$WEB_PORT" "$API_PORT" > .env.local
echo "[rwa] wrote .env.local: PORT=$WEB_PORT VITE_BACKEND_PORT=$API_PORT"

# Restart both halves: the frontend inlines the API port at config time, so an already-running
# dev server is still carrying whatever the previous .env.local said.
stop_ours "$API_PORT" "API" || exit 1
stop_ours "$WEB_PORT" "frontend" || exit 1

mkdir -p "$REPO/.harness-logs"

# (2) start the API. The shell value wins over .env because dotenv does not override.
#
# BOTH ports must be passed. VITE_BACKEND_PORT decides which port the API binds. PORT decides
# its CORS allow-list: backend/app.ts:31 sets `origin: http://localhost:${frontendPort}` from
# process.env.PORT, and .env pins PORT=3000. Passing only VITE_BACKEND_PORT yields a live API
# that answers health checks but rejects every browser call with
# `Access-Control-Allow-Origin: http://localhost:3000`, which is how this failure hides: the
# service looks healthy and the app still cannot log in.
#
# Note the allow-list is a single literal origin on the `localhost` hostname, so the page must
# be loaded via http://localhost:$WEB_PORT. Loading it via 127.0.0.1 is a DIFFERENT origin and
# is refused, even though both names reach the same server.
PORT="$WEB_PORT" VITE_BACKEND_PORT="$API_PORT" nohup yarn start:api \
    > "$REPO/.harness-logs/api.log" 2>&1 &
API_PID=$!
echo "[rwa] API starting (pid $API_PID), log $REPO/.harness-logs/api.log"

# (3) real liveness gate, not a sleep
gate() {
    local url="$1" needle="$2" deadline="$3" label="$4" i body
    for i in $(seq 1 "$deadline"); do
        body="$(curl -sS --max-time 3 "$url" 2>/dev/null)"
        if printf '%s' "$body" | grep -qF "$needle"; then
            echo "[rwa] $label live after ${i}s -- matched identity: $needle"
            return 0
        fi
        sleep 1
    done
    echo "[rwa] $label FAILED to become live within ${deadline}s at $url" >&2
    return 1
}

if ! gate "http://127.0.0.1:$API_PORT/" "$API_IDENTITY" "$API_DEADLINE" "API"; then
    echo "[rwa] --- last 25 lines of api.log ---" >&2
    tail -25 "$REPO/.harness-logs/api.log" >&2
    exit 1
fi

# (4) start and gate the frontend
nohup yarn start:react -- --port "$WEB_PORT" --host 127.0.0.1 \
    > "$REPO/.harness-logs/web.log" 2>&1 &
WEB_PID=$!
echo "[rwa] frontend starting (pid $WEB_PID), log $REPO/.harness-logs/web.log"

if ! gate "http://127.0.0.1:$WEB_PORT/" "$WEB_IDENTITY" "$WEB_DEADLINE" "frontend"; then
    echo "[rwa] --- last 25 lines of web.log ---" >&2
    tail -25 "$REPO/.harness-logs/web.log" >&2
    exit 1
fi

# (5) assert the halves agree
BAKED="$(sed -n 's/^VITE_BACKEND_PORT=//p' .env.local)"
if [ "$BAKED" != "$API_PORT" ]; then
    echo "[rwa] WIRING MISMATCH: frontend baked VITE_BACKEND_PORT=$BAKED but API is on $API_PORT" >&2
    exit 1
fi

# (5b) verify CORS actually admits the frontend origin, by preflighting as the browser would.
ALLOW="$(curl -s -o /dev/null -D - -X OPTIONS "http://localhost:$API_PORT/login" \
    -H "Origin: http://localhost:$WEB_PORT" -H "Access-Control-Request-Method: POST" \
    --max-time 8 2>/dev/null | sed -n 's/[Aa]ccess-[Cc]ontrol-[Aa]llow-[Oo]rigin: *//p' | tr -d '\r')"
if [ "$ALLOW" != "http://localhost:$WEB_PORT" ]; then
    echo "[rwa] CORS MISMATCH: API allows '${ALLOW:-<none>}' but the frontend origin is http://localhost:$WEB_PORT" >&2
    echo "[rwa] the API was probably started without PORT=$WEB_PORT in its environment" >&2
    exit 1
fi
echo "[rwa] CORS verified: API allows origin $ALLOW"

echo "[rwa] READY"
echo "[rwa]   frontend  http://localhost:$WEB_PORT/   (pid $WEB_PID)  <-- use the localhost name, not 127.0.0.1"
echo "[rwa]   API       http://localhost:$API_PORT/    (pid $API_PID)"
echo "[rwa]   frontend calls the API at http://localhost:$API_PORT (from .env.local)"
