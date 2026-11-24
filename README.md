# AI Chat: multi-turn chat with LiteLLM key fail-over and caching

A small full-stack AI app: React UI, FastAPI backend, SQLite storage, and a LiteLLM gateway that
rotates through a pool of API keys and caches responses. Every assistant reply shows the
request's own metadata (source, model, latency, input and output tokens).

## 1. Live URLs

| Part | URL |
|---|---|
| Frontend | `https://<your-frontend>.vercel.app` |
| Backend | `https://<your-backend>.onrender.com` |
| Health check | `https://<your-backend>.onrender.com/health` |
| Repository | `https://github.com/<you>/<repo>` |

> The backend runs on a free tier that sleeps when idle. The first request after a pause can take about 50 seconds.

## 2. Run locally: with Docker and without

### With Docker (needs Docker Desktop or Docker Engine with Compose v2)

```bash
cp .env.example .env        # then put your real keys in LLM_API_KEYS
make up                     # backend http://localhost:8000, frontend http://localhost:3000
make down                   # stop
```

The SQLite file is stored on the named volume `app_data`, mounted at `/data`, so history survives
`make down` / `make up` and container restarts.

### Without Docker

```bash
# backend (Python 3.12)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export LLM_API_KEYS=key1,key2 LLM_MODEL=gemini/gemini-2.5-flash-lite \
       DATABASE_URL=sqlite:///./app.db ALLOWED_ORIGINS=http://localhost:3000 \
       ENABLE_FAILURE_SIMULATION=true
uvicorn app.main:app --port 8000

# frontend (Node 20), in a second terminal
cd frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev      # http://localhost:3000
```

Tests (no network or keys needed): `cd backend && python -m pytest -q`
Key check (one tiny real call per key): `make check-keys`

### Environment variables

| Variable | Meaning |
|---|---|
| `LLM_API_KEYS` | Comma-separated key pool, at least 2 keys. Ids are `key_1`, `key_2`, ... in order |
| `LLM_MODEL` | LiteLLM model name, default `gemini/gemini-2.5-flash-lite` |
| `DATABASE_URL` | SQLite location, e.g. `sqlite:////data/app.db` |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins |
| `ENABLE_FAILURE_SIMULATION` | `true` enables the `X-Simulate-Failure` header |
| `DEFAULT_SYSTEM_PROMPT`, `CACHE_ENABLED`, `REQUEST_TIMEOUT_SECONDS`, `KEY_COOLDOWN_SECONDS`, `LLM_MAX_TOKENS` | Optional tuning |
| `LLM_MOCK` | Offline mode with canned replies. For tests and keyless demos only |
| `VITE_API_URL` | Frontend, build time: backend URL |

## 3. Design decisions: key fallback, caching, SQLite session storage

**Key fallback.** `LLM_API_KEYS` becomes an ordered pool (`key_1`, `key_2`, ...). For each request the
gateway calls `litellm.completion(..., api_key=key)` with the first key. Any failure (429, quota,
5xx, timeout, auth error, empty completion) moves on to the next key, and the number of failed keys
is returned as `fallback_attempts`. LiteLLM's own retries are turned off (`num_retries=0`) so the
fail-over is fast and the count is exact. If every key fails, the API returns
`503 {"detail": "all providers unavailable"}` and nothing is written to history. A key that really
failed is tried last for `KEY_COOLDOWN_SECONDS`, so a rate-limited key does not slow every request.
Provider error text and keys are never returned to the client or logged; only the key id and the
exception type are.

**Failure simulation.** When `ENABLE_FAILURE_SIMULATION=true`, `X-Simulate-Failure: key_1=429,key_2=500`
(or `*=429`) makes the listed keys behave as failed for that one request. Simulated requests skip the
cache lookup, so failover can be demonstrated even for a message that is already cached, and the answer is
always a real model reply, never an error wrapped in a 200.

**Caching.** LiteLLM's built-in in-memory cache (`litellm.cache = Cache(type="local")`). Its cache key
is the model plus the full message list sent to the LLM (system prompt + history + new message), so
the same first message in a new session is a hit and any different message is a miss. A hit is
detected from LiteLLM's `cache_hit` flag and reported as `LLM_CACHE` with the stored reply, the
stored token usage, `key_id: null` and `fallback_attempts: 0`. The cache lives in process memory, so it
is empty after a restart (the spec allows in-memory). Two offline warm-up calls at startup load
LiteLLM's lazy modules so the first real cache hit is fast.

**SQLite session storage.** The `messages` table follows the required schema, plus an index on
`(session_id, id)` and a small `sessions` table that stores the optional per-session system prompt.
The schema is created on startup. The backend reads the session history, prepends the system prompt,
appends the new message and sends the list to the model. The user message and the reply are saved in
a single transaction only after a successful answer, so a 422 or 503 never leaves partial history.
The database path comes from `DATABASE_URL`; in Docker it is `/data/app.db` on a named volume.

