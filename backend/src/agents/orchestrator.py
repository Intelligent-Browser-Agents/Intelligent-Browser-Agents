"""
Orchestration Agent
Converts user requests into ordered high-level subtasks for browser automation.
"""

from langchain_core.messages import SystemMessage, HumanMessage

from schema import OrchestratorPlan
from state import ProjectState
from models import Models
from prompt_loader import get_orchestration_prompt


class Orchestrator:
    """
    LLM-powered planner plus deterministic step router.

    - Planning uses an LLM.
    - Step routing uses verifier outputs to avoid controller loops.
    """

    def __init__(self):
        self.planner = Models.planner(OrchestratorPlan)
        self.planning_prompt = get_orchestration_prompt()

    def __call__(self, state: ProjectState) -> dict:
        abort_reason = self._get_abort_reason(state)
        if abort_reason:
            return self._abort_mission(state, abort_reason)

        user_intent = self._get_user_intent(state)
        current_plan = state.get("current_plan", [])
        current_step = state.get("current_step_index", 0)

        needs_new_plan = len(current_plan) == 0
        simulated_page = self._get_simulated_page_context(
            state.get("current_url", ""),
            current_step,
            user_intent,
        )

        if needs_new_plan:
            return self._create_plan(user_intent, simulated_page, state)

        return self._make_decision(current_plan, current_step, state)

    def _create_plan(self, user_intent: str, page_state: str, state: ProjectState) -> dict:
        context = f"""
        USER REQUEST: {user_intent}

        CURRENT URL: {state.get('current_url', 'https://google.com')}

        PAGE STATE:
        {page_state}

        Based on this request, create a plan following the output format specified.
        """

        messages = [
            SystemMessage(content=self.planning_prompt),
            HumanMessage(content=context),
        ]

        plan: OrchestratorPlan = self.planner.invoke(messages)

        if plan.needs_clarification:
            reasoning = "[Planner] Needs clarification:\n"
            for question in plan.clarifying_questions:
                reasoning += f"  - {question}\n"

            return {
                "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                "current_plan": [],
                "plan_history": [],
                "current_step_index": 0,
                "plan_status": "NEEDS_CLARIFICATION",
                "current_task": "Awaiting user clarification",
                "reasoning_log": [reasoning],
                "is_complete": False,
                "handoff_interaction": True,
                "needs_fallback": False,
                "last_step_complete": False,
                "mission_failed": False,
                "step_attempts": 0,
            }

        reasoning = f"[Planner] Goal: {plan.goal}\n"
        reasoning += f"[Planner] Created plan with {len(plan.steps)} steps:\n"
        for index, step in enumerate(plan.steps):
            reasoning += f"  {index + 1}. {step}\n"

        first_task = plan.steps[0] if plan.steps else "No steps generated"
        return {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "current_plan": plan.steps,
            "plan_history": plan.steps,
            "current_step_index": 0,
            "plan_status": "MAINTAIN",
            "current_task": first_task,
            "reasoning_log": [reasoning],
            "is_complete": False,
            "needs_fallback": False,
            "last_step_complete": False,
            "mission_failed": False,
            "step_attempts": 0,
            "handoff_interaction": False,
        }

    def _make_decision(self, current_plan: list, current_step: int, state: ProjectState) -> dict:
        step_complete = state.get("last_step_complete", False)
        total_steps = len(current_plan)
        safe_step = min(max(current_step, 0), max(total_steps - 1, 0))

        if step_complete and safe_step >= total_steps - 1:
            reasoning = (
                f"[Decision] Status: MAINTAIN | Step: {safe_step + 1}/{total_steps} | Complete: True\n"
                "[Decision] Rule: Final step verified as complete."
            )
            return {
                "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                "current_step_index": safe_step,
                "plan_status": "MAINTAIN",
                "current_task": current_plan[safe_step],
                "reasoning_log": [reasoning],
                "is_complete": True,
                "needs_fallback": False,
                "mission_failed": False,
            }

        if step_complete:
            next_step = min(safe_step + 1, total_steps - 1)
            next_task = current_plan[next_step]
            reasoning = (
                f"[Decision] Status: MAINTAIN | Step: {next_step + 1}/{total_steps} | Complete: False\n"
                "[Decision] Rule: Previous step succeeded; advancing to next step."
            )
            return {
                "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                "current_step_index": next_step,
                "plan_status": "MAINTAIN",
                "current_task": next_task,
                "reasoning_log": [reasoning],
                "is_complete": False,
                "needs_fallback": False,
                "mission_failed": False,
            }

        current_task = state.get("current_task") or current_plan[safe_step]
        reasoning = (
            f"[Decision] Status: MAINTAIN | Step: {safe_step + 1}/{total_steps} | Complete: False\n"
            "[Decision] Rule: Current step not complete; retrying with updated task context."
        )
        return {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "current_step_index": safe_step,
            "plan_status": "MAINTAIN",
            "current_task": current_task,
            "reasoning_log": [reasoning],
            "is_complete": False,
            "needs_fallback": False,
            "mission_failed": False,
        }

    def _get_user_intent(self, state: ProjectState) -> str:
        user_message = state["messages"][0] if state["messages"] else None
        if isinstance(user_message, dict):
            return user_message.get("content", "Unknown intent")
        if hasattr(user_message, "content"):
            return user_message.content
        return str(user_message) if user_message else "Unknown intent"

    def _get_abort_reason(self, state: ProjectState) -> str:
        max_step_attempts = int(state.get("max_step_attempts", 6))
        max_transactions = int(state.get("max_transactions", 80))
        step_attempts = int(state.get("step_attempts", 0))
        transactions = int(state.get("number_of_transactions", 0))

        if step_attempts >= max_step_attempts:
            return (
                f"Aborted after {step_attempts} failed attempts on the current step "
                f"(limit: {max_step_attempts})."
            )
        if transactions >= max_transactions:
            return (
                f"Aborted after {transactions} transactions without completion "
                f"(limit: {max_transactions})."
            )
        return ""

    def _abort_mission(self, state: ProjectState, reason: str) -> dict:
        reasoning = (
            "[Decision] Status: MAINTAIN | Complete: False\n"
            f"[Decision] Safety Stop: {reason}"
        )
        return {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "is_complete": True,
            "needs_fallback": False,
            "mission_failed": True,
            "abort_reason": reason,
            "reasoning_log": [reasoning],
        }

    def _get_simulated_page_context(self, url: str, step: int, intent: str) -> str:
        if "ucf" in url.lower() or "login" in intent.lower():
            stages = [
                "UCF homepage loaded. Search and navigation elements are visible.",
                "User has interacted with the page and relevant controls are available.",
                "Progress has been made toward the requested task.",
                "Near completion with final interactions pending.",
                "Task completed successfully.",
            ]
        else:
            stages = [
                f"Page loaded at {url}. Navigation and content elements visible.",
                "Interacted with page. Elements responding to actions.",
                "Progress made. Page state updated.",
                "Near completion. Final actions pending.",
                "Task completed successfully.",
            ]

        return stages[min(step, len(stages) - 1)]
