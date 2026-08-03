# Continuing: Intelligent-Browser-Agents, finish Phase 4

## Context

UCF senior-design LangGraph + Playwright browser agent.
The goal is not the demo scope: it is to autonomously complete long, stateful web tasks on my behalf, primarily **applying to jobs unattended**, plus booking travel and acting as me on sites where I have saved credentials.

Read `docs/IMPROVEMENT_PLAN.md` first.
It is the audited source of truth: verified defects with file:line evidence, measured before/after tables per phase, and an explicit out-of-scope list.
Do not re-derive its findings.

Then read `docs/issues/phase-4-control-loop.md`, the open issue for this work.

Branch: `Edwin-after-grad`, at the tip (`git log -1`).
Work continues on this branch.
Never delete or force-push other branches; the repo has ~20 from a 10-person team.

## Machine setup (none of this is in git)

    git checkout Edwin-after-grad && git pull

    python -m venv .venv
    .\.venv\Scripts\Activate.ps1        # or source .venv/bin/activate
    pip install -r requirements-dev.txt
    python -m playwright install chromium

    cd frontend && npm install && cd ..

Create `.env` in the **repo root**:

    OPENAI_API_KEY=...      # required; all six agents use OpenAI
    TOKEN_SECRET=...        # long random string, signs JWTs
    CREDENTIALS_KEY=...     # Fernet key, see below. MUST stay stable.
    ALLOWED_ORIGINS=http://localhost:5173
    EMAIL_ACCOUNT=...       # only for forgot-password mail
    EMAIL_PASSWORD=...

Generate the Fernet key once:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

If `CREDENTIALS_KEY` changes, every saved credential vault becomes unreadable.
Copy the value from the other machine rather than generating a new one.

Postgres: set `DB_NAME` / `DB_USER` / `DB_PASSWORD` / `DB_HOST` / `DB_PORT`, or copy `backend/configs/user_db_config.example.yaml` to `user_db_config.yaml` (gitignored; env vars win).
The server creates the `user_credentials` table itself on startup.

## The state you are inheriting

**The offline suite is green.**

    pytest -q                       # 194 passed, 4 xfailed, 98 deselected
    pytest -m browser -q            # expect green (needs Chromium + network)
    cd frontend && npx eslint .     # expect 0 errors, 1 warning

Phases 0, 1, 2 and 3 are complete. Do not redo them.
Phase 4 is functionally complete except for the two items below (work-item
population, and the three deferred Phase-3-to-4 wires). Everything else in
the "Phase 4" section of `docs/IMPROVEMENT_PLAN.md` (items 1, 2, 3, 5, 6, 7,
8, 9, 10, 11, 13, 14, 15) has landed:

- `backend/src/autonomy.py` (new): the autonomy policy replacing the
  sensitive-token gate. Three levels (observe_only, confirm_irreversible,
  autonomous), a hard always-confirm list no level bypasses, per-domain
  overrides. Written and unit-tested (`backend/tests/test_autonomy.py`).
  **The executor is not wired to it yet** — see wire 3 below.
- `backend/src/agents/verifier.py`: rewritten around structural evidence
  (executor status, the `field_progress` tracker, URL/DOM deltas between
  consecutive `dom_cache` snapshots). The compose/mailbox/finalization
  keyword branches are gone (plan item 6).
- `backend/src/agents/fallback.py`: `revise_step` and `insert_step_before`
  now mutate `current_plan` for real, instead of decorating `current_task`
  with `[Recovery Hint: ...]` / `[Then continue objective: ...]` markers
  while the plan stayed frozen (plan item 3). A `replan` escalation
  (`plan_status="CREATE"`, empty `current_plan`) fires when a detected action
  loop persists after step-level recovery has already been tried — this is a
  deterministic pre-LLM branch, not a new `FallbackStrategy.update_type`
  value, so **no schema.py change was needed for it** (the previous version
  of this handoff said otherwise; that turned out to be avoidable).
