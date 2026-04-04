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
13. [Troubleshooting](#troubleshooting)
14. [Security Notes](#security-notes)
15. [Contributors](#contributors)

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
2. Frontend opens `/ws/stream/{user_id}`.
3. Backend starts `src/app.py` as a subprocess.
4. LangGraph agents iterate: orchestrator -> executor -> verifier -> fallback/interaction.
5. Browser frames/logs and HITL messages stream back through WebSocket.
6. User replies (if requested) are forwarded to the running agent.

## Repository Layout

Top-level structure:

- `backend/`
	- `server.py`: FastAPI app, auth endpoints, websocket orchestration, process management.
	- `src/`: LangGraph agent pipeline and Playwright execution modules.
	- `configs/user_db_config.yaml`: PostgreSQL connection config.
	- `tests/`: Unit and integration tests.
	- `Makefile`: common setup/test/run shortcuts.
	- `verification/`: verification model/evaluator docs and logic.
- `frontend/`
	- `src/pages/`: login/register/forgot-password/dashboard pages.
	- `src/components/`: route protection and credential components.
	- `vite.config.js`: dev proxy for `/api` and `/ws` to backend.
- `requirements.txt`: Python dependencies.
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
pip install -r requirements.txt
python -m playwright install chromium
```

Then complete backend and frontend setup below.

## Backend Setup (Database, Env, API)

### 1. Configure PostgreSQL

Run PostgreSQL via Docker:

```powershell
docker pull postgres
docker run --name some-postgres -e POSTGRES_PASSWORD=mysecretpassword -p 5432:5432 -d postgres
```

Update `backend/configs/user_db_config.yaml` to match your DB settings:

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

Create `backend/.env` with at least these keys:

```env
GOOGLE_API_KEY=
OPENAI_API_KEY=
TOKEN_SECRET=
BCRYPT_SALT=
EMAIL_ACCOUNT=
EMAIL_PASSWORD=
```

Notes:

- Default model assignments currently use Google models, so `GOOGLE_API_KEY` is required for out-of-the-box agent runs.
- `OPENAI_API_KEY` is optional unless you switch model assignments in `backend/src/models.py`.
- `TOKEN_SECRET` should be long/random in non-dev environments.
- `BCRYPT_SALT` must be a valid bcrypt salt.
- `EMAIL_ACCOUNT` and `EMAIL_PASSWORD` are needed for forgot-password email sending.

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

### REST endpoints

- `GET /api/users/`
- `POST /api/users/insert/`
- `DELETE /api/users/delete/`
- `POST /api/users/update/`
- `POST /api/users/login/`
- `POST /api/users/verify/`
- `GET /api/users/forgot-password/`
- `POST /api/start_agent`
- `POST /api/users/store-credentials`
- `POST /api/hitl_reply/{user_id}`
- `GET /send_logs` (placeholder)

### WebSocket endpoints

- `WS /ws/stream/{user_id}`
	- Streams agent logs, status updates, HITL requests, and browser frames.
- `WS /ws/chat/{client_id}`
	- Chat channel and HITL reply forwarding.

## Testing

Primary backend tests are in `backend/tests/`.

From `backend/`:

```powershell
pytest tests -v
```

Targeted suites:

```powershell
pytest tests/test_server.py -v
pytest tests/execution -v
pytest tests/verification -v
```

Systematic action script (long-running, browser-based):

```powershell
python tests/test_action_system.py
```

Using Makefile shortcuts (if your shell supports `make`):

```bash
make install
make install-dev
make playwright
make test
make test-server
make test-execution
```

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
- Use a strong `TOKEN_SECRET` and rotate if exposed.
- Consider storing sensitive user credential payloads in encrypted storage rather than local browser storage for production deployments.

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
