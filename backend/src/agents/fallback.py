"""
Fallback Agent
Uses an LLM to diagnose failures and propose a revised step or recovery.
"""

from langchain_core.messages import SystemMessage, HumanMessage

from state import ProjectState
from schema import FallbackStrategy
from models import Models
from prompt_loader import get_fallback_prompt


class Fallback:
    """
    LLM-based fallback: given the failed step and execution/verification logs,
    the model decides how to recover (revise step, insert step, request context, or abort).
    """

    def __init__(self):
        self.llm = Models.fallback(FallbackStrategy)
        self.prompt = get_fallback_prompt()

    def __call__(self, state: ProjectState) -> dict:
        current_task = state.get("current_task", "Unknown task")
        reasoning_log = state.get("reasoning_log", [])
        user_intent = self._get_user_intent(state)
        current_url = state.get("current_url", "")

        last_verification = self._find_latest_log(reasoning_log, "[Verifier]") or "Verification failed."
        last_execution = (
            self._find_latest_log(reasoning_log, "[Executor]")
            or self._find_latest_log(reasoning_log, "[Verifier]")
            or "No execution log."
        )

        context = f"""
MAIN_GOAL: {user_intent}

PLAN_STEP (failed): {current_task}

VERIFICATION_OUTPUT:
{last_verification[:500]}

EXECUTION_OUTPUT:
{last_execution[:500]}

CURRENT_URL: {current_url}

Diagnose the failure and propose a recovery. Use update_type: revise_step with proposed_step for a single revised instruction; use insert_step_before with insert_step to add a prerequisite; use request_context if user input is needed; use abort only if the goal cannot be continued.
"""

        messages = [
            SystemMessage(content=self.prompt),
            HumanMessage(content=context.strip()),
        ]

        err = None
        try:
            strategy: FallbackStrategy = self.llm.invoke(messages)
        except Exception as e:
            err = e
            strategy = None

        if strategy is None:
            revised_task = current_task
            fallback_log = (
                "[Fallback] LLM failed; retrying same step.\n"
                f"[Fallback] Error: {err}\n"
                f"[Fallback] Message to Orchestration: Retry the current step."
            )
            needs_human = False
        else:
            revised_task = (
                (strategy.proposed_step or "").strip()
                or (strategy.insert_step or "").strip()
                or current_task
            )
            needs_human = strategy.update_type == "request_human_action"
            fallback_log = (
                f"[Fallback] Update Type: {strategy.update_type}\n"
                f"[Fallback] Diagnosis: {strategy.diagnosis}\n"
                f"[Fallback] Message to Orchestration: {strategy.message_to_orchestration}\n"
                f"[Fallback] Proposed Step: {revised_task}\n"
                f"[Fallback] Last Verification: {last_verification[:180]}"
            )

        out = {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "current_task": revised_task,
            "reasoning_log": [fallback_log],
            "needs_fallback": False,
        }
        if needs_human:
            out["handoff_interaction"] = True
            # Reset step_attempts so that human-in-the-loop pauses do not trigger
            # the orchestrator safety stop immediately after the user completes
            # the required action.
            out["step_attempts"] = 0
        return out

    def _find_latest_log(self, reasoning_log: list, prefix: str) -> str:
        for entry in reversed(reasoning_log or []):
            if isinstance(entry, str) and prefix in entry:
                return entry
        return ""

    def _get_user_intent(self, state: ProjectState) -> str:
        user_message = state["messages"][0] if state["messages"] else None
        if isinstance(user_message, dict):
            return user_message.get("content", "Unknown intent")
        if hasattr(user_message, "content"):
            return user_message.content
        return str(user_message) if user_message else "Unknown intent"
