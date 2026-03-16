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

    def __init__(self):
        self.llm = Models.verifier(VerificationResult)
        self.prompt = get_verification_prompt()

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

        context = f"""
MAIN_GOAL: {user_intent}

PLAN_STEP (current): {current_task}

EXECUTION_OUTPUT (action, args, status, message) and AFTER_STATE (page content after the action) from the Execution Agent:
{last_execution}

CURRENT_URL (after action): {current_url}

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
            next_step_attempts = 0 if step_complete else int(state.get("step_attempts", 0)) + 1
            verification_log = (
                f"[Verifier] Verdict: {result.verdict}\n"
                f"[Verifier] Step Complete: {step_complete}\n"
                f"[Verifier] Goal Complete: {goal_complete}\n"
                f"[Verifier] Message: {result.message}\n"
                f"[Verifier] Handoff: {result.handoff}"
            )

        return {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "needs_fallback": needs_fallback,
            "is_complete": goal_complete,
            "last_step_complete": step_complete,
            "step_attempts": next_step_attempts,
            "reasoning_log": [verification_log],
        }

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
