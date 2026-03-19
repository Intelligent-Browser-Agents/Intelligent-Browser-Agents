"""
Orchestration Agent
Converts user requests into ordered high-level subtasks (plan) and reasons over
execution outcomes to decide next action (advance / retry / plan_complete).
"""

from langchain_core.messages import SystemMessage, HumanMessage

from schema import OrchestratorPlan, OrchestratorDecision
from state import ProjectState
from models import Models
from prompt_loader import get_orchestration_plan_prompt, get_orchestration_reasoning_prompt


class Orchestrator:
    """
    Dual-prompt orchestration: plan creation + reasoning/action.

    - Planning: LLM creates initial plan (or asks for clarification).
    - Reasoning and action: LLM decides advance, retry, or plan_complete from verification state.
    """

    def __init__(self):
        self.planner = Models.planner(OrchestratorPlan)
        self.decision_maker = Models.decision_maker(OrchestratorDecision)
        self.planning_prompt = get_orchestration_plan_prompt()
        self.reasoning_prompt = get_orchestration_reasoning_prompt()

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
        # Build a conversation recap so the planner sees any clarification replies
        conversation_block = ""
        raw_msgs = state.get("messages", [])
        if len(raw_msgs) > 1:
            lines = []
            for m in raw_msgs:
                if isinstance(m, dict):
                    role, text = m.get("role", "?"), m.get("content", "")
                elif hasattr(m, "type"):
                    role, text = m.type, getattr(m, "content", "")
                else:
                    role, text = "?", str(m)
                lines.append(f"  [{role.upper()}]: {text}")
            conversation_block = (
                "\n\nCONVERSATION SO FAR (includes any user clarifications):\n"
                + "\n".join(lines)
            )

        credentials_block = self._build_credentials_summary(state)

        context = f"""
        USER REQUEST: {user_intent}

        CURRENT URL: {state.get('current_url', 'https://google.com')}

        PAGE STATE:
        {page_state}
        {conversation_block}
        {credentials_block}

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
        current_task = state.get("current_task") or (current_plan[safe_step] if current_plan else "No task")
        user_intent = self._get_user_intent(state)
        recent_log = (state.get("reasoning_log") or [])[-3:]

        context = f"""
USER GOAL: {user_intent}

CURRENT PLAN (steps 1 to {total_steps}):
{chr(10).join(f"  {i+1}. {s}" for i, s in enumerate(current_plan))}

CURRENT STEP INDEX: {safe_step + 1} (1-based)
LAST STEP COMPLETE: {step_complete}
CURRENT TASK: {current_task}

RECENT CONTEXT (execution/verification):
{chr(10).join(recent_log) if recent_log else "  (none yet)"}