- `backend/src/agents/orchestrator.py`: `_get_simulated_page_context` is
  gone; the planner reads the real snapshot via `state["last_page_snapshot"]`
  / `dom_cache` (plan item 1). `mission_goal` is written once by the planner
  and read by every agent via `state.get_mission_goal()` (plan item 2). The
  abort-budget "success credit" subtraction is gone — it's a plain counter
  now (plan item 7). A new `goal_retry_cycles` counter caps the one loop none
  of the other brakes catch: the final step verifying complete while the
  overall goal does not (see `Orchestrator._GOAL_RETRY_CAP`). Work-queue
  *advancement* is implemented (`_complete_or_next_item`): when
  `state["work_items"]` is non-empty and a mission completes, it advances to
  the next item instead of ending. **Nothing populates `work_items` yet** —
  see the work-queue gap below.
- `backend/src/status_tracker.py`: one `field_progress` tracker fed by
  `read_form` rows and verified field-write actions (`fill`, `select_option`,
  `set_checkbox`, `upload_file` — deliberately not the legacy untargeted
  `type`, which Phase 2 gives no readback guarantee for), replacing the two
  competing trackers (plan item 15). `login_phase` reaches `"completed"`
  only on verifier evidence (a verified `authenticate`-intent step) or MFA
  HITL completion, never on task wording losing login keywords.
- `backend/src/agents/interaction.py`: the interrupt re-entry bug is fixed
  (plan item 9). LangGraph re-runs a node from the top on resume; the LLM
  response is now memoized on a fingerprint of the input state so the replay
  reuses the first response rather than paying for a second call that could
  sample a different branch. Every `interrupt()` payload carries a
  deterministic `correlation_id`; a resume value is matched by id, not by
  call order (`InteractionAgent._ask_user`).
- `backend/src/app.py`: per-run UUID `thread_id` (`--run_id`), a durable
  sqlite checkpointer when `langgraph-checkpoint-sqlite` is installed
  (falls back to `MemorySaver` with a logged notice otherwise — see wire 4),
  `recursion_limit` set with real headroom above `max_transactions`
  (`_TRANSACTION_HEADROOM`) so the graceful abort always gets to run before
  LangGraph's own hard ceiling, `GraphRecursionError` caught explicitly and
  routed to a user-facing message instead of a silent traceback, a stdin
  timeout on the HITL wait (`_HITL_INPUT_TIMEOUT_SECONDS`), the "finish"
  interrupt is now actually resumed so the interaction node's own state
  update commits instead of being lost, and per-user browser session
  (`storage_state`) persistence under `backend/.browser_sessions/` (plan
  items 10, 11, 14).
- `backend/server.py`: passes `--run_id` / `--session_key` to the agent
  subprocess and sends the client a `{"type": "run_started", "run_id": ...}`
  frame. Nothing yet consumes that frame to build a "resume this run" UI —
  reasonable next step, not started.
