# Issue: Phase 8 - offline fixtures, regression coverage, and CI that runs on pull requests

Status: **closed** (implemented 2026-08-31)
Branch: `Edwin-after-grad`
Opened: 2026-08-31
Plan reference: `docs/IMPROVEMENT_PLAN.md`, Phase 8

Closed with: the full scope below.
Verification: 306 offline and 124 browser tests green (from 266 and 96), and `pytest -m ""` green at 432 passed / 3 xfailed with nothing deselected. eslint and `npm run build` clean, `npm ci` reproducible from the lockfile.
Every acceptance item was checked directly, including the one that mattered most: the Google URL rewrite was still live in `executor.py`, the new regression test failed against it, and it passes against the fix.
Results table in the plan doc's Phase 8 section.

Two defects surfaced that were not in the original scope and were fixed here.
An uncommitted revert of Phase 5's `file_path` alias sat in the working tree and would have broken every JSON-mode upload.
And `test_verifier_marks_success_and_resets_attempts` had been failing since Phase 3 without anyone noticing, because `llm`-marked tests are deselected by default and no one ran the full suite; it asserted the pre-Phase-3 contract where an executor's unverified claim of success was enough.

Carried out of scope: `npm audit` reports 10 high-severity advisories in `react-router-dom` 7.13.1, fixed in 7.14.2.
Most are SSR/RSC-specific and this is a client-rendered SPA, but the open-redirect pair (backslash in `<Link>`/`useNavigate`, and protocol-relative `//` reinterpretation) does apply.
A router upgrade needs its own verification pass across every route, so it is not folded into a tests-and-CI change.

## Why

The suite is green (266 offline plus 96 browser tests) but it does not yet defend the things Phase 8 exists to defend.

**Tests reach the public internet.**
`test_action_system.py`, `execution/test_handlers.py`, and `execution/test_integration.py` drive real Chromium against `google.com`, `example.com`, and `wikipedia.org`.
Google in particular serves an anti-bot interstitial to automated Chromium, so these assert against a page that changes without notice.
`test_action_system.py`'s own docstring already names Phase 8 as the fix.
CI cannot run them, which means the 96 browser tests, the only tests that exercise the real action layer, would never run on a pull request.

**The action layer's documented failure modes are untested.**
`test_action_layer.py` covers ambiguity, readonly fill, checkbox idempotence, and a missing upload file.
Three failure modes the plan names are missing: an element behind an overlay, a value that does not survive `fill`, and an upload rejected by the input's `accept` type.
Each is a silent-success path, the defect class Phase 2 was written to close.

**Two confirmed bugs have no regression test, and one of them is still live.**
The plan's item 3 names six bugs.
Four are covered (compose gate, budget arithmetic, AFTER_STATE strip, login auth bypass).
The `execution` package shadow that once aborted collection for the whole suite is guarded only by a `pyproject.toml` setting that nothing asserts.
And the **Google URL rewrite is not fixed**: [executor.py:1276-1279](backend/src/agents/executor.py:1276) still rewrites any Google-owned host to `https://duckduckgo.com` unless the task text happens to contain the word "google", exactly as documented at plan lines 26-36.
`mail.google.com`, `docs.google.com/forms/...`, and `accounts.google.com/signin` are all silently redirected.
Google Forms is a common application host and `accounts.google.com` is the "Sign in with Google" hop on Greenhouse, Lever, and Workday, so this breaks real applications today.

**Contract coverage is half done.**
Phase 5 added eight prompt-to-schema parity tests.
The other half of the plan's item 4, `ProjectState` key coverage, does not exist: an agent node can return a key that is not declared in the `TypedDict`, LangGraph will drop it, and nothing fails.

**CI does not test anything.**
`.github/workflows/main.yml` triggers only on push to `main` and runs `npm install && npm run build`.
No `pytest`, no `eslint`, no `pull_request` trigger.
`appleboy/ssh-action@master` and `appleboy/scp-action@master` are unpinned, so a third party controls what runs against the deploy key.
The deploy script has three ordering bugs: `pip install -r requirements.txt` runs from `$HOME` where the file does not exist, the `git reset --hard` that fetches the new code runs *after* that install, and `rm -rf htdocs/*` empties the site before the upload so any later failure leaves it blank.

Separately, an uncommitted working-tree edit to `backend/src/schema.py` reverts the `file_path` validation alias on `ExecutionArgs.document_id` that Phase 5 added in a40b626.
`execution_tools.prompt.md:37` documents the argument as `upload_file(file_path=...)`, so without the alias every JSON-mode upload silently loses its path.

## What

### 1. Offline fixtures served over HTTP

Serve `backend/tests/fixtures/` from a `ThreadingHTTPServer` on an ephemeral port, session-scoped, in `conftest.py`.
HTTP rather than `file://` because the multi-page flow needs same-origin iframes, form posts, and redirects, none of which behave normally under `file://`.

New fixture pages, alongside the existing `job_application.html` (which stays as-is; 30 passing tests address it):

- A multi-page job application: personal details with client-side validation, then work authorization with an EEO iframe and a shadow-DOM referral widget, then a confirmation page.
- A login form with a second-factor step.
- A listing page with duplicate link text ("Apply" repeated per row).
- A page with an overlay covering a button, and a file input restricted by `accept`.

### 2. Unit tests for every Phase 2 primitive

Add the three missing failure modes: element behind an overlay, value that does not survive `fill`, upload rejected by type.
Keep every assertion on an observable post-condition rather than the action's own status string.

### 3. Regression tests for each confirmed bug

- **Fix the Google URL rewrite** and pin it: `mail.google.com`, `docs.google.com/forms/...`, and `accounts.google.com/signin` must be navigated to verbatim.
- Assert the `execution` package resolves to `backend/src/execution`, so the shadowing collision cannot return.
- Assert the `file_path` alias on `document_id` survives.
- Verify the four already-covered bugs still have a test each and label them consistently.

### 4. Contract test for `ProjectState` key coverage

Every key any agent node returns must be declared in `ProjectState`.

### 5. CI

- `pull_request` trigger running `pytest` (offline and browser), `eslint`, and `npm run build`.
- Pin `appleboy/ssh-action` and `appleboy/scp-action` to commit SHAs.
- Fix the deploy script: fetch code first, install from the repo directory, and upload before clearing the old site.
- Keep deploy on push to `main` only.

## Non-goals

- Coverage thresholds or a coverage gate.
- Rewriting the `llm`-marked tests to run in CI; they make billable calls and stay opt-in.
- The async database migration and credential rotation, both parked in the plan's out-of-scope section.

## Acceptance

- `pytest -m browser` passes with the network disabled.
- No test in the suite resolves a public hostname.
- A pull request runs backend tests, frontend lint, and frontend build, and a failure in any one blocks the merge.
- Navigating to `docs.google.com/forms/...` for a task that never says "google" reaches Google Forms.
- Adding an undeclared key to an agent's return value fails a test.
- Both deploy actions are pinned to SHAs, and a deploy that fails midway leaves the previous site serving.
