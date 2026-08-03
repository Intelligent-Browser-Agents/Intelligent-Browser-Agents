# Issue: Phase 4 - fix the agentic control loop

Status: **mostly complete** - two items handed off, see `docs/issues/CODEX_HANDOFF.md`
Branch: `Edwin-after-grad`
Plan reference: `docs/IMPROVEMENT_PLAN.md`, section "Phase 4: fix the agentic control loop"
Opened: 2026-08-02

## Why

The control loop is the layer that decides what happens between browser actions: planning, verification, recovery, budgets, and HITL.
Today it fabricates page observations for the planner, gates verification on email-compose keywords, cannot mutate its own plan, and has safety brakes that arithmetic makes unreachable.
Phase 4 replaces those mechanisms with structural ones so the agent stops being brittle on anything that is not an email task.

## Scope

The 15 numbered items from the plan document. In this codebase they land in:

- `backend/src/state.py` - new control-plane fields (`mission_goal`, `last_page_snapshot`, work queue, retry brake).
- `backend/src/agents/orchestrator.py` - real page context for planning, replan path, deterministic work-item loop, budget arithmetic.
- `backend/src/agents/verifier.py` - structural completion checks, explicit plan position, keyword-branch removal.
- `backend/src/agents/fallback.py` - plan mutation that actually writes `current_plan`.
- `backend/src/agents/interaction.py` - interrupt re-entry fix, correlation ids, state-contract cleanup.
- `backend/src/status_tracker.py` - one progress tracker fed by `read_form`, evidence-based `login_phase`.
- `backend/src/app.py`, `backend/server.py` - per-run identity, durable checkpointing, recursion budget, HITL lifecycle, browser session persistence.
- `backend/src/autonomy.py` (new) - autonomy policy replacing the sensitive-token lists.
- Tests under `backend/tests/`.

## Constraint: concurrent Phase 3 build

Phase 3 ("one honest page representation") is being built concurrently in this working tree.
Its footprint (per `git status` at the time this issue was opened): `backend/src/agents/executor.py`, `backend/src/capabilities.py`, `backend/src/dom_extraction/*`, `backend/src/execution/*`, `backend/src/schema.py`, `backend/tools/inspect_page.py`, `requirements.txt`, and several test files.
**Phase 4 does not modify any of those files.** The few Phase 4 wires that terminate inside them are implemented tolerantly on the Phase 4 side (consumers accept the signal when present) and the producer edits are deferred:

1. `executor.py`: write the post-action snapshot into `state["last_page_snapshot"]` (verifier and orchestrator already prefer it when present).
2. `executor.py`: include the Phase 2 `verified` flag in `last_execution_event` (verifier already consumes `event["verified"]` when present).
3. `executor.py`: replace `_sensitive_action_reason` token lists with `autonomy.assess_action(...)` (module ready and tested).
4. `schema.py`: optional `replan` value on `FallbackStrategy.update_type` and optional `work_items` on `OrchestratorPlan` (both have deterministic non-schema triggers in the meantime).
5. `requirements.txt`: add `langgraph-checkpoint-sqlite` (app.py falls back to `MemorySaver` with a logged notice until it is installed).

## Acceptance (from the plan)

- A scripted multi-page fixture task runs to completion without hitting the recursion limit.
- An intentionally impossible task aborts gracefully with a user-facing explanation.
- A run interrupted mid-way resumes from its checkpoint.

## Log

- 2026-08-02: opened; implementation started.
- 2026-08-02: all 15 Phase 4 items landed except work-item *population* (the
  deterministic advancement half is done) and the three deferred wires listed
  above, which were re-confirmed still open now that Phase 3 has landed.
  Offline suite green (194 passed, 4 xfailed). Remaining work handed off in
  `docs/issues/CODEX_HANDOFF.md`, which also carries three confirmed defects
  in Phase 3's snapshot code found by review and re-verified as still present.