- State contract cleanup (plan item 13): `made_progress` is a local control
  signal passed as a keyword argument now, not written into `ProjectState`;
  `plan_status` actually reaches `"UPDATE"` (from fallback's plan mutations)
  and `"CREATE"` (from replan/next-work-item); `mission_goal`,
  `last_page_snapshot`, `goal_retry_cycles`, `work_items`,
  `current_item_index`, `item_results`, `autonomy_policy` are declared
  fields, not ad hoc dict keys.

### What changed in the test suite

`backend/tests/test_control_flow.py` and `backend/tests/test_fallback.py`
had ~18 tests pinning the deleted compose/mailbox keyword classifiers, the
old bracket-marker recovery format, and the old success-credit abort
arithmetic. Each was individually triaged: methods that no longer exist
(`Verifier._recipient_step_confirmed`, `Verifier._is_email_compose_step`,
`Fallback._enforce_directional_recovery`, etc.) got their tests deleted;
tests whose *contract* changed (fallback rewrite tests, the popup-recovery
test, the abort-arithmetic test) got rewritten against the new behavior;
one test (`test_verifier_does_not_complete_recipient_step_from_generic_field_progress_only`)
encoded email-recipient-picker-specific caution that Phase 4 intentionally
stops special-casing, and was deleted rather than preserved — flagging this
one explicitly since it is a judgment call, not a mechanical rename. New
tests were added for `goal_retry_cycles`, the work-queue advancement helper,
generic (non-email) field-progress completion, `autonomy.py`, and the
interaction correlation-id matching. `pytest -q` is green.

## Two things still open

### 1. The work-item population gap

The deterministic *advancement* half of the work queue (plan item 4) is
done: `Orchestrator._complete_or_next_item` advances `current_item_index`
and restarts planning for the next item when `state["work_items"]` is
non-empty. **Nothing populates `work_items` in the first place.** A request
like "apply to these 3 jobs: <url1>, <url2>, <url3>" today just becomes one
ordinary plan; the bulk structure is never extracted into
`state["work_items"]`.

The natural place is `OrchestratorPlan` in `schema.py`: add an optional
`work_items: List[dict]` (or a small `WorkItem` model with `description` and
`url`) that the planner populates when it recognizes a bulk task, and have
`Orchestrator._create_plan` seed `state["work_items"]`/`current_item_index`
from it when present. Write the acceptance test first: a plan prompt like
"apply to these 3 job postings: ..." should produce `work_items` of length 3
and a first-item plan scoped to just that one posting.

### 2. The three deferred Phase 3-to-4 wires

Phase 3 has landed and these files are no longer being touched concurrently,
so all three are safe to do now. All three were re-verified as still open
against the current `executor.py` / `schema.py` immediately before writing
this handoff:

1. **Write the post-action snapshot into `state["last_page_snapshot"]`.**
   `executor.py`'s `_finish_from_result` (around line 1267) already computes
   `after_state` from `_get_real_dom_snapshot` and folds it into the
   execution log string, and a few lines later (around 1304-1309) writes a
   *different* snapshot into `dom_cache`. Add
   `out["last_page_snapshot"] = after_state` alongside that. The verifier
   and orchestrator already prefer this field when present
   (`Verifier.__call__`, `Orchestrator._get_page_context`) — this is a
   pure producer-side addition, no consumer-side change needed.
2. **Forward the Phase 2 `verified` flag into `last_execution_event`.**
   `execution/models.py`'s `ExecutionOutput` already carries `verified: bool`
   (Phase 2's post-condition readback: `fill` re-reads `input_value()`,
   `select_option` re-reads the selected value, etc.), but
   `schema.LastExecutionEvent` has no field for it and
   `executor.py::_last_execution_event_dict` (called from `_finish_from_result`,
   around line 1293) does not pass it through. Add
   `verified: Optional[bool] = None` to `LastExecutionEvent` in `schema.py`,
   thread `verified=result.verified` through the constructor call, and
   `Verifier.__call__` will start reading a real value instead of always
   seeing `None` (see the `event_verified` tri-state read near the top of
   the verifier, already written to consume this once it exists).
3. **Replace `_sensitive_action_reason`'s token lists with `autonomy.assess_action`.**
   `executor.py` lines ~75-111 (`_SENSITIVE_TARGET_TOKENS`,
   `_SENSITIVE_TASK_TOKENS`) and ~609-636 (`_sensitive_action_reason`) are
   the pre-Phase-4 gate: every click whose label contains "submit" is a HITL
   stop, which is incompatible with "apply to jobs automatically." Replace
   the two call sites (~310, ~444) with
   `autonomy.assess_action(action, args, policy=state.get("autonomy_policy"), url=state.get("current_url"))`
   and gate on `decision["mode"] == "confirm"`. The module is written and
   unit-tested; this is purely wiring it in.
4. **Add `langgraph-checkpoint-sqlite` to `requirements.txt`.**
   `app.py::_build_checkpointer` already tries to import
   `langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver` and falls back to
   `MemorySaver` with a logged notice when it is not installed (verified:
   the package is absent from the current venv, so every run today is
   using the in-memory fallback). Add the dependency, confirm
   `AsyncSqliteSaver.from_conn_string(path)` is the correct entry point for
   whatever version you pin, and that a run's checkpoint actually survives
   killing and restarting the subprocess with the same `--run_id`.

## Three confirmed defects in the Phase 3 code, found by review after it was written

These are real, reproduced on the pinned Playwright 1.58, and **re-verified as
still present** immediately before writing this handoff. Fix them before
building on the snapshot.

**1. Single-quoted aria keys are silently dropped (high).**
`backend/src/dom_extraction/snapshot.py:96`, the `_ARIA_ROW` regex.
Playwright's `yamlEscapeKeyIfNeeded` wraps the whole `role "name" [attrs]` key in single quotes when the accessible name contains `': '`, `' #'`, `{`, `}`, or a backtick.
Verified live: `<button>Step 2: Continue</button>` emits `- 'button "Step 2: Continue"'`, and an input labeled `Apt #` emits `- 'textbox "Apt #"'`.
`_ARIA_ROW` requires `[a-zA-Z]` immediately after `- `, so those rows fail to match and are skipped with no marker.
The element then vanishes from the snapshot, from `element_inventory`, and from `suggest_candidates`.
Names like "Apt #", "Phone #" and "Step 2 of 5" are routine on job applications, so real fields become invisible.
Fix: unwrap the single-quoted key (undoing YAML `''` doubling) before matching. Add tests for `': '`, `' #'`, `{`, `}`, and backtick names.

**2. `read_page` re-sections at a different budget than the snapshot that advertised it (medium).**
`backend/src/execution/actions.py:675`, `do_read_page` (re-verified: still hardcodes `max_chars=4000` for both `section_count` and `render`).
`PageSnapshot._sections` packs rows into chunks of `max(400, max_chars - 220)`, so section boundaries depend on `max_chars`.
The executor renders at whatever `_dom_snapshot_budget` returns and the after-state at 2200, neither of which is 4000.
Under a smaller budget, section 1 ends earlier and tells the model to call `read_page(section=2)`, which starts at the 4000-budget's boundary instead — rows in between are shown by neither call, and the model is told coverage is complete.
Reproduced offline with 120 form rows: elements 38 to 43 are unreachable through any sequence of advertised calls.
This is the exact silent-loss failure the module was written to end.
Fix: one shared budget constant across `_get_real_dom_snapshot`, the after-state render, and `do_read_page`, or thread the budget through so section numbers always refer to one canonical sectioning.

**3. Options nested under a `group` row inside a listbox are lost (medium).**
`backend/src/dom_extraction/snapshot.py:509`, `_flatten_aria_nodes` (re-verified: still only scans `node.children` directly for `role == "option"` when `role in {"combobox", "listbox"}`, and does not recurse into intermediate wrapper rows).
A grouped ARIA listbox (options nested one level under a `group` node) renders with no options, and the option elements themselves are also dropped since recursion into children is skipped entirely for combobox/listbox roles.

A fourth review lens (tests, contracts, and a secrets re-verification) did not finish because the session hit its usage limit.
Re-running a review over `backend/src/dom_extraction/snapshot.py` and `backend/src/execution/actions.py` is worth the tokens before you build on them.

## Things to know before you touch anything

1. **`TEMPERATURES` in `backend/src/models.py` is inert.**
   gpt-5.x accepts only `temperature=1.0`; langchain-openai silently drops anything else (verified: passing 0.0 stores None).
   Sampling cannot be turned down.
   Determinism must come from structural checks on observable state, for example `Verifier._credentials_still_requested`.
   A test pins this.
   Plan item 8 ("set temperature 0 for the verifier, decision maker and fallback agent") is **not achievable as written** for this reason. It has been implemented as structural determinism throughout instead (see the verifier's structural-signals section and the orchestrator's deterministic early-return branches); consider the plan text corrected by this handoff rather than still open.

2. **The `xfail(strict=True)` tests are deliberate.**
   Each names the phase that fixes it.
   They assert intended behaviour the code does not have yet.
   Do not delete markers to get green: fix the defect and strict mode will tell you to remove the marker.
   One xfail (`test_status_tracker_infers_subject_and_body_for_generic_write_email_step`) was removed during this pass rather than left to flip: its premise (implicit subject+body inference for a generic "write an email" task with no explicit field wording) is a compose-specific heuristic Phase 4 deletes outright, not a bug Phase 4 fixes, so the marker's own reasoning no longer applied.

3. **The default suite is offline and free.**
   `backend/tests/conftest.py` swaps in deterministic LLM stubs unless a test is marked `llm`.
   Keep new tests offline. Note that the stub always returns the same fixed
   response per schema (e.g. `VerificationResult.step_complete=True` always,
   `FallbackStrategy.proposed_step="stubbed revised step"` always) — a test
   that needs a *specific* simulated response (a refusal, a no-op revision,
   a partial match) needs its own fake `.llm` via `Fallback.__new__(Fallback)`
   / `Verifier.__new__(Verifier)` rather than going through the real
   constructor, which several tests in this pass do; follow that pattern.
   `pytest -m browser` needs Chromium; `pytest -m llm` costs money.

4. **`backend/tests/fixtures/job_application.html`** is the offline test surface: two selects, a radio group, checkboxes, a file input, a readonly field, a late-appearing control, an `aria-labelledby` field, a shadow-root section, and two buttons that deliberately share the name "Save".
   Extend this rather than testing against live sites.

5. **The snapshot never carries field values, only their presence.**
   The aria YAML does contain live values in plain text; the parser records `filled` and drops the text.
   A browser test pins this.
   Do not "improve" the snapshot by including values: it would put typed passwords back into the LLM context.

6. **The JS metadata pass never adds elements**, it only enriches rows the aria snapshot already produced.
   A JS-computed accessible name is not guaranteed to resolve through `get_by_role`, and advertising unaddressable targets is the failure mode Phase 3 exists to end.
   Controls only the JS pass can see surface through `read_form`, which shares the collector.

7. **`status_tracker._feed_field_progress` only trusts `fill` / `select_option` / `set_checkbox` / `upload_file` / `read_form`, not the legacy untargeted `type`.**
   This is deliberate: Phase 2's own docs say `type` "types into the focused element only... no longer returns invented target_* metadata," i.e. it has no reliable readback, unlike the addressable primitives. If you extend field-progress crediting, preserve this distinction rather than trusting `type` — that was the exact gap the deleted `test_verifier_does_not_complete_recipient_step_from_generic_field_progress_only` was worried about (see the test-suite section above), and it is meaningfully mitigated (not fully eliminated for hand-constructed state fixtures) by this restriction alone.

## Known-broken things I have not fixed, deferred deliberately

- Downloads (`expect_download`) and the file-chooser event are unhandled.
- `app.py` dialog handling auto-accepts every dialog, which auto-confirms `confirm("Submit your application?")` and defeats the sensitive-action gate.
- `handle_search` still has hardcoded Google/DuckDuckGo/Bing selectors.
- `handle_navigate` reports HTTP 4xx/5xx as success (`page.goto` does not raise).
- Date pickers and type-then-select autocomplete have no primitive.
- No endpoint or UI yet consumes the `run_id` the server now sends on `run_started`; a "resume this run" flow needs both a server endpoint and frontend work.

## Needs my decision, do not act on these

- The DB password and private VPC address `172.31.46.153` are still in git history.
  Untracking did not remove them.
  Rotation is the real fix; whether to rewrite history is my call.
- GitHub reports 122 Dependabot vulnerabilities on the default branch (1 critical, 59 high).
  Do not mass-bump dependencies; `requirements.txt` was rebuilt from the real import graph in Phase 0 and I want to review any change to it, including the sqlite checkpointer addition above.
- Anti-bot: detection, session persistence and user takeover are in scope. CAPTCHA solving is not.
  Many ATS platforms prohibit automated submission.

## Working agreement

- Never use the em dash. Use a plain dash instead.
- Do not add yourself as a commit co-author.
- When you finish work on an issue, close it.
- Put each full sentence on its own line in long Markdown files.
- Reproduce a bug end to end before fixing it. Never guess at a cause without evidence.
- Do not commit or push until I ask.
