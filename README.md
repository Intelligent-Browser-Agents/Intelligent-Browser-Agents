# Intelligent Browser Agents

Senior Design Project - University of Central Florida

This README is the primary implementation guide for setting up, running, and developing the full repository.

## Table of Contents

1. [Original Project Overview](#original-project-overview)
2. [Current Implementation Highlights](#current-implementation-highlights)
3. [Architecture Overview](#architecture-overview)
4. [Repository Layout](#repository-layout)
5. [Prerequisites](#prerequisites)
6. [Quick Start](#quick-start)
7. [Backend Setup (Database, Env, API)](#backend-setup-database-env-api)
8. [Frontend Setup](#frontend-setup)
9. [Running the System End-to-End](#running-the-system-end-to-end)
10. [Agent Workflow](#agent-workflow)
11. [API and WebSocket Endpoints](#api-and-websocket-endpoints)
12. [Testing](#testing)
13. [Continuous Integration](#continuous-integration)
14. [Troubleshooting](#troubleshooting)
15. [Security Notes](#security-notes)
16. [Contributors](#contributors)

## Original Project Overview

### Overview

Intelligent Browser Agents is a system designed to automate monotonous or repetitive user tasks inside a web browser, introducing a new way for humans to interact with computers. By combining LLM-driven reasoning, browser automation, and a custom frontend + backend pipeline, the system transforms natural-language instructions into executable actions performed on a live browser session.

### Project Motivation

Modern users waste significant time performing routine digital tasks (filling forms, navigating dashboards, downloading files, managing workflows). The goal of this project is to create a platform where users can delegate these interactions to an intelligent agent that understands instructions, plans actions, and executes them visually and safely.

## Current Implementation Highlights

- Streams browser activity to the frontend in near real time.
- Supports human-in-the-loop (HITL) clarifications and approvals during runs.
- Includes account features (register/login/update/delete/forgot password).
- Allows users to store reusable credentials and profile data for automation contexts.
- Uses a modular action execution layer (navigate, click, type, search, scroll, press_key, wait, extract_content).

## Architecture Overview

The system is split into two main apps plus supporting modules:

- Frontend: React + Vite UI for login, dashboard, prompts, chat, and live browser feed.
- Backend API: FastAPI server for auth, session orchestration, HITL routing, and WebSocket streams.
- Agent Runtime: LangGraph workflow inside backend subprocesses.
- Automation Layer: Playwright browser control and ARIA-oriented DOM extraction.
- Storage:
	- PostgreSQL for user auth/profile records.
	- In-memory session maps for active run credentials and HITL queues.
	- Local browser/session artifacts under screenshot/output-style folders.

High-level flow:

1. User submits a task from the dashboard.
2. Frontend opens `/ws/stream` and sends `{"type": "start", "token", "prompt"}` as the first frame.
3. Backend validates the token, loads that user's encrypted credential vault, and starts `src/app.py` as a subprocess, handing the credentials over on stdin.
4. LangGraph agents iterate: orchestrator -> executor -> verifier -> fallback/interaction.
5. Browser frames/logs and HITL messages stream back through WebSocket.
6. User replies (if requested) are forwarded to the running agent.

## Repository Layout

Top-level structure:

- `backend/`
	- `server.py`: FastAPI app, auth endpoints, websocket orchestration, process management.
	- `src/`: LangGraph agent pipeline and Playwright execution modules.
	- `configs/user_db_config.example.yaml`: template for the optional local PostgreSQL override.
	- `tests/`: Unit and integration tests, plus shared fixtures in `conftest.py`.
	- `Makefile`: common setup/test/run shortcuts.
- `frontend/`
	- `src/pages/`: login/register/forgot-password/dashboard pages.
	- `src/components/`: route protection and credential components.
	- `vite.config.js`: dev proxy for `/api` and `/ws` to backend.
- `pyproject.toml`: pytest configuration (import mode, path, markers).
- `requirements.txt` / `requirements-dev.txt`: Python runtime and test dependencies.
- `docs/IMPROVEMENT_PLAN.md`: audited defect list and phased plan of work.
- `README.md`: this repository guide.

## Prerequisites

- Python 3.10+ (3.11 recommended)
- Node.js 18+ and npm
- Docker (recommended for PostgreSQL/Chroma local setup)
- Playwright browser binaries

## Quick Start

From repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements-dev.txt
python -m playwright install chromium
```

`requirements-dev.txt` includes `requirements.txt` plus the test dependencies. For
a runtime-only install use `pip install -r requirements.txt`.

Then complete backend and frontend setup below.

## Backend Setup (Database, Env, API)

### 1. Configure PostgreSQL

Run PostgreSQL via Docker:

```powershell
docker pull postgres
docker run --name some-postgres -e POSTGRES_PASSWORD=mysecretpassword -p 5432:5432 -d postgres
```

Configure the connection with the `DB_*` environment variables described below.

For local development you may instead copy `backend/configs/user_db_config.example.yaml`
to `backend/configs/user_db_config.yaml` and edit it. That path is gitignored, and
environment variables take precedence over it:

```yaml
dbname: "postgres"
user: "postgres"
password: "mysecretpassword"
port: "5432"
host: "127.0.0.1"
```

### 2. Create the `users` table

Connect to Postgres:

```powershell
docker exec -it some-postgres psql -U postgres -d postgres
```

Create table:

```sql
CREATE TABLE users (
		user_id SERIAL PRIMARY KEY,
		username VARCHAR(50) UNIQUE NOT NULL,
		firstname VARCHAR(50) NOT NULL,
		lastname VARCHAR(50) NOT NULL,
		email VARCHAR(50) UNIQUE NOT NULL,
		isverified BOOLEAN NOT NULL,
		createdat TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
		chng_pass BOOLEAN NOT NULL,
		password VARCHAR(255) NOT NULL
);
```

### 3. Set environment variables

Create `.env` in the **repository root** with at least these keys:

```env
OPENAI_API_KEY=
TOKEN_SECRET=
CREDENTIALS_KEY=
EMAIL_ACCOUNT=
EMAIL_PASSWORD=

# Comma-separated. Defaults to the Vite dev server on 5173.
ALLOWED_ORIGINS=http://localhost:5173

# Optional: only needed if you switch AGENT_MODELS to a gemini-* key
GOOGLE_API_KEY=

# Optional: database connection. Defaults to postgres@127.0.0.1:5432/postgres.
DB_NAME=
DB_USER=
DB_PASSWORD=
DB_HOST=
DB_PORT=
```

Generate `CREDENTIALS_KEY` once and keep it stable, or previously saved
credentials become unreadable:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Notes:

- All six agents are assigned OpenAI models in `backend/src/models.py`, so `OPENAI_API_KEY` is required for out-of-the-box agent runs.
- `GOOGLE_API_KEY` is only needed if you change `AGENT_MODELS` to a `gemini-*` key.
- `TOKEN_SECRET` should be long/random in non-dev environments. It signs both access tokens and the short-lived password-reset tokens.
- `CREDENTIALS_KEY` is a Fernet key encrypting the saved-credential vault at rest. Without it, the credential endpoints return 503 rather than storing anything in plaintext.
- `ALLOWED_ORIGINS` sets the CORS allowlist. A wildcard is not accepted, because `allow_origins=["*"]` with `allow_credentials=True` is not a valid combination.
- `EMAIL_ACCOUNT` and `EMAIL_PASSWORD` are needed for forgot-password email sending.
- `BCRYPT_ROUNDS` optionally sets the bcrypt cost factor (default 12). Passwords are hashed with a fresh `bcrypt.gensalt()`, so no salt variable is needed.
- `load_dotenv()` searches upward from the working directory, so a root `.env` is picked up whether you run from the repository root or from `backend/`.

### 4. Optional Chroma service

If you need Chroma running locally for related experiments:

```powershell
docker pull chromadb/chroma
docker run -d -p 8001:8000 chromadb/chroma
```

### 5. Start backend API

From `backend/`:

```powershell
uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

## Frontend Setup

From `frontend/`:

```powershell
npm install
npm run dev
```

Vite dev server proxies:

- `/api` -> `http://localhost:8000`
- `/ws` -> `ws://localhost:8000`

By default, open the URL printed by Vite (commonly `http://localhost:5173`).

## Running the System End-to-End

1. Start backend server in `backend/`.
2. Start frontend dev server in `frontend/`.
3. Register or log in.
4. Open dashboard and submit a prompt.
5. Watch logs + live browser stream.
6. Respond to HITL clarification requests when prompted.

Optional manual subprocess run (debugging only):

```powershell
cd backend
python src/app.py --prompt "Search for the latest UCF news" --port 9000
```

## Agent Workflow

Core workflow is built in `backend/src/main.py` and uses these agents:

- Orchestrator: builds and updates multi-step plans.
- Executor: selects and dispatches browser actions.
- Verifier: evaluates if step completed or fallback is needed.
- Fallback: proposes recovery when execution fails.
- Interaction: delivers final output or requests user clarification.

Execution actions are implemented in `backend/src/execution/` and exposed through a typed dispatcher.

## API and WebSocket Endpoints

Authenticated endpoints expect `Authorization: Bearer <access token>` and return
`401` with a `detail` field when the token is missing, expired, or wrongly scoped.
The acting user is always the token subject; no endpoint accepts a caller-supplied
user id.

### Public REST endpoints

- `POST /api/users/insert/` - register.
- `POST /api/users/login/` - returns `{token}`, or `{resetRequired, resetToken}` when the account is flagged for a password change.
- `POST /api/users/forgot-password` - body `{username}` or `{email}`.
  Always returns the same response so it cannot be used to test whether an account exists.
  Rate limited per client.
- `POST /api/users/change-password` - requires the **reset-scoped** token from login, not an access token.
  Returns a normal access token.

### Authenticated REST endpoints

- `GET /api/users/` - the authenticated user's profile.
- `POST /api/users/update/`
- `DELETE /api/users/delete/` - also removes the credential vault row.
- `POST /api/users/verify/` - confirm the caller's own password.
- `GET /api/users/credentials` - read the decrypted vault.
- `POST /api/users/store-credentials` - encrypt and upsert the vault.
  CVV-like fields are stripped before storage.
- `DELETE /api/users/credentials`
- `POST /api/hitl_reply` - answer the caller's active clarification prompt.

### WebSocket endpoints

Both authenticate with a first frame. Tokens are never query parameters, so they
do not appear in access logs. An unauthenticated socket is closed with code 1008
before any agent process starts.

- `WS /ws/stream`
	- First frame: `{"type": "start", "token": "<access token>", "prompt": "<task>"}`.
	- Streams `FRAME`, `STATUS`, `LOG`, `CLARIFICATION`, and `RESPONSE` messages.
	- Accepts `{"type": "user_hitl_reply", "content": ...}`, `{"type": "abort_run", ...}`, and `{"type": "INPUT", ...}` browser input events.
- `WS /ws/chat`
	- First frame: `{"type": "auth", "token": "<access token>"}`, answered with `{"type": "AUTH_OK"}`.
	- Fallback path for delivering a HITL reply. It does not broadcast.

### Removed in Phase 1

- `POST /api/start_agent` - was broken (launched `src/app.py` with an unsupported `--video_port`, and blocked the event loop with a synchronous `subprocess.run`). Runs start over `WS /ws/stream`.
- `GET /send_logs` - stub whose body was `pass`.
- `GET /api/nuke` - unauthenticated `gc.collect()` debugging leftover.

## Testing

Backend tests are in `backend/tests/`. Pytest configuration lives in the root
`pyproject.toml`, so **run pytest from the repository root**:

```powershell
pytest -q
```

This runs the offline suite: no network, no browser, and no model API key. Agent
LLM calls are replaced with deterministic stubs by `backend/tests/conftest.py`.

Two marker groups are deselected by default:

- `browser` needs a real Chromium instance. It does not need the network.
- `llm` makes billable model API calls.

Run them explicitly:

```powershell
pytest -m browser -v
pytest -m llm -v
pytest -m "" -v
```

Targeted suites:

```powershell
pytest backend/tests/test_server.py -v
pytest -m browser backend/tests/execution -v
```

### The fixture site

Browser tests run against `backend/tests/fixtures/`, served over HTTP on an
ephemeral loopback port by the session-scoped `site` fixture in
`backend/tests/conftest.py`. Nothing in the suite resolves a public hostname, so
the tests are unaffected by network conditions and by the anti-bot interstitials
that real sites serve to automated Chromium.

Take the base URL from the `site` fixture and never hardcode a port:

```python
async def test_something(page, site):
    await page.goto(f"{site}/apply_step1.html")
```

The pages, and what each one exists to exercise:

| Page | Covers |
| --- | --- |
| `apply_step1.html` | Client-side validation that blocks submit; a mask that rewrites typed input |
| `apply_step2.html` | A same-origin iframe, an open shadow root, an upload restricted by `accept` |
| `apply_confirm.html` | The observable end state of the application flow |
| `eeo_frame.html` | The iframe's contents |
| `login.html`, `mfa.html`, `account.html` | Sign-in with a second factor, and its failure paths |
| `listings.html` | Three links that share the accessible name "Apply"; a search box |
| `hazards.html` | A button under an overlay, a disabled control, a truncating field |
| `tall_page.html` | Enough height for a scroll to be measurable |
| `job_application.html` | The original single-page form, addressed by `file://` in `test_action_layer.py` |

Add to an existing page when a test needs a variation of what it already covers,
and add a page when the case is genuinely different. Every fixture control is
there because a test pins a behaviour on it, so removing one will break
something.

Using Makefile shortcuts from `backend/` (if your shell supports `make`):

```bash
make install-dev
make playwright
make test
make test-browser
make test-server
```

### Known failing expectations

Some tests are marked `xfail` with a reason pointing at the phase of
`docs/IMPROVEMENT_PLAN.md` that fixes them. They assert intended behaviour that
the code does not yet have, so they are documentation rather than dead weight.
They are `strict`, meaning they fail loudly once the underlying defect is fixed,
which is the prompt to remove the marker.

## Continuous Integration

`.github/workflows/main.yml` runs on every pull request and on every push to
`main`:

- **Backend tests**: the offline suite, then `pytest -m browser` against a
  Chromium installed by Playwright. Both run on every pull request, which is why
  the fixture site above matters: a suite that needed the network could not run
  here.
- **Frontend lint and build**: `npm ci`, `npm run lint`, `npm run build`.

Deploy is a third job. It runs only on a push to `main`, and only after both
test jobs pass, so a red `main` cannot reach the server. It builds the frontend,
uploads it to `/home/bitnami/deploy-staging`, and publishes into the served root
only once a complete build is confirmed on the server. The live site is
therefore untouched if any earlier step fails.

Third-party actions are pinned to commit SHAs with the version in a trailing
comment. Update the SHA and the comment together; a floating tag like `@master`
means an outside maintainer decides what runs against the deploy key.

## Troubleshooting

- Backend cannot connect to DB:
	- Verify `backend/configs/user_db_config.yaml` values and container status (`docker ps`).
- Login/register failing:
	- Ensure `users` table exists and bcrypt/token env variables are set.
- Forgot-password not sending:
	- Confirm email credentials in `backend/.env` and provider SMTP requirements.
- Browser stream not showing:
	- Confirm backend is on port 8000 and frontend dev proxy is active.
	- Check that Playwright browsers were installed.
- Tests import/path issues:
	- Run tests from inside `backend/` to match relative import assumptions.

## Security Notes

- Do not commit real API keys or secrets.
- Keep production secrets outside source control.
- Use a strong `TOKEN_SECRET` and rotate it if exposed.
- Saved user credentials are encrypted at rest with `CREDENTIALS_KEY` and keyed to the authenticated user.
  Losing or rotating that key makes existing vault rows unreadable.
- Card verification values (CVV) are never persisted, by either the browser or the server.
- `backend/configs/user_db_config.yaml` is gitignored.
  It was previously committed with a real password and a private VPC address, so that credential should be treated as compromised and rotated.

### Still outstanding

These are known gaps, tracked in `docs/IMPROVEMENT_PLAN.md`:

- The access token lives in `localStorage`, so it is reachable by any XSS.
  Moving to an httpOnly cookie needs a CSRF strategy and is not yet done.
- Database calls are synchronous inside async endpoints, so they block the event loop under load.
  Phase 1 fixed the correctness problem (a single shared cursor) with a connection pool; the throughput problem remains.
- The forgot-password rate limit is per-process and in-memory, so it does not hold across multiple workers.

## Contributors

Browser Interaction Team:

- Edwin Villanueva, CS
- Caleb Yaghoubi, CS
- Dylan Dinh, CS
- Dylan Kuneman, CS
- Kevin Esparza Lanzas, CS

Information Gathering Team:

- Jordan Campbell, CS
- Gregory Pulitano, CS
- Kush Havinal, CS
- Aridsondez Jerome, CS
- Vignesh Sundararajan, CS

Sponsored by Dr. Liqiang Wang and Dr. Zihang Zou