Based on the rules, output exactly one action: advance, retry, or plan_complete.
"""

        messages = [
            SystemMessage(content=self.reasoning_prompt),
            HumanMessage(content=context.strip()),
        ]

        # Unambiguous cases: skip LLM to avoid wrong "retry" and prevent loops
        if step_complete and safe_step >= total_steps - 1:
            original_step = current_plan[safe_step]
            completed_fallback_prereq = (
                current_task.strip() != original_step.strip()
            )
            if completed_fallback_prereq:
                reasoning = (
                    f"[Decision] Fallback prerequisite completed; "
                    f"retrying original step {safe_step + 1}/{total_steps}."
                )
                return {
                    "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                    "current_step_index": safe_step,
                    "plan_status": "MAINTAIN",
                    "current_task": original_step,
                    "reasoning_log": [reasoning],
                    "is_complete": False,
                    "needs_fallback": False,
                    "mission_failed": False,
                    "last_step_complete": False,
                }
            reasoning = "[Decision] Final step verified complete; marking plan complete."
            return {
                "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                "current_step_index": safe_step,
                "plan_status": "MAINTAIN",
                "current_task": original_step,
                "reasoning_log": [reasoning],
                "is_complete": True,
                "handoff_interaction": True,
                "needs_fallback": False,
                "mission_failed": False,
            }
        if step_complete and safe_step < total_steps - 1:
            original_step = current_plan[safe_step]
            if current_task.strip() != original_step.strip():
                reasoning = (
                    f"[Decision] Fallback prerequisite completed; "
                    f"retrying original step {safe_step + 1}/{total_steps}."
                )
                return {
                    "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                    "current_step_index": safe_step,
                    "plan_status": "MAINTAIN",
                    "current_task": original_step,
                    "reasoning_log": [reasoning],
                    "is_complete": False,
                    "needs_fallback": False,
                    "mission_failed": False,
                    "last_step_complete": False,
                }
            next_step = min(safe_step + 1, total_steps - 1)
            next_task = current_plan[next_step]
            reasoning = f"[Decision] Step {safe_step + 1}/{total_steps} complete; advancing to next step."
            return {
                "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                "current_step_index": next_step,
                "plan_status": "MAINTAIN",
                "current_task": next_task,
                "reasoning_log": [reasoning],
                "is_complete": False,
                "needs_fallback": False,
                "mission_failed": False,
                "last_step_complete": False,
            }

        try:
            decision: OrchestratorDecision = self.decision_maker.invoke(messages)
        except Exception as e:
            reasoning = f"[Decision] LLM failed: {e}; using rule-based fallback."
            return self._decision_fallback(
                state, current_plan, safe_step, step_complete, current_task, reasoning
            )

        decision_reasoning = getattr(decision, "reasoning", "") or (decision.model_dump().get("reasoning") if hasattr(decision, "model_dump") else "") or ""
        decision_action = getattr(decision, "action", None) or (decision.model_dump().get("action") if hasattr(decision, "model_dump") else None)
        if decision_action not in ("advance", "retry", "plan_complete"):
            decision_action = "retry"
        reasoning = f"[Decision] {decision_reasoning or '(no reasoning)'}\n[Decision] Action: {decision_action}"

        if decision_action == "plan_complete":
            return {
                "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                "current_step_index": safe_step,
                "plan_status": "MAINTAIN",
                "current_task": current_plan[safe_step],
                "reasoning_log": [reasoning],
                "is_complete": True,
                "handoff_interaction": True,
                "needs_fallback": False,
                "mission_failed": False,
            }

        if decision_action == "advance":
            next_step = min(safe_step + 1, total_steps - 1)
            next_task = current_plan[next_step]
            return {
                "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                "current_step_index": next_step,
                "plan_status": "MAINTAIN",
                "current_task": next_task,
                "reasoning_log": [reasoning],
                "is_complete": False,
                "needs_fallback": False,
                "mission_failed": False,
                "last_step_complete": False,
            }

        # retry: keep same step and task
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

    def _decision_fallback(
        self,
        state: ProjectState,
        current_plan: list,
        safe_step: int,
        step_complete: bool,
        current_task: str,
        reasoning: str,
    ) -> dict:
        """Rule-based fallback when the reasoning LLM fails."""
        total_steps = len(current_plan)
        if step_complete and safe_step >= total_steps - 1:
            return {
                "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                "current_step_index": safe_step,
                "plan_status": "MAINTAIN",
                "current_task": current_plan[safe_step],
                "reasoning_log": [reasoning],
                "is_complete": True,
                "handoff_interaction": True,
                "needs_fallback": False,
                "mission_failed": False,
            }
        if step_complete:
            next_step = min(safe_step + 1, total_steps - 1)
            return {
                "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                "current_step_index": next_step,
                "plan_status": "MAINTAIN",
                "current_task": current_plan[next_step],
                "reasoning_log": [reasoning],
                "is_complete": False,
                "needs_fallback": False,
                "mission_failed": False,
                "last_step_complete": False,
            }
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

    def _is_presentation_only_step(self, task: str) -> bool:
        """True if the step is only about presenting/summarizing for the user (no browser action)."""
        if not (task or "").strip():
            return False
        t = task.lower().strip()
        presentation_markers = (
            "present the",
            "present the gathered",
            "summarize",
            "summarise",
            "tell the user",
            "tell the user about",
            "report back",
            "report to the user",
            "give the user",
            "provide the user",
            "share the",
        )
        return any(m in t for m in presentation_markers)

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
            "handoff_interaction": True,
            "needs_fallback": False,
            "mission_failed": True,
            "abort_reason": reason,
            "reasoning_log": [reasoning],
        }

    @staticmethod
    def _build_credentials_summary(state: ProjectState) -> str:
        """Build a summary of available credentials for the planner (names only, no secrets)."""
        creds = state.get("user_credentials") or {}
        if not creds:
            return ""

        parts = []
        full_name = creds.get("fullName", "").strip()
        if full_name:
            parts.append(f"- Personal info on file (name, email, phone, address)")

        services = creds.get("userCredentialsList") or []
        if services:
            names = [s.get("serviceName", "unnamed") for s in services if isinstance(s, dict)]
            parts.append(f"- Saved login credentials for: {', '.join(names)}")

        payments = creds.get("userPaymentMethods") or []
        if payments:
            parts.append(f"- {len(payments)} saved payment method(s)")

        experience = creds.get("userExperienceEntries") or []
        if experience:
            parts.append(f"- {len(experience)} experience/education entries")

        if not parts:
            return ""
        return (
            "\n\nAVAILABLE USER CREDENTIALS (the agent can auto-fill these — no need for human-in-the-loop):\n"
            + "\n".join(parts)
        )

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
