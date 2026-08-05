# Improvement Plan: from demo to general-purpose web agent

Branch: `Edwin-after-grad`
Baseline commit: `9f6b2eb`
Date: 2026-07-31

## Purpose

Today the system can drive a browser through a short, mostly-linear task and stream it to the UI.
The goal is for it to autonomously complete long, stateful, high-stakes web tasks on the user's behalf: applying to jobs, booking travel, filling multi-page forms.

This document records what is actually wrong, what to change, and in what order.
Every claim below was verified by reading the code or by running it, and the evidence is cited.

## The central finding

The system is architected as an email-composition agent wearing a general-agent costume.

Roughly a third of the control logic in the executor, the verifier, and the status tracker consists of Gmail and Outlook compose special cases that are gated on keyword matches against plan-step text.
Because the gates are keyword-driven, they fire on unrelated tasks and actively block them.
This is not a matter of a few stray heuristics to clean up later.
It is the primary reason the system cannot generalize, and the plan below is organized around removing it and replacing it with structural mechanisms.

Two reproductions make the point concretely.

**Reproduction 1: any Google-owned URL is silently redirected to DuckDuckGo.**
[executor.py:1398-1402](backend/src/agents/executor.py:1398) rewrites the navigation target to `https://duckduckgo.com` whenever the host ends in `.google.com` and the task text does not contain the literal word "google".
Verified behavior:

| Requested URL | Task text | Result |
| --- | --- | --- |
| `https://mail.google.com/` | "Check the confirmation email" | redirected to DuckDuckGo |
| `https://docs.google.com/forms/x` | "Fill out the employer questionnaire" | redirected to DuckDuckGo |
| `https://accounts.google.com/signin` | "Sign in to continue the application" | redirected to DuckDuckGo |

Google Forms is a common job-application host, and `accounts.google.com` is the "Sign in with Google" hop on Greenhouse, Lever, and Workday.
This also silently violates the "plan step URL must be used verbatim" invariant asserted three lines earlier at [executor.py:1386](backend/src/agents/executor.py:1386).

**Reproduction 2: the email compose gate deadlocks job applications.**
[executor.py:744-752](backend/src/agents/executor.py:744) treats any plan step containing "message" (or "email", "mail", "subject", "recipient", "draft") as an email compose task, then refuses every Send, Review, Continue, or Finish click until an email recipient, subject, and body have all been filled.
A job application form has none of those.
Verified behavior for the step "Enter your message to the hiring manager and click Continue":

| Action | Gate verdict |
| --- | --- |
| `click(button, "Continue")` | blocked, missing recipient/subject/body |
| `click(button, "Review")` | blocked, missing recipient/subject/body |
| `click(button, "Send")` | blocked, missing recipient/subject/body |
| `click(button, "Finish")` | blocked, missing recipient/subject/body |

Every path forward is refused.
`step_attempts` climbs, the fallback agent is invoked repeatedly, and the run dies on the recursion limit without ever telling the user what happened.

## Current state, measured

| Check | Result |
| --- | --- |
| `pytest tests` from `backend/` | **6 collection errors, suite aborts, 0 tests run** |
| with `--continue-on-collection-errors` | 27 passed, 1 failed, 14 errors |
| `npx eslint .` in `frontend/` | **5 errors, 2 warnings** |
| CI (`.github/workflows/main.yml`) | builds frontend and deploys; runs no tests and no lint |
| `import main` without `GOOGLE_API_KEY` | **fails**, though all six agents are configured for OpenAI |
| `POST /api/start_agent` | **broken**, passes `--video_port` which `app.py` does not accept |
| Endpoints requiring authentication | **0 of 12** |

## Blocking capability gaps

For the stated goal these are hard blockers, not polish.

| Missing | Why it blocks the goal | Evidence |
| --- | --- | --- |
| **File upload** | no resume, no cover letter | no `set_input_files` or `expect_file_chooser` anywhere; [capabilities.py:38](backend/src/capabilities.py:38) rewrites "upload a file" into an instruction nothing implements; [dom_extractor.py:98](backend/src/dom_extraction/dom_extractor.py:98) reports `input[type=file]` as a plain textbox |
| **Addressable typing** | the model chooses *what* to type but not *where* | [langchain_tools.py:44-47](backend/src/execution/langchain_tools.py:44) `TypeInput` has only `text`; [handlers.py:659-673](backend/src/execution/handlers.py:659) then guesses the field by classifying the *value* |
| **Select / dropdown** | country, state, degree, cabin class, passenger count | no `select_option` anywhere; native `<option>` elements are not clickable in Chromium yet are advertised to the model at [dom_extractor.py:105](backend/src/dom_extraction/dom_extractor.py:105) |
| **Checkbox and radio state** | EEO questions, "I certify", terms, seat and insurance opt-ins | no `.check()` or `.is_checked()` anywhere; clicks toggle blindly, and a retry silently un-checks |
| **Plan mutation** | a fixed 3 to 8 step plan cannot express "apply to 20 jobs" | [orchestrator.py:39](backend/src/agents/orchestrator.py:39) builds a plan only when `current_plan` is empty, and nothing ever writes `current_plan` again; `insert_step_before` is promised by the schema and the prompt but never implemented |
| **Session persistence** | every run re-authenticates, maximizing MFA and risk-engine friction | [app.py:153](backend/src/app.py:153) `browser.new_context()` with no `storage_state` |
| **Field readback** | nothing can answer "which fields are still empty?" | no `input_value()` check anywhere; handlers return success without confirming the value landed |

## Correctness defects that will bite immediately

Grouped by theme, with the fix folded into the phases below.

### Non-termination

The graceful safety stop is arithmetically unreachable.
`recursion_limit` is 80 at [app.py:104](backend/src/app.py:104) and `max_transactions` is also 80 at [app.py:125](backend/src/app.py:125), but every node increments `number_of_transactions`, so LangGraph hits its own limit first.
The abort test at [orchestrator.py:682-690](backend/src/agents/orchestrator.py:682) subtracts "success credits" from the transaction count, which pushes the graceful stop even further out of reach.
`GraphRecursionError` is then swallowed by the blanket handler at [app.py:178-181](backend/src/app.py:178), so the user sees nothing.
80 supersteps is roughly 20 act-verify cycles for the entire mission.

A second loop exists on the final step.
When the verifier says the step is complete but the goal is not, [orchestrator.py:333-348](backend/src/agents/orchestrator.py:333) retries while [verifier.py:459](backend/src/agents/verifier.py:459) resets `step_attempts` to 0 and [verifier.py:46-48](backend/src/agents/verifier.py:46) resets `stall_cycles` to 0.
All three brakes are disabled simultaneously.

### The verifier cannot see the page

`AFTER_STATE`, the post-action page snapshot, is the verifier's primary evidence.
[verifier.py:84-101](backend/src/agents/verifier.py:84) prefers a synthetic log built by `last_execution_event_to_executor_log`, which emits only action, args, status, message, and error type, and then overwrites the tail of the real log with it.
So the freshest page content is deleted from both `EXECUTION_OUTPUT` and `RECENT_EXECUTION_HISTORY`, while the prompt at [verifier.py:417](backend/src/agents/verifier.py:417) still claims AFTER_STATE is present and [verification.prompt.md:35](backend/src/prompts/verification.prompt.md:35) instructs the model to prefer it.
The verifier judges the current action using the previous action's snapshot.

