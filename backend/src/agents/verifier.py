"""
Verification Agent
Evaluates whether execution actions satisfied the current plan step.
"""

import re

from state import ProjectState


class Verifier:
    """
    Deterministic verifier that reads executor logs and routes control.

    This removes unstable simulated verification behavior and directly
    uses the execution result emitted by Executor.
    """

    _attempt_count = 0

    def __init__(self):
        # Kept for compatibility with existing initialization patterns.
        pass

    def __call__(self, state: ProjectState) -> dict:
        Verifier._attempt_count += 1

        current_step = state.get("current_step_index", 0)
        current_plan = state.get("current_plan", [])
        current_task = state.get("current_task", "")
        step_count = len(current_plan)
        is_last_step = step_count > 0 and current_step >= step_count - 1

        reasoning_log = state.get("reasoning_log", [])
        last_execution = reasoning_log[-1] if reasoning_log else "No execution log"

        executor_action = self._extract_executor_action(last_execution)
        executor_status = self._extract_executor_status(last_execution)
        executor_message = self._extract_executor_message(last_execution)
        action_aligned = self._is_action_aligned_with_task(current_task, executor_action)

        step_complete = executor_status == "success" and action_aligned
        goal_complete = step_complete and is_last_step
        needs_fallback = not step_complete

        if step_complete:
            verdict = "success"
            handoff = "orchestration"
            error_type = "none"
            message = executor_message or "Execution step completed successfully."
            next_step_attempts = 0
        else:
            verdict = "failure"
            handoff = "fallback"
            error_type = "execution_failure"
            if executor_status == "success" and not action_aligned:
                message = (
                    f"Action '{executor_action}' succeeded but did not satisfy current task: {current_task}"
                )
            else:
                message = executor_message or "Execution step failed."
            next_step_attempts = int(state.get("step_attempts", 0)) + 1

        verification_log = (
            f"[Verifier] Verdict: {verdict}\n"
            f"[Verifier] Action Aligned: {action_aligned}\n"
            f"[Verifier] Step Complete: {step_complete}\n"
            f"[Verifier] Goal Complete: {goal_complete}\n"
            f"[Verifier] Message: {message}\n"
            f"[Verifier] Handoff: {handoff}"
        )

        if error_type != "none":
            verification_log += f"\n[Verifier] Error Type: {error_type}"

        return {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "needs_fallback": needs_fallback,
            "is_complete": goal_complete,
            "last_step_complete": step_complete,
            "step_attempts": next_step_attempts,
            "reasoning_log": [verification_log],
        }

    def _extract_executor_action(self, execution_log: str) -> str:
        match = re.search(r"\[Executor\] Action:\s*([a-z_]+)", execution_log, flags=re.IGNORECASE)
        if not match:
            return "unknown"
        return match.group(1).lower()

    def _extract_executor_status(self, execution_log: str) -> str:
        match = re.search(r"\[Executor\] Status:\s*(success|failure)", execution_log, flags=re.IGNORECASE)
        if not match:
            return "failure"
        return match.group(1).lower()

    def _extract_executor_message(self, execution_log: str) -> str:
        match = re.search(r"\[Executor\] Message:\s*(.+)", execution_log)
        if not match:
            return ""
        return match.group(1).strip()

    def _is_action_aligned_with_task(self, task: str, action: str) -> bool:
        t = (task or "").lower()
        a = (action or "").lower()

        search_markers = [
            "search",
            "look up",
            "lookup",
            "find information",
            "locate information",
            "find info",
            "query",
        ]
        navigate_markers = [
            "navigate",
            "go to ",
            "open ",
            "visit ",
        ]

        if any(marker in t for marker in search_markers):
            return a == "search"
        if any(marker in t for marker in navigate_markers):
            return a == "navigate"
        return True

    @classmethod
    def reset_simulation(cls):
        """Compatibility reset hook."""
        cls._attempt_count = 0