**Tokens and latency.** Tokens come from the provider usage of that one request (system + history +
new message in, completion out); nothing is accumulated. `latency_ms` is measured on the server from
reading the history to finishing the model call, rounded up to whole milliseconds.

**Errors.** Validation problems return FastAPI's 422 `{"detail": ...}`. A catch-all handler returns
`{"detail": "internal server error"}` instead of a stack trace or HTML page. The UI shows 422 and 503
as readable messages inside the chat.

## 4. Verification: how to see failover, cache hits and per-message token usage

Set `API` to your backend (`http://localhost:8000` locally).

```bash
API=https://<your-backend>.onrender.com

# Health
curl -s $API/health

# Live call (LIVE_INFERENCE, key_1, tokens for this request only)
curl -s -X POST $API/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"demo-1","message":"What is the capital of France?"}'

# Cache hit: same first message in a NEW session -> LLM_CACHE, key_id null, same reply, lower latency
curl -s -X POST $API/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"demo-2","message":"What is the capital of France?"}'

# Failover: key_1 "fails" -> answered by key_2, fallback_attempts = 1
curl -s -X POST $API/chat -H 'Content-Type: application/json' -H 'X-Simulate-Failure: key_1=429' \
  -d '{"session_id":"demo-3","message":"Name a famous river in Egypt"}'

# Every key fails -> 503 {"detail":"all providers unavailable"}, nothing saved
curl -s -i -X POST $API/chat -H 'Content-Type: application/json' -H 'X-Simulate-Failure: *=429' \
  -d '{"session_id":"demo-4","message":"This will not be stored"}'

# Validation -> 422
curl -s -i -X POST $API/chat -H 'Content-Type: application/json' -d '{"session_id":"demo-5","message":""}'

# Stored history (oldest first, no system prompt) and the 404 case
curl -s $API/sessions/demo-1/messages
curl -s -i $API/sessions/does-not-exist/messages
```

In the UI: send a message (blue `LIVE_INFERENCE` badge), then click **New chat** and send the exact
same message (amber `LLM_CACHE` badge, lower latency). Open **Session settings** and type
`key_1=429` in the failure field to see `Key: key_2` and `Fallbacks: 1`. Ask a follow-up such as
"What did I just ask?" to confirm the multi-turn memory. Token counts differ per message and never add up.

## 5. Setup Used: your editor and AI tools

- Editor: _(fill in, e.g. VS Code)_
- AI tools: Claude (claude.ai) for scaffolding and review; _(add any others you used)_
- Stack: React 18 + Vite, FastAPI, LiteLLM, SQLite (`sqlite3`), Docker Compose, pytest
- Hosting: Vercel (frontend), Render (backend)

## 6. Bonus features (if any): what you added beyond the requirements and why

- Optional system-prompt field, stored per session in SQLite, so the persona survives page-level follow-ups.
- Failure-simulation field in the UI, so failover can be shown without curl.
- Key cooldown, so a really rate-limited key stops costing a failed call on every request.
- Slow-server hint in the UI ("server may be waking up") for free-tier cold starts.
- New chat button (fresh session id) and extra metadata shown per reply: key id and fallback count.
- 31 backend tests covering contract, cache, failover, 422/503/404, history and restart persistence.

## 7. Deployment guide

**Backend on Render (Docker web service)**
1. Render dashboard, New, Web Service, connect the GitHub repo.
2. Root Directory `backend`, Language `Docker`, Instance type Free.
3. Environment variables: `LLM_API_KEYS`, `LLM_MODEL`, `ENABLE_FAILURE_SIMULATION=true`,
   `ALLOWED_ORIGINS=https://<your-frontend>.vercel.app` (no trailing slash), and
   `DATABASE_URL=sqlite:////data/app.db`.
4. Health Check Path `/health`. Deploy.
5. Persistence: the free tier has no persistent disk, so history resets on redeploy or restart.
   For history that survives restarts, add a Render Disk mounted at `/data` (paid) or deploy on Fly.io with a volume.

**Frontend on Vercel**
1. Import the repo, set Root Directory to `frontend` (framework: Vite).
2. Environment variable `VITE_API_URL=https://<your-backend>.onrender.com`.
3. Deploy, then put the Vercel URL into the backend's `ALLOWED_ORIGINS` and redeploy the backend.

## API summary

| Method and path | Purpose |
|---|---|
| `GET /health` | `{"status":"ok","keys_configured":N,"cache_enabled":true}` |
| `POST /chat` | Body `{session_id, message, system_prompt?}`, returns `{session_id, reply, metadata}` |
| `GET /sessions/{session_id}/messages` | Stored history, oldest first |