As a direct consequence the MFA and CAPTCHA safety net at [verifier.py:132-140](backend/src/agents/verifier.py:132) can never fire: it scans for page phrases in a string that no longer contains page content.

The verifier is also never told where it is in the plan.
`is_last_step` is computed at [verifier.py:80](backend/src/agents/verifier.py:80) and used only in the LLM-failure branch.
The only carrier is `MISSION_STATUS`, clipped to 2200 chars, and `## Stats` with `Current step: i/n` is the last section of that document, so it is the first thing truncated.

### The planner is fed fabricated observations

[orchestrator.py:745-753](backend/src/agents/orchestrator.py:745) `_get_simulated_page_context` returns a hardcoded string from a five-element list and injects it into the planning prompt under the heading `PAGE STATE:`.
On step 0 the planner is always told "Page loaded at about:blank. Navigation and content elements visible."
The list also contains the string "Task completed successfully."

### Silent success

The action layer reports success in cases where nothing happened.

- `click(force=True)` is the automatic retry at [handlers.py:137](backend/src/execution/handlers.py:137), which bypasses actionability checks and fires at coordinates through overlays and disabled controls.
- Role-only click falls back to `get_by_role(role).first` at [handlers.py:266-307](backend/src/execution/handlers.py:266), which is typically the nav hamburger or the cookie banner, and reports "Clicked first button".
- Name matching is substring and case-insensitive with `.first`, so `click(button, "Submit")` also matches "Submit Application" and "Do not submit", chosen by DOM order.
- `handle_navigate` at [handlers.py:27-42](backend/src/execution/handlers.py:27) ignores the HTTP response, so a Cloudflare 403 returns "Navigated to URL".
- `handle_search`'s keyboard fallback at [handlers.py:978-990](backend/src/execution/handlers.py:978) types into whatever has focus and always returns success.
- `handle_scroll` at [handlers.py:1017](backend/src/execution/handlers.py:1017) never compares `scrollY` before and after.

### Secrets

- Credentials are passed to the agent subprocess as a command-line argument at [server.py:715](backend/server.py:715). Process command lines are readable by other processes on the machine.
- [server.py:699](backend/server.py:699) prints the entire credential blob, including passwords, to server stdout.
- `handle_type` embeds the typed value in its result message at [handlers.py:873](backend/src/execution/handlers.py:873). [executor.py:415-427](backend/src/agents/executor.py:415) redacts `args["text"]` and `extracted_text` but not `message`, so the secret re-enters the LLM context and `reasoning_log` every turn via [executor.py:1559](backend/src/agents/executor.py:1559).
- `backend/configs/user_db_config.yaml` is tracked in git with a plaintext database password **and a private VPC address (`172.31.46.153`)**. `.gitignore:28` guarded `backend/credentials/user_db_config.yaml`, the wrong directory, so the rule was a no-op.
- `README.md` documented `BCRYPT_SALT` as a required environment variable. Nothing reads it; passwords are hashed with a fresh `bcrypt.gensalt()` and the only bcrypt variable is the optional `BCRYPT_ROUNDS` ([server.py:195](backend/server.py:195)). Anyone following the README would set a variable that does nothing and assume salting was configured.
- The frontend stores third-party service passwords, full card numbers, and CVVs in `localStorage` at [Dashboard.jsx:1127-1131](frontend/src/pages/Dashboard.jsx:1127). Storing a CVV is a PCI-DSS violation regardless of encryption.

### Authorization

No endpoint authenticates.
`/api/users/store-credentials` at [server.py:549](backend/server.py:549) accepts an `Authorization` header and never reads it, keying instead on a client-supplied `session_id`.
`/ws/stream/{user_id}` at [server.py:683](backend/server.py:683) requires no token, so any client can make the server spawn a browser subprocess with an arbitrary prompt, and anyone who learns a `session_id` can pop that user's credential blob into their own run.
`GET /api/users/?userId=N` returns any user's record with no token at all.

Login has an auth bypass: [server.py:400-404](backend/server.py:400) short-circuits on a valid `Authorization` header and returns the token, ignoring the submitted username and password entirely.
Since [Login.jsx:20-27](frontend/src/pages/Login.jsx:20) attaches any existing header, a second person at the same browser can type arbitrary credentials and be logged in as the previous user.

The forgot-password flow rotates the user's password on a `GET` request with the email in the query string ([server.py:478-513](backend/server.py:478)), which is CSRF-able and puts PII in access logs.
It then sets `chng_pass = true`, after which login returns a valid token alongside `error = 'Password Change Required'`; [Login.jsx:31](frontend/src/pages/Login.jsx:31) requires `error === ''`, discards the token, and shows "incorrect password".
There is no change-password UI anywhere, so password reset is a dead end.

### Concurrency

A single global psycopg2 connection and cursor are shared by every request ([server.py:61-99](backend/server.py:61)).
psycopg2 cursors are not safe for concurrent use, so overlapping requests will interleave results.

`POST /api/start_agent` calls blocking `subprocess.run` inside an async endpoint at [server.py:539](backend/server.py:539), which would stall the entire event loop for the duration of an agent run.
It is also broken (wrong argument name), and unreachable from the UI.

The HITL wait at [server.py:912](backend/server.py:912) blocks `log_consumer` for up to 300 seconds, so no logs reach the frontend while the agent is waiting for the user.

### Streaming

The screencast is started with only format and quality at [server.py:976](backend/server.py:976).
CDP's `maxWidth`, `maxHeight`, and `everyNthFrame` are all unused, so frames arrive at full viewport size at whatever rate Chromium produces them.
Each frame is then base64-encoded inside a JSON text message, adding about 33 percent overhead, and the frontend allocates a fresh data-URL string per frame at [Dashboard.jsx:838](frontend/src/pages/Dashboard.jsx:838).
Because `setLiveFrame` is parent state and nothing in the app is memoized, every frame re-renders the whole Dashboard, which re-runs an O(n) reduce over the entire log history at [Dashboard.jsx:539-569](frontend/src/pages/Dashboard.jsx:539).
Old CDP sessions are never detached on page switch at [server.py:965-976](backend/server.py:965).

The click-coordinate mapping hardcodes 1280x720 at [Dashboard.jsx:627](frontend/src/pages/Dashboard.jsx:627).
This is currently correct only by coincidence, because no viewport is set anywhere in the backend and Playwright's default happens to be 1280x720.
It breaks the moment anyone sets a viewport, and out-of-image clicks on the wrapper padding are never clamped on either side.

### Dead and misleading code

