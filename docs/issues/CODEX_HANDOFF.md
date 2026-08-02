# Continuing: Intelligent-Browser-Agents, finish Phase 4

## Context

UCF senior-design LangGraph + Playwright browser agent.
The goal is not the demo scope: it is to autonomously complete long, stateful web tasks on my behalf, primarily **applying to jobs unattended**, plus booking travel and acting as me on sites where I have saved credentials.

Read `docs/IMPROVEMENT_PLAN.md` first.
It is the audited source of truth: verified defects with file:line evidence, measured before/after tables per phase, and an explicit out-of-scope list.
Do not re-derive its findings.

Then read `docs/issues/phase-4-control-loop.md`, which is the open issue for the work you are picking up.

Branch: `Edwin-after-grad`, at commit `f42e996`. Work continues on this branch.
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

**The offline suite is not green.** This is expected and is your first task.

    pytest -q                       # 173 passed, 18 failed, 5 xfailed
    pytest -m browser -q            # expect green (needs Chromium + network)
    cd frontend && npx eslint .     # expect 0 errors, 1 warning

Phases 0, 1, 2 and 3 are complete. Do not redo them.
Phase 4 is roughly half landed, and **the 18 failures are its old tests, not regressions.**

### What Phase 4 has already landed

- `backend/src/autonomy.py` (new): the autonomy policy replacing the sensitive-token gate.
  Three levels (observe_only, confirm_irreversible, autonomous), a hard always-confirm list that no level bypasses, and per-domain overrides.
  The module is written and tested; the executor is **not** wired to it yet.
- `backend/src/agents/verifier.py`: the compose/mailbox/finalization keyword branches are deleted (plan item 6). This is the bulk of the 902-line reduction.
- `backend/src/agents/fallback.py`: rewritten.
- `backend/src/status_tracker.py`: one `field_progress` tracker fed by `read_form`, replacing the two competing trackers (plan item 15).
  `compose_fields` and `_classify_compose_slot_from_type_event` are gone.

### Your first task: triage the 18 failures

    backend/tests/test_control_flow.py   14 failures
    backend/tests/test_fallback.py        4 failures

Twelve of the fourteen `test_control_flow.py` failures pin verifier compose/mailbox keyword gating that Phase 4 deliberately deleted.
Two (`test_orchestrator_transaction_abort_*`) pin the "success credits" budget arithmetic that plan item 7 says to drop.
The four `test_fallback.py` failures pin the pre-rewrite fallback behaviour.

For each: either rewrite it against the structural checks that replaced the keyword branch, or delete it because the behaviour it pinned is gone on purpose.
Do not delete a test merely to get green.
Precedent from this commit: `test_compose_slot_classification.py` was deleted because all four of its tests covered one deleted private function, and nothing else.

**Every deletion needs a one-line justification in the commit message.**

### Then: the deferred Phase 3-to-4 wires

`docs/issues/phase-4-control-loop.md` lists five wires that were deliberately left undone so that Phase 3 and Phase 4 could be built concurrently without touching the same files.
Phase 3 has landed, so those files are free now:

1. `executor.py`: write the post-action snapshot into `state["last_page_snapshot"]`. The verifier and orchestrator already prefer it when present.
2. `executor.py`: include the Phase 2 `verified` flag in `last_execution_event`. The verifier already consumes `event["verified"]` when present.
3. `executor.py`: replace `_sensitive_action_reason`'s token lists with `autonomy.assess_action(...)`. The module is ready and tested.
4. `schema.py`: optional `replan` on `FallbackStrategy.update_type`, optional `work_items` on `OrchestratorPlan`.
5. `requirements.txt`: add `langgraph-checkpoint-sqlite`. `app.py` falls back to `MemorySaver` with a logged notice until it is installed.

### Then: the remaining Phase 4 items

Items 1 through 15 in `docs/IMPROVEMENT_PLAN.md` under "Phase 4".
The highest-value ones still open are 1 (delete `_get_simulated_page_context`, pass the real Phase 3 snapshot to the planner), 3 (make the plan mutable; `insert_step_before` is promised by the schema and the prompt and is not implemented), 4 (the work-queue construct, which is what makes "apply to 20 jobs" representable at all), and 10 and 11 (per-run identity, durable checkpointing, and `storage_state` persistence per user and domain).

## Three confirmed defects in the Phase 3 code, found by review after it was written

These are real, reproduced on the pinned Playwright 1.58, and not yet fixed.
Fix them before building on the snapshot.

