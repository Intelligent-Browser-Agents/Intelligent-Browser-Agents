# Issue: Executor cannot act on paginated snapshot content (Apple careers run loops to abort)

Status: **closed** (implemented 2026-08-10)
Branch: `Edwin-after-grad`
Opened: 2026-08-10
Closed with: the six fixes below, plus a wait_for guard found during verification.

## Results

Offline suite: 279 passed (13 new tests: read_page feedback, repeat guard, `fill(press_enter=True)`, tautological wait_for).
Browser suite: 96 passed against the local fixture, including the new fill/wait_for cases.

Live e2e rerun of the original prompt (empty credential vault, headless):

- Transactions 1-11: navigate -> `fill(combobox 'Search by role or keyword', 'software engineer', press_enter=True)` (the model chose the new argument unprompted; the search committed) -> `click(link 'Software Engineer 200674638')` -> `click(link 'Submit Resume: Software Engineer 200674638-3337')`.
- The Submit Resume click was held at the sensitive-action checkpoint for explicit user approval, by design. Run 1 burned 83 transactions and never reached any of this.
- Zero `read_page` calls (the 12k executor budget put the filtered results in view), zero overlay misdiagnoses; the three fallbacks were all sensible on-page revisions.
- The run then followed the apply flow to Apple's sign-in page and correctly concluded the user must log in ("Prompt the user to log in or create the Apple applicant account... do not interact with the page further"). With no user present it idled at that wall on tautological `wait_for(url_contains="apple.com")` calls until manually stopped; that produced the extra wait_for guard below. In the product this wall is where the user takes over the live view. Nothing was submitted to Apple and no account was created.

Additional fix from verification: `do_wait_for` now says when a `url_contains` condition was already true at call time (0s elapsed) and suggests waiting on a future state, so a login-wall step cannot "succeed" instantly every cycle.
Evidence: run `8975c575-b683-40e9-aeb6-297fd1e33495` ("apply to apple as a software engineer"), aborted at the 80-transaction safety stop on the unfiltered `jobs.apple.com/en-us/search?location=united-states-USA` results page, one click away from a job's Submit Resume button.

## What happened in the run

The agent reached the Apple careers search page in 5 transactions, then spent the remaining ~75 in three loops:

1. `read_page(section=2)` was called five times in a row and never acted on.
2. The verifier and fallback diagnosed a nonexistent "expanded global Apple navigation overlay" and spent several plans trying to close it.
3. The search keyword was typed twice but never committed, so the executor clicked the closest match on the unfiltered list ("AI Test Engineer, Sensing & Connectivity"), which the verifier rejected for not being literally a "Software Engineer" posting.

## Root causes (each reproduced against the live site with `backend`'s own snapshot/action code)

### 1. `read_page` output is thrown away before the next executor call

`Executor.__call__` always renders `DOM_SNAPSHOT` as section 1 (`_get_real_dom_snapshot(..., section=1)` default).
When the model calls `read_page(section=N)`, the section body goes into `extracted_text`, but `_finish_from_result` only surfaces `extracted_text` in `AFTER_STATE` for `extract_content`.
The next executor prompt therefore contains section 1 again plus a `PREVIOUS_ACTIONS` line saying only "Section 2 of 5 (238 elements total).".
The model reads section 2, the harness discards it, and the model's only rational next move is to read it again.

Reproduced: on the unfiltered results page the only literal "Software Engineer" link ("Software Engineer - Apple Services 200676478") is in section 2 of 5.
The executor was told to click a Software Engineer posting, could not see one in section 1, and read section 2 five times without ever being shown what it read.

### 2. `read_page` output also pollutes the report pipeline

`_finish_from_result` appends any non-empty `extracted_text` to `state["extracted_content"]`, which feeds the final user-facing report and the orchestrator's `_has_reportable_content` heuristic.
Raw DOM section dumps do not belong there; only `extract_content` output does.

### 3. Judges only ever see the nav-heavy top of the page

`AFTER_STATE` for every action is section 1, whose first ~21 rows on any Apple page are the global nav (Store, Mac, iPad, ...).
The verifier and fallback, seeing wall-to-wall nav links and "nothing changed", concluded a navigation overlay was open and planned around closing it.
Nothing was open; that is simply what the top of the accessibility tree looks like.

### 4. The search commit path is fragile

Reproduced live:

- `fill(combobox 'Search by role or keyword') + Enter` on the careers landing page commits the search and lands on `?search=Software%20Engineer&sort=relevance`, whose results contain 18 literal "Software Engineer" links, most in section 1. The whole failure chain dissolves when the search commits.
- The suggestion listbox holds up to 10 duplicate "Software Engineer" options (some hidden). Clicking one is unreliable, and in the run it clicked a stale/hidden duplicate ("no observable change") which moved focus off the field.
- `press_key(Enter)` uses `page.keyboard.press`, so after focus was stolen the Enter went to `<body>` and did nothing. The typed keyword was never committed, which is why the run ended on the unfiltered list.

### 5. No deterministic guard against verbatim action repetition

The executor prompt forbids repeating actions, but nothing structural stops the same `(action, args)` running five times.
Each wasted cycle costs ~4 transactions (orchestrator, executor, verifier, +fallback).

### 6. The transaction budget cannot fit the mission even when everything works

`max_transactions = 80` with ~4 transactions per browser action allows roughly 20 actions.
Search, select a posting, sign in, and a multi-page application form need well more than 20 even with zero retries.

## Fix plan

1. Feed `read_page` output forward: `AFTER_STATE` and `last_page_snapshot` become the section that was read, and the next executor prompt includes it as an actionable block. Stop appending it to `extracted_content`.
2. Raise the executor's own snapshot budget (separate from the per-section default) so typical pages fit without pagination; pagination stays for genuinely huge pages.
3. Add `press_enter` to `fill` so a search can be committed on the field that was just filled, immune to focus theft; document it in the executor prompt.
4. Deterministic repeat guard in the executor: a tool call identical to the immediately previous successful one is rejected with a message telling the model what that call already returned.
5. Raise `max_transactions` to 160 (~40 actions, env-overridable via `AGENT_MAX_TRANSACTIONS`) so legitimate multi-page flows are not killed mid-form; the recursion-limit headroom logic is unchanged.
6. Add `langgraph-checkpoint-sqlite` to requirements.txt (startup log in this run warned it is missing, forcing in-memory checkpoints).
7. (Found during verification) `do_wait_for` reports an already-true `url_contains` condition as a 0-second no-op with guidance, instead of a plain success indistinguishable from a real wait.

## Acceptance

- Offline test suite green, with new tests covering the read_page feedback path, the repeat guard, and `fill(press_enter=True)`.
- Live e2e rerun of the original prompt reaches a Software Engineer posting's application flow (Submit Resume / sign-in gate) without a read_page loop and without the overlay misdiagnosis.