- `backend/execution/` contains only a `__pycache__` directory with four tracked `.pyc` files. The source moved to `backend/src/execution/`. Four test files still import from it.
- `backend/tests/execution/__init__.py` makes `execution` an importable top-level package that shadows the real one. This is the single cause of the suite-wide collection failure.
- `backend/verification/` (about 530 lines including `USAGE.md`) is a superseded rule-based verifier that cannot even be imported, since it depends on the deleted `backend/execution/`. `README.md:75` still lists it as a live component.
- `backend/Prototype/` contains only three PNGs. `tests/execution/test_handlers.py:13` still points into it.
- `Verifier.reset_simulation` at [verifier.py:1048](backend/src/agents/verifier.py:1048) is `pass`, still called at import time from [app.py:46](backend/src/app.py:46).
- [main.py:19](backend/src/main.py:19) constructs a `genai.Client()` at import, requiring `GOOGLE_API_KEY` even though every agent is configured for OpenAI, and the client is never used. [main.py:31-35](backend/src/main.py:31) reads prompts through hardcoded Windows relative paths; all five variables silently hold the string "Error: ... was not found." and are never referenced.
- `fallback.prompt.md` ships its own markdown scaffolding as the system prompt. It literally begins with `---`, `## \`prompts/fallback.prompt.md\``, and an opening ` ```md ` fence, and ends with an unclosed fence. `verification.prompt.md` also ends with an unterminated fence.
- Frontend: `UserCredentialsCard.jsx` renders an empty div and is imported nowhere; `App.css` is unimported and still contains Vite scaffolding that would break the layout; `Dashboard.jsx:705-748` is a 44-line commented-out `handleSend` that is the only reason `axios` is still a dependency.
- `agentPrompt` is collected in the UI at [Dashboard.jsx:1562](frontend/src/pages/Dashboard.jsx:1562), persisted, read once, and never used. Users will believe they configured a system prompt.
- "Reset Password" and "Delete Account" buttons at [Dashboard.jsx:1571-1573](frontend/src/pages/Dashboard.jsx:1571) have no `onClick`. The backing endpoints exist and are unused.
- `output (1).pdf` (49 KB) and a root `package-lock.json` stub with no `package.json` are both tracked.
- `.gitignore` blanket-ignores `*.png`, which matches the ten agent icons the UI needs.

---

# The plan

Eight phases. Each phase leaves the repo in a working, testable state.
Phases 0 through 4 are the load-bearing ones; a run through 0 to 4 alone would produce a materially more capable agent.

## Phase 0: make the system runnable and verifiable

**Status: complete.** Results:

| Check | Before | After |
| --- | --- | --- |
| Tests collected | 36, suite aborted on 6 errors | **143, zero collection errors** |
| Tests passing | 0 (suite aborted) | **88 offline, plus 47 browser and 2 llm opt-in** |
| Offline, no API key | not possible | **passes** |
| `eslint` | 5 errors, 2 warnings | **0 errors, 1 warning** |
| Tracked secrets | DB password + private VPC IP | **none** |
| Tracked-but-ignored files | 26 | **0** |
| `import main` without `GOOGLE_API_KEY` | fails | **succeeds** |

Six tests are `xfail(strict=True)` with a reason naming the phase that fixes them.
They are not suppressed failures; they are executable specifications for work
that is still owed, and they will fail loudly once the defect is fixed.

Two findings surfaced while doing this work:

- `backend/tests/test_executor_resilience.py` asserted executor argument-recovery
  behaviour (recovering a search query from plan context, recovering a click
  target from the DOM) that was **deleted** in `66fb45f`. The tests never ran
  because of the collection failure, so the removal went unnoticed. Phase 2
  reintroduces this capability properly via `ambiguous_target` candidate lists,
  so the tests are kept as xfail rather than rewritten to match the weaker
  current behaviour.
- The executor's argument recovery is invisible in the logs.
  `_validate_and_normalize_action` builds a "Recovered search text from
  PLAN_STEP" message and `_finish_from_result` then overwrites it with the
  dispatcher's own message, so no record of the recovery reaches the verifier.

Nothing else can be trusted until the tests run and the tree is clean.

1. Add `pyproject.toml` at the repo root with `[tool.pytest.ini_options]`: `pythonpath = ["backend", "backend/src"]`, `testpaths = ["backend/tests"]`, `asyncio_mode = "auto"`, and registered markers for `browser` and `llm`.
2. Delete `backend/tests/execution/__init__.py`. This removes the package shadow that aborts the suite.
3. Delete the dead trees: `backend/execution/`, `backend/Prototype/`, `backend/verification/`, `backend/tests/verification/`, `backend/archive/`, `backend/test_message.py`, `backend/test_message2.py`, `output (1).pdf`, root `package-lock.json`.
4. Repoint `backend/tests/execution/*.py` at `execution.*` (the real package) and rewrite `test_handlers.py` to import from `execution.handlers`.
5. Convert `tests/test_action_system.py` into a proper pytest module: add a session-scoped `page` fixture in `backend/tests/conftest.py`, mark it `@pytest.mark.browser`, and default to headless. Fix the `ZeroDivisionError` in `TestResults.print_summary`.
6. Mark `test_control_flow.py` and `test_fallback.py` `@pytest.mark.llm` and add a `Models` fixture that injects deterministic fakes, so the default suite makes no billable API calls. Deselect `llm` and `browser` by default via `addopts`.
7. `git rm --cached` the tracked-but-ignored files: `.idea/`, `.vscode/settings.json`, all `.pyc`. Rewrite `.gitignore`: drop the duplicate rules and the stray `back/*`, replace blanket `*.png` with `screenshots/**/*.png` and `output/**`, add `__pycache__/`, `.pytest_cache/`, `.claude/settings.local.json`, and `dist/`. Keep `frontend/assets/**/*.png` tracked.
8. Move database configuration out of `backend/configs/user_db_config.yaml` into environment variables, `git rm --cached` the file, add it to `.gitignore`, and commit a `user_db_config.example.yaml`. Note the credential rotation caveat in the out-of-scope section.
9. Delete `main.py:19` (`genai.Client()`), `main.py:31-39` (dead prompt reads and `user_input`), the unused imports, and the commented `app_prototype` import. Delete `Verifier.reset_simulation` and its call at `app.py:46`.
10. Fix the lint errors: delete the dead `check_login` in `ProtectedRoute.jsx` (it references undefined `username`/`password`), remove the unused `useState` import in `ForgotPassword.jsx`, give `Register.jsx:15`'s `useEffect` a dependency array, and tighten `eslint.config.js:27` so `varsIgnorePattern` no longer hides the unused PascalCase state in `Register.jsx`.
11. Prune `requirements.txt`. Remove `backend==0.2.4.1` (an unrelated PyPI package that shadows this repo's own `backend` namespace and is a dependency-confusion vector), `jsonwebtoken` (the npm package name; the real dependency is `pyjwt`), `python-bcrypt` (Python 2 only, redundant with `bcrypt`), and the unused `chromadb`, `flask`, `kubernetes`, `onnxruntime`, `huggingface-hub`, `mouseinfo`, and Scrapy stack. Split into `requirements.txt` and `requirements-dev.txt`.
12. Fix the README drift: the provider claim at `README.md:164-165` is inverted (all six agents use OpenAI, so `OPENAI_API_KEY` is required and `GOOGLE_API_KEY` is not), `.env` lives at the repo root not `backend/`, and the documented test commands at lines 261, 268, 269, and 275 all fail. Delete `backend/verification/USAGE.md` with the tree, fix `backend/readme.md`'s Chroma port collision with uvicorn, and replace `frontend/README.md`'s untouched Vite boilerplate.

**Acceptance**: `pytest` from the repo root collects and passes with no network and no API key. `npx eslint .` is clean. No tracked secrets. No tracked `.pyc`.

## Phase 1: security and tenancy

**Status: complete.** Results:

| Check | Before | After |
| --- | --- | --- |
| Endpoints requiring auth | 0 of 12 | **all except register, login, forgot-password, change-password** |
| WebSockets requiring auth | 0 of 2 | **2 of 2, via first-frame handshake** |
| Credentials at rest | plaintext in `localStorage` | **Fernet-encrypted in Postgres, keyed to the token subject** |
| CVV storage | plaintext in `localStorage` | **never persisted, stripped client and server side** |
| Credentials to subprocess | command-line argument | **stdin** |
| Secrets in server logs | full blob printed | **key names only** |
| Typed secrets in LLM context | present every turn | **redacted by value** |
| DB concurrency | one shared cursor | **connection pool, one connection per request** |
| Tests passing offline | 88 | **149, plus 49 opt-in** |
| `eslint` | 0 errors | **0 errors** |

Each fixed vulnerability has a `test_regression_*` test pinning it.
The `xfail` on `GET /api/users/` is gone because that defect is now fixed, which is the marker working as intended.

Deliberate contract changes, which the frontend was updated to match:

- Auth failures return `401` with a `detail` field instead of `200` with an `error` string.
- `GET /api/users/` no longer accepts `?userId=`; it returns the token subject.
- `forgot-password` is a `POST` at `/api/users/forgot-password`, with no trailing slash and a single generic response.
- `/ws/stream/{user_id}` and `/ws/chat/{client_id}` lost their path parameters and became `/ws/stream` and `/ws/chat`.
- `POST /api/hitl_reply/{user_id}` became `POST /api/hitl_reply`.
- JWTs now carry a `scope` claim, so tokens issued before this change are rejected and users must sign in again.

Findings that surfaced during the work:

- `README.md` documented `BCRYPT_SALT` as a required variable.
  Nothing reads it, and nothing ever did in this tree.
  Anyone following the setup guide would set a no-op variable and reasonably assume salting was configured.
- The chat WebSocket relayed every message to *every* connected socket as `Client #N says: ...`, and the dashboard rendered whatever arrived as agent output.
  One user's text appeared in another user's transcript, attributed to the agent.
  This was a data leak, not just a correctness bug, so the broadcast was removed rather than scoped.
