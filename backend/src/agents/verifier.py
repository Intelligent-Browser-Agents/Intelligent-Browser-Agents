"""
Verification Agent
Uses an LLM to decide whether the execution satisfied the current plan step.
"""

from langchain_core.messages import SystemMessage, HumanMessage

from state import ProjectState
from schema import VerificationResult
from models import Models
from prompt_loader import get_verification_prompt


class Verifier:
    """
    LLM-based verifier: given the plan step and execution outcome,
    the model decides if the step is complete and whether to hand off to
    orchestration or fallback.
    """

    _STALL_CAP = 6

    def __init__(self):
        self.llm = Models.verifier(VerificationResult)
        self.prompt = get_verification_prompt()

    def _apply_stall_cap(
        self,
        state: ProjectState,
        current_step: int,
        partial: dict,
    ) -> dict:
        """
        General stall detection: count consecutive incomplete verification
        cycles on the same plan step and force fallback when the cap is hit.
        Applies to any step type — no keyword classification needed.
        """
        out = dict(partial)
        if out.get("needs_fallback") or bool(out.get("last_step_complete")):
            out["stall_cycles"] = 0
            out["stall_tracked_step"] = current_step
            return out
        tr_raw = state.get("stall_tracked_step")
        tr_i = int(tr_raw) if tr_raw is not None else -1
        prev = int(state.get("stall_cycles") or 0)
        if tr_i != current_step:
            prev = 0
        nxt = prev + 1
        if nxt >= self._STALL_CAP:
            out["needs_fallback"] = True
            out["last_step_complete"] = False
            nxt = 0
            prefix = (
                "[Verifier] Step exceeded retry budget without completion; "
                "forcing fallback for recovery.\n"
            )
            logs = list(out.get("reasoning_log") or [])
            if logs and isinstance(logs[0], str):
                logs[0] = prefix + logs[0]
            else:
                logs = [prefix + "[Verifier] Handoff: fallback"]
            out["reasoning_log"] = logs
        out["stall_cycles"] = nxt
        out["stall_tracked_step"] = current_step
        return out

    def __call__(self, state: ProjectState) -> dict:
        current_step = state.get("current_step_index", 0)
        current_plan = state.get("current_plan", [])
        current_task = state.get("current_task", "")
        current_url = state.get("current_url", "")
        step_count = len(current_plan)
        is_last_step = step_count > 0 and current_step >= step_count - 1

        reasoning_log = state.get("reasoning_log", [])
        last_execution = reasoning_log[-1] if reasoning_log else "No execution log."
        user_intent = self._get_user_intent(state)

        # Deterministic guardrail: do not allow failed executor actions to be
        # marked as successful just because page content looks plausible.
        last_exec_lower = (last_execution or "").lower()
        if "[executor] status: failure" in last_exec_lower:
            verification_log = (
                "[Verifier] Verdict: failure\n"
                "[Verifier] Step Complete: False\n"
                "[Verifier] Goal Complete: False\n"
                "[Verifier] Message: Executor reported a failed action; retry/fallback required.\n"
                "[Verifier] Handoff: fallback"
            )
            return self._apply_stall_cap(
                state,
                current_step,
                {
                    "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                    "needs_fallback": True,
                    "is_complete": False,
                    "last_step_complete": False,
                    "step_attempts": int(state.get("step_attempts", 0)) + 1,
                    "reasoning_log": [verification_log],
                },
            )

        # Provide recent executor history so the LLM verifier can detect
        # patterns (repeated actions, discovery loops, login progress, etc.).
        recent_executor_logs = [
            entry for entry in (reasoning_log or [])
            if isinstance(entry, str) and entry.startswith("[Executor]")
        ]
        recent_executor_history = "\n\n".join(recent_executor_logs[-4:]) if recent_executor_logs else ""

        mission_status = state.get("mission_status") or ""

        # Build an HITL-resolved note so the LLM knows old MFA/login
        # mentions in the history are stale and shouldn't influence the
        # current verdict.
        hitl_note = ""
        signals = state.get("status_signals") or {}
        hitl_events = signals.get("hitl_events") or []
        if hitl_events:
            last_hitl = hitl_events[-1]
            last_hitl_tx = last_hitl.get("transaction", -1)
            current_tx = state.get("number_of_transactions", 0)
            if current_tx - last_hitl_tx <= 4:
                hitl_note = (
                    "\nIMPORTANT: The user recently completed a human-in-the-loop action "
                    "(e.g. MFA/2FA approval). Any previous mentions of 'two-step verification', "
                    "'MFA', or 'login blocked' in the history are RESOLVED. "
                    "Evaluate the CURRENT EXECUTION_OUTPUT and AFTER_STATE on their own merits. "
                    "Do NOT flag MFA/2FA issues based on old history.\n"
                )

        context = f"""
MAIN_GOAL: {user_intent}

PLAN_STEP (current): {current_task}
{hitl_note}
EXECUTION_OUTPUT (action, args, status, message) and AFTER_STATE (page content after the action) from the Execution Agent:
{last_execution}

RECENT_EXECUTION_HISTORY (last few executor logs):
{recent_executor_history}

CURRENT_URL (after action): {current_url}

MISSION_STATUS:
{mission_status}

Use the EXECUTION_OUTPUT and especially AFTER_STATE (page content) as evidence. If the page content or action result shows the step was satisfied (e.g. the right page loaded, the target was clicked, or the required information is visible), set verdict=success and step_complete=true. Do not mark failure with "insufficient_evidence" if AFTER_STATE is present and supports success.
For a "search" action: if EXECUTION_OUTPUT shows status=success, the search was submitted. Treat as step_complete=true if you see search results, result links, or a results page in AFTER_STATE; if the page still shows the same search box but the action succeeded, still accept success (the step was to run the search).
If this is the last step of the plan and the step is complete, set goal_complete=true.
"""

        messages = [
            SystemMessage(content=self.prompt),
            HumanMessage(content=context.strip()),
        ]

        err = None
        try:
            result: VerificationResult = self.llm.invoke(messages)
        except Exception as e:
            err = e
            result = None

        if result is None:
            step_complete = "success" in (last_execution or "").lower() and "status: success" in (last_execution or "").lower()
            goal_complete = step_complete and is_last_step
            needs_fallback = not step_complete
            next_step_attempts = 0 if step_complete else int(state.get("step_attempts", 0)) + 1
            verification_log = f"[Verifier] LLM failed: {err}; step_complete={step_complete}\n[Verifier] Handoff: {'fallback' if needs_fallback else 'orchestration'}"
        else:
            step_complete = result.step_complete
            goal_complete = result.goal_complete
            needs_fallback = result.handoff == "fallback"
            # Only count "attempts" for automated retries. If we're handing off to fallback
            # due to a hard block (CAPTCHA/2FA/human action), do not burn the safety budget.
            error_type = (result.error_type or "").strip().lower()
            verdict_is_success = (result.verdict or "").strip().lower() == "success"
            if step_complete:
                next_step_attempts = 0
            elif needs_fallback and error_type in {"blocked", "tool_limit"}:
                next_step_attempts = 0
            elif verdict_is_success:
                # verdict=success with step_complete=False means progress
                # (e.g. typing credentials during multi-step login). Don't
                # burn the safety budget on forward progress.
                next_step_attempts = int(state.get("step_attempts", 0))
            else:
                next_step_attempts = int(state.get("step_attempts", 0)) + 1
            verification_log = (
                f"[Verifier] Verdict: {result.verdict}\n"
                f"[Verifier] Step Complete: {step_complete}\n"
                f"[Verifier] Goal Complete: {goal_complete}\n"
                f"[Verifier] Message: {result.message}\n"
                f"[Verifier] Handoff: {result.handoff}"
            )

        return self._apply_stall_cap(
            state,
            current_step,
            {
                "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                "needs_fallback": needs_fallback,
                "is_complete": goal_complete,
                "last_step_complete": step_complete,
                "step_attempts": next_step_attempts,
                "reasoning_log": [verification_log],
            },
        )

    def _get_user_intent(self, state: ProjectState) -> str:
        user_message = state["messages"][0] if state["messages"] else None
        if isinstance(user_message, dict):
            return user_message.get("content", "Unknown intent")
        if hasattr(user_message, "content"):
            return user_message.content
        return str(user_message) if user_message else "Unknown intent"

    @classmethod
    def reset_simulation(cls):
        pass
