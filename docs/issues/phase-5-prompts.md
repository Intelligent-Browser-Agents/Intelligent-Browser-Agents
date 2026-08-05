# Issue: Phase 5 - prompts that tell the truth

Status: **closed** (implemented 2026-08-05)
Branch: `Edwin-after-grad`
Opened: 2026-08-05
Plan reference: `docs/IMPROVEMENT_PLAN.md`, Phase 5

Closed with: all seven prompts rewritten and adversarially verified against the code (21 wrong claims found and fixed, including two bugs introduced during the work and caught by the verification pass: a NameError in status_tracker's success path and a credential overwrite on non-credential fill targets); site-notes mechanism with Gmail/Outlook notes; prompt contract tests (test_prompt_contracts.py, test_site_notes.py); job-application skill module. Suite: 249 passed offline. Deviations recorded in the plan doc's Phase 5 notes.

## Why

Phases 2-4 rebuilt the action layer, the page representation, and the control loop, but the seven prompt files still describe the system that was deleted.
An audit of every prompt against its consuming code (orchestrator, executor, verifier, fallback, interaction) found 65 defects in five categories.

The load-bearing ones:

- **Prompts lie about their inputs.**
  Every prompt's Inputs section is wrong.
  `ALLOWED_TOOLS` is promised to the executor and never supplied on either path; `BEFORE_STATE` is promised to the verifier and never existed; the fallback's `AFTER_STATE (URL + DOM snapshot)` describes labels the code does not use.
  Meanwhile the real context blocks (`STRUCTURAL_SIGNALS`, `PLAN_POSITION`, `STEP_OBJECTIVE`, `LOOP_ANALYSIS`, `WORK_ITEM_RESULTS`, `MISSION_STATUS`, `EXECUTION_STATUS_SIGNALS`, and more) are undocumented, so the models receive evidence they were never told how to weigh.
- **The compose special-casing survives in the prompts.**
  Phase 4 deleted the email keyword gates from the code, but the prompts still teach them: 12 of the verifier's rules are compose semantics, the planner's only granularity example is an email recipe, the fallback's repair heuristics are recipient-lane repairs, and ~42% of `execution_tools.prompt.md` is compose flow plus a genericized university-SSO walkthrough.
- **The prompts steer the model away from the new capabilities.**
  The planner's output format suppresses `work_items` ("output exactly one of the following"), so the Phase 4 work queue can never be populated by the model.
  The executor's JSON-fallback prompt lists 8 of 20 actions and 6 of 12 error types.
  `read_page` pagination, `scroll_to`, and `list_tabs` are documented nowhere.
  The credentials guidance still prescribes legacy blind `type` in both executor prompts.
- **Structural drift the prompts can't fix alone.**
  The JSON-fallback path drops every Phase 2 arg before dispatch (executor.py `_validate_and_normalize_action` result repacking), so `select_option` and `upload_file` are unusable in that mode regardless of prompt text.
  Credential enforcement intercepts only the `type` tool, so a model following the fill-first guidance bypasses it.
  The upload argument is `file_path` in the registered tool but `document_id` in the schema.
  `switch_tab`/`close_tab` are implemented, dispatchable, and in the schema, but never registered as tools.

## What

1. Rewrite all seven prompts so every claimed input exists, every documented output field matches its Pydantic schema, and no site-specific rule remains in a generic prompt.
   Scope per file: ground-up rewrite for `execution_tools`, `execution`, and the verifier's Inputs/Rules; substantial rewrite for `orchestration`; targeted edits for `orchestration_reasoning`, `fallback`, `interaction`.
2. Add a per-domain site-notes mechanism: `backend/src/prompts/site_notes/<host>.md`, loaded only when the current host matches, injected as a `SITE_NOTES` block.
   The distilled mail-compose knowledge moves there, so a Gmail rule cannot affect a Workday run.
3. Code fixes required for the rewritten prompts to be honest:
   forward the full `ExecutionArgs` field set in the JSON-fallback path; extend credential enforcement to `fill`; alias `file_path` to `document_id`; register `switch_tab`/`close_tab`; widen the verifier's history window to match its own rule; delete the dead `target_name` plumbing and the dead `tool_limit` branch.
4. A contract test that fails when a prompt names an input or output field the schema/code does not have, pinning prompt-to-code parity from now on.
5. A job-application skill module at `.agents/skills/job-application/SKILL.md` holding the answer library, question-mapping heuristics, and tailoring rules.

## Non-goals

- No prompt-quality/eval-harness work (out of scope per the improvement plan; `orchestrator-benchmarking` exists for that).
- No frontend rendering of `requested_fields` (Phase 7 item 7).
- No retirement of the executor's newest-page auto-switch; registering the tab tools is enough for this phase.

## Acceptance

- Every context label a prompt documents is supplied by the consuming code, and every context label the code supplies is documented (verified by audit re-run).
- Every output field and enum value in a prompt matches its Pydantic model exactly, enforced by the new contract test.
- `rg -i 'recipient|compose|draft|subject line'` over `backend/src/prompts/*.prompt.md` returns no compose semantics outside `site_notes/`.
- Offline suite green, eslint clean, no billable API calls in the default test run.