- `ProtectedRoute` authenticated by POSTing `{token}` to the *login* endpoint with no username, which raised a `KeyError` and returned a 500.
  The redirect worked only because an exception was thrown.

This must precede autonomy work.
An agent that acts on the user's behalf with their saved credentials and card is not something to leave unauthenticated.

1. Add a `require_user` FastAPI dependency that validates the JWT and returns a `user_id`. Apply it to every REST endpoint. Derive the user from the token, never from a request parameter, which closes the IDOR on `GET /api/users/?userId=N`.
2. Authenticate both WebSockets. Accept the connection, require an auth frame as the first message, validate it, and close with 1008 otherwise. Stop putting the JWT and the task prompt in the query string; both currently land in access logs.
3. Stop passing credentials on the command line. Write the credential JSON to the child's stdin as the first line before any HITL traffic, and have `app.py` read it there. Delete the `--credentials_json` argument and the `print` of the credential blob at `server.py:699`.
4. Move credential storage server-side. Encrypt at rest with a key from the environment, key rows to the authenticated `user_id`, and give the agent only the subset the current task needs. Remove all secrets from `localStorage`. Never store a CVV; if card payment is in scope at all, require the user to enter the CVV at the moment of use.
5. Redact secrets on every path out of the browser layer. Fix the `message` leak in `handle_type`, and add a single `redact()` helper applied to `ExecutionOutput.message`, `LastExecutionEvent`, and `reasoning_log` before anything is logged or sent to a model.
6. Replace the global connection and cursor with a `psycopg2.pool.ThreadedConnectionPool` and a per-request context manager.
7. Delete `POST /api/start_agent` (broken and unreachable), `GET /send_logs` (a bare `pass`), and `GET /api/nuke` (an unauthenticated `gc.collect()`).
8. Fix the auth bypass at `server.py:400-404`: username and password must be verified even when an `Authorization` header is present, and `Login.jsx` should not send one. Fix `delete_user` returning a raw exception object instead of a string. Make forgot-password a `POST`, return an identical response whether or not the account exists, and rate-limit it.
9. Implement the change-password flow the backend already implies: on `chng_pass`, issue a scoped one-time token and add the UI page. Right now the entire reset path dead-ends.
10. Replace `allow_origins=["*"]` plus `allow_credentials=True` (an invalid combination) with an explicit origin list from the environment.
11. Fix `ProtectedRoute`: it currently POSTs `{token}` with no username, which raises `KeyError` and a 500 at `server.py:408`, and its redirect works only by accident. Its failure fallback at line 75 navigates to `/dashboard`, the route it guards. Add a token-expiry check, a 401 interceptor, and a real login redirect.

**Acceptance**: every endpoint rejects an unauthenticated request. No secret appears in stdout, in a process argument list, in a URL, or in `localStorage`. Concurrent requests do not share a cursor.

## Phase 2: rebuild the action layer around addressable targets

**Status: core complete.** Results:

| Check | Before | After |
| --- | --- | --- |
| Tools offered to the model | 11 | **19** |
| Can address a duplicate label | no, `.first` by DOM order | **yes, `nth=` after an `ambiguous_target` result** |
| Field targeting | value classified against 7 selector lists | **`fill(role, name, text)`** |
| Dropdowns | impossible | **`select_option`** |
| Checkbox / radio state | blind toggle, never read | **`set_checkbox`, idempotent and verified** |
| Resume upload | impossible | **`upload_file`** |
| "Which fields are empty?" | unanswerable | **`read_form`** |
| Waiting | blind `sleep` | **`wait_for` element / URL / text** |
| Post-condition checks | none | **`verified` flag on every result** |
| Miss diagnostics | "element not found" | **lists the targets that do exist** |
| Absent dropdown option | 8s timeout, no detail | **0.03s, lists the real options** |
| `handlers.py` | 1186 lines | **426 lines** |
| Tests | 177 offline | **177 offline + 89 browser, incl. 36 new** |

The new layer lives in `execution/targeting.py` (resolution) and
`execution/actions.py` (primitives), tested offline against
`backend/tests/fixtures/job_application.html`, a form with two selects, a radio
group, checkboxes, a file input, a readonly field, a late-appearing control, and
two buttons that deliberately share the name "Save". An end-to-end test fills
every field type and submits, asserting `verified` on each step.

Deliberate contract changes:

- `handle_click` no longer uses `force=True` by default. Forcing dispatched at
  coordinates regardless of overlays, so a cookie banner covering a button
  produced a success with nothing happening.
- The typed value is no longer echoed in any result message. One legacy test
  asserted the opposite; that assertion *was* the leak.
- `type` still exists but types into the focused element only. It no longer
  guesses a field, and no longer returns invented `target_*` metadata.

Still outstanding from this phase, deferred rather than done:

