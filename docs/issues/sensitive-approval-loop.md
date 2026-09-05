# Issue: An approved sensitive action is never executed; the user is asked again

Status: **closed** (implemented 2026-09-05)
Branch: `Edwin-after-grad`
Opened: 2026-09-05

Closed with: all six items under "What" below.
Verification: offline suite 356 passed / 3 xfailed (7 new tests in `backend/tests/test_sensitive_approval.py`; the exact-signature test that pinned the old behaviour is retired), eslint and `npm run build` clean.
The Yes/No approval prompt was checked visually against the real stylesheets through a throwaway harness page: Yes submits "yes" and disables both buttons; the ordinary clarification form is unchanged.
The state-contract floor for `interaction.py` moves from 8 to 7 because the unclear-reply branch no longer returns a state update of its own.
Not exercised live: a real gated click on a job site. The handshake is pinned at the unit level end to end (approval record, routing, model-free dispatch), and the reproduction of the original loop is the live run log plus the signature check in the diagnosis above.

## Why

Live run 5d1a58ca ("please look for a software engineer position on apple.com and begin applying"), 2026-09-05.
The executor's click on Apple's "Submit Resume" link was gated as a `submission` under the default `confirm_irreversible` autonomy level.
The user approved it three times (transactions 12, 18, and 21) and the click still never ran; the run was left waiting on a fourth confirmation.

What the code did after each yes, traced against the source and reproduced offline:

1. **Nothing replays the approved action.**
   The interaction node stored the approval as an exact signature of the proposed arguments and handed control to the orchestrator.
   The orchestrator's decision model rewrote the task ("now that confirmation was provided", "after receiving an explicit yes confirmation"), and a fresh executor call had to re-choose an action from scratch.
2. **The executor prompt argued against the replay.**
   The blocked click sat in `PREVIOUS_ACTIONS` under "already executed, do NOT repeat", and `ADAPTIVE_GUIDANCE` warned about repeating the same action type.
   The model obliged: it ran `wait_for(heading ...)` instead, and later took "after receiving an explicit yes confirmation" literally and ran `wait_for(text_contains="yes")` against the page.
3. **Exact-signature matching, with one slot.**
   Apple's job page has two identical "Submit Resume" links, so the snapshot labels them `nth=0` and `nth=1`.
   The model picked 0, then 1, then 0; each is a different signature, and each approval overwrote the previous one, so nothing ever matched (`executor._action_signature` includes `nth`; reproduced with the executor's own functions).
4. **An unclear reply left the checkpoint.**
   "yesd" parsed as unclear and the node returned to the orchestrator instead of asking again, which cost another executor round before the question came back.

The gate itself is policy (`autonomy.py` classes any click named "Submit ..." as `submission`) and is left as is; `autonomous` mode skips it.
The bug is everything after the yes.

## What

1. **Approval is a one-shot ticket with the action inside it.**
   The interaction node records the exact `action` and `args` that were proposed alongside the signature.
   `autonomy.approved_action(state)` is the single predicate for "there is an approved action to run".
2. **The graph routes straight back to the executor.**
   `main.route_after_interaction`: END when complete, `execution` when an approval is pending, `orchestrator` otherwise.
   No decision-model turn sits between the yes and the click.
3. **The executor dispatches the approved action without a model call.**
   `Executor._execute_approved_action` rebuilds the action from the recorded arguments, re-runs the required-fields guard, dispatches through the same dispatcher as the structured path, appends "(executed after explicit user approval)" to the log, and clears the approval whatever the outcome.
   The exact-signature re-check in the model path is gone: by construction the model path never sees an approval.
4. **Unclear replies are re-asked in place.**
   The interaction node loops on the checkpoint until it gets a yes or a no, with a message that names the action.
5. **The frontend offers Yes/No buttons for approval prompts**, so typing is not needed and "yesd" cannot happen.
6. Tests: routing, the predicate, the approval record, the in-place re-ask, and the executor's model-free dispatch, plus retiring the exact-signature test that pinned the old behaviour.

## Non-goals

- Changing which actions are gated. Whether an "apply" entry link should count as a submission is a policy question; see the note above.
- Remembering approvals across attempts. If the approved click fails (the page changed), the next attempt asks again; that is the safe default.
- The executor's missing "step already satisfied" outcome, which is what made it click "Submit Resume" one step early in the same run.

## Acceptance

- After a yes, the very next graph node is the executor, and it dispatches the recorded action with the recorded arguments (`nth` included) without calling the model.
- A duplicate-target page cannot produce a second confirmation for the same approval.
- "yesd" produces a second question inside the same checkpoint, not a new executor turn.
- Offline suite green; frontend lint and build clean.