**1. Single-quoted aria keys are silently dropped (high).**
`backend/src/dom_extraction/snapshot.py:96`, the `_ARIA_ROW` regex.
Playwright's `yamlEscapeKeyIfNeeded` wraps the whole `role "name" [attrs]` key in single quotes when the accessible name contains `': '`, `' #'`, `{`, `}`, or a backtick.
Verified live: `<button>Step 2: Continue</button>` emits `- 'button "Step 2: Continue"'`, and an input labeled `Apt #` emits `- 'textbox "Apt #"'`.
`_ARIA_ROW` requires `[a-zA-Z]` immediately after `- `, so those rows fail to match and are skipped with no marker.
The element then vanishes from the snapshot, from `element_inventory`, and from `suggest_candidates`.
Names like "Apt #", "Phone #" and "Step 2 of 5" are routine on job applications, so real fields become invisible.
Fix: unwrap the single-quoted key (undoing YAML `''` doubling) before matching. Add tests for `': '`, `' #'`, `{`, `}`, and backtick names.

**2. `read_page` re-sections at a different budget than the snapshot that advertised it (medium).**
`backend/src/execution/actions.py:675`.
`PageSnapshot._sections` packs rows into chunks of `max(400, max_chars - 220)`, so section boundaries depend on `max_chars`.
The executor renders at 3500/5000/5200 and the after-state at 2200, but `do_read_page` always uses 4000.
Under the default 3500 budget, section 1 ends at 3280 characters of rows and tells the model to call `read_page(section=2)`, which starts at 3780.
Rows between 3280 and 3780 are shown by neither call, and the model is told coverage is complete.
Reproduced offline with 120 form rows: elements 38 to 43 are unreachable through any sequence of advertised calls.
This is the exact silent-loss failure the module was written to end.
Fix: one shared budget constant across `_get_real_dom_snapshot`, the after-state render, and `do_read_page`, or thread the budget through so section numbers always refer to one canonical sectioning.

**3. Options nested under a `group` row inside a listbox are lost (medium).**
`backend/src/dom_extraction/snapshot.py:509`, `_flatten_aria_nodes`.
It only scans direct children for `role="option"` and never recurses into combobox/listbox subtrees, so a grouped ARIA listbox renders with no options while the option elements are also dropped.

A fourth review lens (tests, contracts, and a secrets re-verification) did not finish because the session hit its usage limit.
Re-running a review over `backend/src/dom_extraction/snapshot.py` and `backend/src/execution/actions.py` is worth the tokens before you build on them.

## Things to know before you touch anything

1. **`TEMPERATURES` in `backend/src/models.py` is inert.**
   gpt-5.x accepts only `temperature=1.0`; langchain-openai silently drops anything else (verified: passing 0.0 stores None).
   Sampling cannot be turned down.
   Determinism must come from structural checks on observable state, for example `Verifier._credentials_still_requested`.
   A test pins this.
   Plan item 8 ("set temperature 0 for the verifier, decision maker and fallback agent") is **not achievable as written** for this reason. Implement it as structural determinism instead, and correct the plan text.

2. **The `xfail(strict=True)` tests are deliberate.**
   Each names the phase that fixes it.
   They assert intended behaviour the code does not have yet.
   Do not delete markers to get green: fix the defect and strict mode will tell you to remove the marker.

3. **The default suite is offline and free.**
   `backend/tests/conftest.py` swaps in deterministic LLM stubs unless a test is marked `llm`.
   Keep new tests offline.
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

## Known-broken things I have not fixed, deferred deliberately

- Downloads (`expect_download`) and the file-chooser event are unhandled.
- `app.py:159` auto-accepts every dialog, which auto-confirms `confirm("Submit your application?")` and defeats the sensitive-action gate.
- `handle_search` still has hardcoded Google/DuckDuckGo/Bing selectors.
- `handle_navigate` reports HTTP 4xx/5xx as success (`page.goto` does not raise).
- Date pickers and type-then-select autocomplete have no primitive.

## Needs my decision, do not act on these

- The DB password and private VPC address `172.31.46.153` are still in git history.
  Untracking did not remove them.
  Rotation is the real fix; whether to rewrite history is my call.
- GitHub reports 122 Dependabot vulnerabilities on the default branch (1 critical, 59 high).
  Do not mass-bump dependencies; `requirements.txt` was rebuilt from the real import graph in Phase 0 and I want to review any change to it.
- Anti-bot: detection, session persistence and user takeover are in scope. CAPTCHA solving is not.
  Many ATS platforms prohibit automated submission.

## Working agreement

- Never use the em dash. Use a plain dash instead.
- Do not add yourself as a commit co-author.
- When you finish work on an issue, close it.
- Put each full sentence on its own line in long Markdown files.
- Reproduce a bug end to end before fixing it. Never guess at a cause without evidence.
- Do not commit or push until I ask.