- Downloads (`expect_download`) and the file-chooser event are not handled.
- Dialogs are still auto-accepted in `app.py:159`, which auto-confirms
  `confirm("Submit your application?")` and defeats the sensitive-action gate.
- `handle_search` still carries hardcoded Google/DuckDuckGo/Bing selectors, and
  `handle_navigate` still reports HTTP 4xx/5xx as success.
- Date pickers and type-then-select autocomplete have no dedicated primitive.


This is the highest-value change in the plan.
Today the model decides *what* to type and the handler guesses *where*, using the value's shape.
A 40-field job application cannot be filled that way.

Replace the action set with explicitly targeted primitives. Every target is `(role, name, nth)` resolved against the same snapshot the model was shown, or a `ref` id from that snapshot.

| Action | Signature | Notes |
| --- | --- | --- |
| `navigate` | `(url)` | check the response status; distinguish 4xx/5xx from a timeout |
| `click` | `(role, name, nth=0)` | strict resolution, no `force` by default |
| `fill` | `(role, name, text, clear=True)` | replaces blind `type`; readback required |
| `select_option` | `(role, name, value or label)` | new |
| `set_checkbox` | `(role, name, checked)` | new, uses `check`/`uncheck` and verifies with `is_checked` |
| `upload_file` | `(role, name, document_id)` | new, `set_input_files` from the server-side document store |
| `wait_for` | `(role+name or url or text, timeout)` | new, replaces blind sleeps |
| `press_key` | `(key, role=None, name=None)` | target-scoped |
| `scroll` | `(direction, role=None, name=None)` | element-scoped; also `scroll_to(role, name)` |
| `read_form` | `()` | new, returns the structured field inventory with filled/empty state |
| `switch_tab` / `list_tabs` / `close_tab` | | new, replaces the implicit hijack |
| `go_back` | `()` | already implemented; register it in the `Action` literal and in `capabilities.py` |
| `extract_content` | `(max_chars)` | unchanged |

Implementation notes.

1. **Post-condition verification inside every handler.** Add a `verified: bool` field to `ExecutionOutput`. `fill` re-reads `input_value()`. `set_checkbox` re-reads `is_checked()`. `click` compares URL, focused element, and a cheap DOM digest before and after. `select_option` re-reads the selected value. A handler that cannot confirm its effect returns `verified: False`, and the verifier treats that as evidence rather than re-deriving it from prose.
2. **Ambiguity is an error, not a coin flip.** When a `(role, name)` pair matches more than one element, return `error_type="ambiguous_target"` with the candidate list and their `nth` indices, so the model can disambiguate on the next turn. This replaces the current `.first`-plus-substring behavior that silently clicks the wrong control.
3. **Remove `force=True` from the default path.** Keep it as an explicit escalation after a genuine actionability failure, and report when it was used.
4. **Delete the guessing machinery**: the seven hardcoded selector lists at `handlers.py:393-478`, the value-based intent classifier at `handlers.py:659-673`, `_looks_like_password` (which requires a symbol and therefore misroutes real passwords into visible fields), `_looks_auth_context` (which reroutes an application form's Email field to the site's login box because the header says "Sign in"), and the dead `_find_visible_prefer_empty`.
5. **Fix the frame handling.** `frames = [page.main_frame] + list(page.frames)` at `handlers.py:142` and `:480` processes the main frame twice; `page.frames` already includes it. Re-resolve the frame list after any navigation instead of holding stale `Frame` objects. Use `frame_locator` and make focus queries frame-aware, since `document.activeElement` in the main frame returns the `<iframe>` element itself when focus is inside an embedded Greenhouse or Workday form.
6. **Replace `networkidle` waits with `load` plus a targeted `wait_for`.** The current code spends 3 to 21 seconds per action on `networkidle` waits that never resolve on an SPA, plus unconditional sleeps. Worst-case click latency today is effectively unbounded: `handlers.py:125-140` can spend about 60 seconds per (frame, role, name) combination across up to 27 combinations in stage one alone, with no timeout above it.
7. **Fix the error taxonomy.** `handle_type`, `handle_scroll`, and `handle_wait` all return `error_type="tool_limit"` on failure, which `executor.py:1255-1265` treats as high-signal and escalates to screenshot capture and fallback. Introduce `timeout`, `blocked`, `not_found`, `ambiguous_target`, `http_error`, and `not_interactable`, and map escalation to the ones that deserve it.
8. **Handle downloads and file choosers.** Register `page.on("download")` with a per-run artifact directory, and use `expect_file_chooser` for uploads that go through a button rather than a visible input.
9. **Stop auto-accepting every dialog.** [app.py:159](backend/src/app.py:159) accepts all dialogs, which auto-confirms `confirm("Submit your application?")` and defeats the sensitive-action gate. Route dialogs through the same approval policy as other irreversible actions, and auto-dismiss only `beforeunload`.

**Acceptance**: a local HTML fixture representing a three-page job application (text inputs, a select, a radio group, a checkbox, a file input, an iframe section) is completed end to end by the action layer under test, with every field verified by readback.

## Phase 3: one honest page representation

There are currently two unrelated snapshot pipelines, and the one the model sees is the weaker of the two.

**Status: complete.** Results:

| Check | Before | After |
| --- | --- | --- |
| Snapshot producers | 2 unrelated (BS4 tag walk, aria formatter) | **1: `dom_extraction/snapshot.py`** |
| `aria-labelledby` names (Workday, React form libs) | deliberately unimplemented, field had no name | **resolved (Playwright accname)** |
| Open shadow DOM (Salesforce/LWC) | invisible to every consumer | **in the snapshot and in `read_form`** |
| Long form over budget | hard truncation in DOM order; bottom fields silently cut | **paginated; footer names the exact `read_page(section=N)` call; every element reachable** |
| Per-element facts | role and name only | **`ref`, `nth`, input type, required, readonly, disabled, checked, filled, options with selection, frame path** |
| `<select>` options | standalone unclickable `option` rows | **folded into the combobox line; also gone from miss-candidate lists** |
| `input[type=file]` | reported as a textbox; model typed paths into it | **`[file input]` with attachment state** |
| `input[type=hidden]` | emitted as a textbox target | **excluded** |
| Duplicate labels | `ambiguous_target` error round-trip first | **`[nth=k]` emitted up front, same ordering as the resolver** |
| Typed secrets in the snapshot | aria YAML carries live field values | **presence only, the text is never parsed out (browser test pins it)** |
| Site-specific role promotion | any div classed `hotel`/`card`/`result` became a button | **deleted, regression-pinned** |
| Screenshot side effect | full-page PNG written and discarded per `list_links` | **gone; `pympler` dropped from requirements** |
| `dom_extractor.main` contract | 3-tuple or bare string; `list_links` unpacked it char by char to `[]` | **deleted; `list_links` reads the snapshot** |
| `get_page_text` | decomposed `nav`/`header`/`footer` ("Step 2 of 5", validation summaries) | **keeps landmarks** |
| Advertised vs addressable (fixture) | unmeasurable | **0 unaddressable; test asserts every advertised target resolves** |
| Tools offered to the model | 19 | **20 (`read_page`)** |
| Tests | 177 offline + 89 browser | **194 offline + 96 browser** |

Deliberate deviations from the item list below:

- Item 4 asked for dedupe and ranking by visibility and viewport proximity alongside pagination.
  Ranking was not implemented: pagination removes the starvation problem ranking was meant to soften, DOM order keeps `nth` hints aligned with the resolver, and reordering would make the snapshot lie about the page.
  Dedupe was not implemented because collapsing duplicate role/name rows would delete exactly the `nth` information that makes duplicates addressable.
- The JS metadata pass never *adds* elements to the snapshot; it only enriches rows the aria snapshot produced.
  A JS-computed accessible name is not guaranteed to resolve through `get_by_role`, and advertising unaddressable targets is the failure mode this phase exists to end.
  Controls only the JS pass can see still surface through `read_form`, which shares the same collector.
- The executor's per-step budget (`_dom_snapshot_budget`, 3500 or 5200 chars) is unchanged, but it now bounds a *section*, not the whole page.

1. **Consolidate.** Delete `dom_extractor.get_dom_tree_and_page_screenshot` and `retrieve_interactive_elements`. Build one producer on `page.accessibility.snapshot` plus a single JS pass that walks documents, iframes, and `shadowRoot`.
2. **Emit what the model needs to act.** For each interactive element: `ref` (stable within the snapshot), role, accessible name resolved through `aria-labelledby` (currently deliberately unimplemented at `dom_extractor.py:136-140`, which is exactly how Workday and most React form libraries label inputs), tag, input type, `required`, `disabled`, `checked`, whether a value is present, `<select>` options, visibility, and frame path.
3. **Fix the type misclassification.** `input[type=file]` must not be reported as a textbox, `<select>` must carry its options rather than emitting unclickable `<option>` rows, and `type=hidden` must be filtered out entirely.
4. **Paginate rather than truncate.** The current budget is 3500 chars by default ([executor.py:948-959](backend/src/agents/executor.py:948)) with hard truncation in DOM order, so on a long form the unfilled fields at the bottom are exactly what gets cut. Raise the budget for form steps, dedupe, rank by visibility and viewport proximity, and expose `read_page(section=N)` so the model can request more instead of being silently starved.
5. **Delete the site-specific role promotion** at `dom_extractor.py:78-82` and `:474-486`, which promotes any div whose class contains `hotel`, `property`, `show-price`, `card`, or `result` to `role="button"`. That is one travel site's DOM shape baked into a generic extractor.
6. **Delete the screenshot side effect.** `dom_extractor.py:242-250` writes a full-page PNG to a hardcoded `screenshots\{title}.png` on every `list_links` call and then discards the bytes. Also remove the `pympler.asizeof` call on the whole element list.
7. **Fix the return-type contract.** `dom_extractor.main` is annotated `tuple[str, bytes]`, returns a 3-tuple on success, and returns a bare string on all four error paths. `langchain_tools.py:184` does `dom_json, *_ = await dom_extractor.main(page)`, so on any error it unpacks the string character by character, `dom_json` becomes `"{"`, and `list_links` silently returns `[]`.
8. **Stop discarding landmarks.** `get_page_text` decomposes `nav`, `header`, and `footer`, which is where "Step 2 of 5" indicators and validation summaries live.

**Acceptance**: for the Phase 2 fixture, the snapshot lists every field with its type, label, required flag, and current filled state, including the ones inside the iframe and the shadow root, and no unclickable `<option>` rows.

## Phase 4: fix the agentic control loop

**Status: complete.** Results:

| Check | Before | After |
| --- | --- | --- |
| Planner page context | fabricated `_get_simulated_page_context` | **real Phase 3 snapshot** |
| Goal storage | clarified goal logged then discarded | **stored once as `mission_goal` and reused everywhere** |
| Plan mutation | recovery decorated step text while `current_plan` stayed frozen | **fallback rewrites `current_plan` and can replan** |
| Work queue | bulk tasks had no outer-loop representation | **planner can emit `work_items`; orchestrator advances them deterministically** |
| Verifier evidence | AFTER_STATE stripped into logs | **post-action snapshot stored in `last_page_snapshot` and `verified` forwarded structurally** |
| Completion logic | verifier special-cased compose, mailbox, and finalization keywords | **structural evidence only** |
| Safety gate | sensitive actions gated by token lists | **autonomy policy** |
| Executor form gate | email-specific executor gate blocked job-application Continue / Review / Send / Finish | **deleted; finalization now only blocks on observable required empty fields** |
| Progress tracking | two competing field trackers, one compose-shaped | **one field-progress tracker fed by `read_form()` and verified field writes** |
| HITL resume | interaction re-ran before interrupts and consumed replies by call order | **memoized interaction output with correlation ids** |
| Run identity and persistence | fixed thread id and in-memory checkpoints | **per-run UUID, sqlite checkpoint support, resumable state contract** |

The executor was the last of the three files to be cleaned.

`verifier.py` and `status_tracker.py` had already lost the compose-specific branches.

`executor.py` now matches them.

1. **Give the planner the real page.** Delete `_get_simulated_page_context` and pass the Phase 3 snapshot.
2. **Store the clarified goal.** `plan.goal` is currently written into a log line and thrown away. Put it in state as `mission_goal` and use it as `MAIN_GOAL` everywhere. Strip the `USER REQUEST: ` prefix once at the source in `app.py` rather than in one agent out of four.
3. **Make the plan mutable.** Implement `revise_step`, `insert_step_before`, and a `replan` path that actually write `current_plan`. Today `FallbackStrategy.update_type` promises `insert_step_before` in both the schema and the prompt, and the code merely decorates `current_task` with a `[Then continue objective: ...]` marker.
4. **Add a work-queue construct.** For "apply to 20 jobs" or "book these three legs", add `work_items`, `current_item_index`, and `item_results` to the state, and make the outer loop deterministic while the per-item plan stays LLM-generated. This is what makes bulk tasks representable at all, and it gives the UI something real to report per item.
5. **Restore evidence to the verifier.** Put the post-action snapshot in a structured state field (`last_page_snapshot`) instead of embedding it in a log string, and stop overwriting the tail of `recent_executor_logs` with the AFTER_STATE-less synthetic log. Pass `step_index` and `total_steps` explicitly rather than hoping they survive a 2200-char clip of `mission_status`.
6. **Replace keyword gating with structural checks.** Delete the eight short-circuit branches in `verifier.py:107-389` and the compose/finalization/mailbox keyword classifiers. Judge step completion from `last_execution_event.verified`, `read_form()` completion counts, and URL and DOM deltas, then make one LLM call for the genuinely ambiguous residue. Specific misfires this removes: any step containing "find" auto-completed by any successful extraction anywhere in the run (`extracted_content` is cumulative across the whole mission); "Complete the application form" and "Review the job listing" treated as finalization steps; and unanchored substring tests where `name=to` matches `name=Total` and `name=add` matches `name=Address`.
7. **Fix the budget arithmetic.** Set `recursion_limit` well above `max_transactions` with headroom, drop the "success credits" subtraction that pushes the graceful stop out of reach, catch `GraphRecursionError` explicitly, and route it to the abort path so the user always gets a final message. Also add a per-step budget, since global counters alone cannot stop a single step from consuming the whole run.
8. **Make the control plane deterministic.** Set temperature 0 for the verifier, the decision maker, and the fallback agent. Their outputs *are* graph edges: `verifier.handoff` selects the next node and `interaction.type` decides whether the run terminates.
9. **Fix the interrupt re-entry bug.** LangGraph re-runs a node from the top when `interrupt()` resumes, and the interaction agent's LLM call sits *before* its interrupts. Every HITL round therefore pays for a second call, and at temperature 0.5 the re-run can take a different branch than the one that raised the interrupt, so the resume value is consumed by a different call site. Move the call after the interrupt or cache its result in state.
10. **Give every run its own identity and make it resumable.** Replace the hardcoded `thread_id="simulation_001"` with a per-run UUID and swap `MemorySaver` for a durable checkpointer, so a run can survive a subprocess restart and the user can resume a long job.
11. **Persist browser sessions.** Save and reuse `storage_state` per (user, domain) so the agent does not re-authenticate on every run. This is the single biggest reduction in MFA and anti-bot friction available.
12. **Replace the sensitive-action token lists with an autonomy policy.** `_SENSITIVE_TARGET_TOKENS` and `_SENSITIVE_TASK_TOKENS` currently make every click whose label contains "submit" or "confirm" a HITL stop, which is incompatible with "apply to jobs automatically", while a genuinely irreversible action whose button says "Continue" sails through. Define a policy object with a user-chosen level (observe only, confirm irreversible, autonomous within budget), a hard always-confirm list (money movement, deletion, sending on the user's behalf), and per-domain overrides. Persist the choice per user.
13. **Repair the state contract.** `made_progress` is written six times in `verifier.py` and is not in `ProjectState`. `plan_status: "UPDATE"` is declared and never written. `step_intent` is written four times and read once, as prompt text, while four agents re-derive intent with mutually inconsistent keyword lists. `handoff_interaction` is not cleared on the interaction finish path, which can loop. `login_phase` flips to `"completed"` merely because the task text stopped containing login keywords, and `orchestrator.py:215-244` then uses that to skip the login step without executing it.
14. **Fix the HITL lifecycle.** `app.py:220` reads stdin with no timeout, and `app.py:211-216` deliberately never resumes the graph after a `finish` interrupt, so the final assistant message is never committed to `messages` and the run cannot continue past an answer. Add a timeout, resume properly, and give each `interrupt()` payload a correlation id so the resume value is matched by id rather than by call order.
15. **Fix the two competing progress trackers.** `status_signals.field_progress` and `status_signals.compose_fields` both try to answer "which slots are filled" with different rules, and `status_tracker.py:568-575` back-fills one of them by string-matching a sentence the verifier wrote one line earlier. Keep one tracker, fed by `read_form()`.

**Acceptance**: a scripted multi-page fixture task runs to completion without hitting the recursion limit; an intentionally impossible task aborts gracefully with a user-facing explanation; a run interrupted mid-way resumes from its checkpoint.

## Phase 5: prompts

1. Strip the markdown scaffolding from `fallback.prompt.md` and close the unterminated fences in it and `verification.prompt.md`.
2. Remove site-specific rules from all six prompts. `verification.prompt.md:39-65` encodes Outlook and Gmail compose semantics; `orchestration.prompt.md:36` prescribes an email-specific step recipe in the generic planner. Move anything genuinely site-shaped into optional per-domain "site notes" loaded only when the current host matches, so a Gmail rule cannot affect a Workday run.
3. Rewrite `execution_tools.prompt.md` around the Phase 2 action set. About half of its current content is email compose and one university portal's SSO flow.
4. Fix the prompt-to-schema mismatches: `verification.prompt.md:16` requires a `BEFORE_STATE` the code never supplies; `fallback.prompt.md:24` requires `AFTER_STATE (URL + DOM snapshot)` while the code supplies differently-labeled fields; `fallback.prompt.md:77` tells the model the executor has a `go_back` tool that `ExecutionResult.action` does not accept; `interaction.prompt.md` documents two states while the code passes three.
5. Add a contract test that fails when a prompt names an input or output field the schema does not have.
6. Add a job-application skill module under `.agents/skills/` (the convention is already established in `AGENTS.md`) holding the answer library, question-mapping heuristics, and tailoring rules, so this domain knowledge lives outside the generic prompts.

## Phase 6: streaming and the live view

The user called this out specifically, and it is also the most visible quality signal in the product.

1. **Backend.** Pass `maxWidth`, `maxHeight`, and `everyNthFrame` to `Page.startScreencast`. Send frames as binary WebSocket messages rather than base64 inside JSON, which removes about 33 percent of the bytes and the JSON parse per frame. Keep only the newest frame when the client is behind, rather than queueing. Detach the old CDP session on page switch. Send an explicit `VIEWPORT` message with the real frame dimensions.
2. **Set a deterministic viewport** in `app.py`'s `new_context()` so frame geometry stops depending on a Playwright default.
3. **Frontend.** Render into a `<canvas>` via `createImageBitmap(blob)` and drop the per-frame data-URL allocation. Move the live view into its own component holding the frame in a ref, so a frame no longer re-renders the Dashboard and no longer re-runs the O(n) log grouping reduce.
4. **Fix the coordinate mapping.** Use the reported viewport dimensions instead of hardcoded 1280x720, clamp coordinates to the frame on both the client and the server, and attach the handler to the image rather than the padded wrapper. Add mouse-move, drag, hover, right-click, and modifier support; today only a click pair is sent, so sliders, text selection, and hover menus are unusable during a takeover.
5. **Release the keyboard.** `handleBrowserKeyDown` calls `preventDefault` unconditionally, swallowing Tab, F5, and Ctrl+R while the panel has focus, with no Escape to release it. Fix the key codes too: one path passes `e.key.charCodeAt(0)`, a character code, into what the backend forwards as `windowsVirtualKeyCode`.
6. **Allow takeover at any time,** not only during a HITL pause. This is the escape hatch when the agent is stuck on a CAPTCHA or an unusual widget, and it is the honest answer to anti-bot challenges.

**Acceptance**: a sustained run holds a stable frame rate with the log panel scrollable and responsive, and a takeover click lands within a few pixels of the target at any panel size.

## Phase 7: make the frontend a product

1. **Stop button.** The backend already implements abort and stop words; the word "abort" appears nowhere in the frontend. Today the only way to halt an agent mid-application is to type "stop" into the chat box and hope it matches. This is the single most important missing control.
2. **Real run status.** `startAgentSession` hardcodes `status: "running"` and `markSessionFinished` only ever writes `"finished"`, so every terminated run renders as "Complete", including crashes. Add succeeded, failed, and aborted with an exit reason. For "apply to 20 jobs" the user must be able to see which applications actually submitted.
3. **Persist runs server-side.** Conversations, logs, and sessions are in-memory only, so a refresh loses every transcript while the card number persists in `localStorage`. Add a runs table with prompt, status, timeline, artifacts, and an audit trail of what the agent did with the user's data.
4. **Multi-run support.** The backend maintains a ten-port pool; the frontend has one socket, one `isAgentRunning`, and one `liveFrame`. Key all three by session id so the user can apply to several jobs at once.
5. **Fix the socket lifecycle.** Add an identity guard in `onclose` (a stale close currently reverts a freshly started run to "Idle"), add `onerror` and `onopen`, add reconnect with backoff and a connection indicator, guard `JSON.parse`, and add an in-flight guard so a double Enter cannot orphan a socket and leak an agent subprocess plus a pool port.
6. **Replace log-substring HITL detection.** The frontend infers HITL by searching agent log text for `[NODE]: __INTERRUPT__`, which races the structured `CLARIFICATION` message and is influenceable by page content the agent reads. Use only the structured messages.
7. **Structured HITL.** The backend already sends `requested_fields`; the frontend discards it and shows a blank chat box. Render a labeled form. When the agent needs "desired salary", ask for desired salary.
8. **Fix the log panel.** STDERR has no styling and no icon, so tracebacks are indistinguishable from routine output. `sanitizeAgentLogLine` drops any line ending in a colon and collapses whitespace, mangling tracebacks and JSON in the one panel meant for debugging. Autoscroll fires on every frame, so the user cannot scroll up to read earlier output while a run is live. Cap and virtualize the list.
9. **Result artifacts.** Keep the final screenshot, the confirmation page capture, extracted structured output, and any downloaded files, and surface them per run. Right now `liveFrame` is nulled on close and the panel is hidden, so a completed application leaves no evidence.
10. **Document store.** Add resume and cover-letter upload, wired to Phase 2's `upload_file`. The Experience tab already collects structured work history and there is no file input anywhere.
11. **Multi-line prompt input** with Shift+Enter and an IME composition guard. It is currently a single-line `<input>` that submits on bare Enter, so a multi-paragraph brief cannot be pasted and CJK users submit mid-composition.
12. **Job queue UI.** A list of job URLs in, a per-application result out, backed by Phase 4's work queue.
13. **Environment configuration.** There is no `import.meta.env` usage anywhere and the backend target is hardcoded in `vite.config.js`, so a production build can only talk to same-origin `/api`.
14. **Delete the dead code**: `UserCredentialsCard.jsx`, `App.css`, the commented-out `handleSend` block, the `axios` dependency it keeps alive, and the hardcoded `ws://localhost:8000` string. Wire up or remove the non-functional "Reset Password", "Delete Account", and `agentPrompt` controls; a setting that silently does nothing is worse than no setting.
15. **Modal hygiene.** Neither modal has `role="dialog"`, a focus trap, Escape handling, or a cancel path; the credentials modal's only close affordance commits the changes. Also reset the child's tab state and the parent's view state together, and make persistence consistent: list fields save on every keystroke while name, address, phone, and email save only on submit.

## Phase 8: tests and CI

1. **HTML fixtures, no network.** Build `backend/tests/fixtures/` with a multi-page job application (text, select, radio, checkbox, file input, iframe, shadow DOM, client-side validation, a confirmation page), a login form with a second-factor step, and a listing page with duplicate link text. Serve them from a local static server in a fixture. Every action-layer test runs against these.
2. **Unit tests for every Phase 2 primitive,** including the failure modes: ambiguous target, element behind an overlay, value that does not survive `fill`, checkbox already checked, upload rejected by type.
3. **Regression tests for each confirmed bug in this document,** so they cannot come back. At minimum: the Google URL rewrite, the compose gate blocking a job-application Continue click, the budget arithmetic, the AFTER_STATE strip, the `execution` package shadow, and the login auth bypass.
4. **Contract tests** for prompt-to-schema field parity and for `ProjectState` key coverage (every key written by an agent must be declared).
5. **CI.** Add a `pull_request` trigger. Run `pytest`, `eslint`, and `npm run build` on every PR. Pin `appleboy/ssh-action` and `appleboy/scp-action` to commit SHAs instead of `master`. Fix the deploy script, where `pip install -r requirements.txt` runs from `$HOME` (the file is in the repo directory) and the `git reset --hard` that updates the code runs *after* that install, and where `rm -rf htdocs/*` runs before the upload so a later failure leaves the site empty.

---

# Out of scope for one prompt

These matter, but they need a decision, an account, or a body of work that does not fit alongside the above.

**Rotate the committed database password.** Phase 0 untracked `backend/configs/user_db_config.yaml` and moved configuration to `DB_*` environment variables, but the file is still in git history along with the private VPC address `172.31.46.153`. Removing it from the index does not remove it from history. Rotating the credential is the actual fix, and if the repo was ever public or shared, treat it as compromised. This needs your call on whether to rewrite history or simply rotate and move on. The local copy of the file was left on disk untouched so your development setup keeps working.

**Anti-bot posture.** The browser is trivially fingerprintable: stock Chromium, no user agent, no locale, `navigator.webdriver === true`. In-page challenges (Turnstile, reCAPTCHA, PerimeterX "Press and Hold") are served at the same URL, so the URL-only detector at `executor.py:1831-1868` cannot see them, and the agent keeps force-clicking into an invisible overlay while reporting success. The defensible fixes are in scope: detect challenges by page content, persist `storage_state` so you authenticate less often, hand control to the user via the live view when a challenge appears, and prefer official APIs where they exist. Building or integrating CAPTCHA solving is not something I would add, and many job boards and airlines prohibit automated access in their terms. Worth reading the terms for your target sites before scaling this up.

**Legal review of automated job applications.** Several major ATS platforms prohibit automated submission. This is a product decision with real consequences for the user's candidacy, not an engineering one.

**Async database layer.** Moving from psycopg2 to asyncpg with SQLAlchemy and Alembic migrations is the right destination, and it is a self-contained project. Phase 1's connection pool is the correct interim step.

**Horizontal scaling.** The real answer to concurrency is containerized browser workers behind a queue, not a ten-port pool on one box. Worth designing once the single-node path is solid.

**Model and prompt evaluation harness.** There is already an `orchestrator-benchmarking` branch. A proper eval set with per-agent metrics deserves its own effort, and it is what would tell you whether a prompt change actually helped.

**TypeScript migration and an accessibility audit** for the frontend. Both are worthwhile, both are large, and neither blocks the agent work.

**The 29 MB of screenshots in the working tree.** `screenshots/`, `backend/screenshots/`, and `backend/Prototype/screenshots/` hold run artifacts, several with filenames containing personal information (a search for your own name, a student portal login, a sign-in page). They are gitignored, so this is a local cleanup, but you should decide what to keep before anything sweeps the directory.

**Unmerged branches.** There are around 20 remote branches, including `codex/agentic-job-workflow-audit` at the same commit as `main` and several unmerged feature branches. Reconciling them is a separate exercise, and doing it blind risks losing work.

---

# Suggested execution order for a single continuous run

Phases 0 and 1 first, in full. They are prerequisites for trusting anything else.
Then Phase 2 and Phase 3 together, since the action layer and the page representation are two halves of one interface.
Then Phase 4, which is where the agent stops being brittle.
Phase 5 is cheap and should ride along with Phase 4.
Phases 6, 7, and 8 can proceed in parallel with each other once 0 through 4 are done.

If the run has to stop early, the natural checkpoints are: after Phase 1 (safe), after Phase 3 (capable), after Phase 4 (reliable).
