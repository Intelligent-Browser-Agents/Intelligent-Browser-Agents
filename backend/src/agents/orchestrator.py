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
            for m in raw_msgs[-6:]:
                if isinstance(m, dict):
                    role, text = m.get("role", "?"), m.get("content", "")
                elif hasattr(m, "type"):
                    role, text = m.type, getattr(m, "content", "")
                else:
                    role, text = "?", str(m)
                lines.append(f"  [{role.upper()}]: {self._clip_text(str(text), 400)}")
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
        recent_log = [self._clip_text(str(entry), 600) for entry in (state.get("reasoning_log") or [])[-3:]]

        # Post-HITL handling via status_signals.
        # When the user just completed a HITL (e.g. MFA) and the login_phase
        # signal confirms completion, advance past the current step.
        if not step_complete:
            signals = state.get("status_signals") or {}
            hitl_events = signals.get("hitl_events") or []
            login_phase = signals.get("login_phase", "not_started")

            just_returned_from_hitl = bool(hitl_events) and (
                hitl_events[-1].get("transaction", -1)
                >= state.get("number_of_transactions", 0) - 2
            )
            if just_returned_from_hitl and login_phase == "completed":
                next_step = min(safe_step + 1, total_steps - 1)
                next_task = current_plan[next_step]
                if safe_step >= total_steps - 1:
                    return {
                        "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                        "current_step_index": safe_step,
                        "plan_status": "MAINTAIN",
                        "current_task": current_plan[safe_step],
                        "reasoning_log": ["[Decision] HITL completed login/MFA; marking plan complete."],
                        "is_complete": True,
                        "handoff_interaction": True,
                        "needs_fallback": False,
                        "mission_failed": False,
                    }
                return {
                    "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                    "current_step_index": next_step,
                    "plan_status": "MAINTAIN",
                    "current_task": next_task,
                    "reasoning_log": [f"[Decision] HITL completed login/MFA; advancing to step {next_step + 1}/{total_steps}."],
                    "is_complete": False,
                    "needs_fallback": False,
                    "mission_failed": False,
                    "last_step_complete": False,
                }

        mission_status = self._clip_text(state.get("mission_status") or "", 4000)
        recent_context_block = self._clip_text(chr(10).join(recent_log) if recent_log else "  (none yet)", 1500)

        # Extract the verifier's verdict and message so the decision-maker
        # can reason over evidence, not just the step_complete boolean.
        verifier_verdict = ""
        verifier_message = ""
        for entry in reversed(recent_log):
            entry_str = str(entry)
            if "[Verifier] Verdict:" in entry_str:
                for line in entry_str.split("\n"):
                    stripped = line.strip()
                    if stripped.startswith("[Verifier] Verdict:"):
                        verifier_verdict = stripped.split(":", 1)[1].strip()
                    elif stripped.startswith("[Verifier] Message:"):
                        verifier_message = stripped.split(":", 1)[1].strip()
                break

        context = f"""
USER GOAL: {user_intent}

CURRENT PLAN (steps 1 to {total_steps}):
{chr(10).join(f"  {i+1}. {s}" for i, s in enumerate(current_plan))}

CURRENT STEP INDEX: {safe_step + 1} (1-based)
LAST STEP COMPLETE: {step_complete}
CURRENT TASK: {current_task}

VERIFIER VERDICT: {verifier_verdict or "(unknown)"}
VERIFIER MESSAGE: {verifier_message or "(none)"}

RECENT CONTEXT (execution/verification):
{recent_context_block}

MISSION_STATUS:
{mission_status}

Based on the rules, output exactly one action: advance, retry, or plan_complete.
"""

        messages = [
            SystemMessage(content=self.reasoning_prompt),
            HumanMessage(content=context.strip()),
        ]

        # Unambiguous cases: skip LLM to avoid wrong "retry" and prevent loops
        goal_already_complete = state.get("is_complete", False)

        if step_complete and safe_step >= total_steps - 1:
            original_step = current_plan[safe_step]
            completed_fallback_prereq = self._is_explicit_prerequisite_variant(current_task, original_step)
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
            # Only mark plan complete if the verifier also confirmed
            # goal_complete. If step_complete=True but goal_complete=False
            # (e.g. found a link but didn't extract the data), retry so
            # the executor can finish the actual goal.
            if goal_already_complete:
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
            # step_complete but goal NOT complete — more work needed
            reasoning = (
                f"[Decision] Step {safe_step + 1}/{total_steps} marked complete "
                f"but the overall goal is not yet achieved; retrying to finish."
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
        if step_complete and safe_step < total_steps - 1:
            original_step = current_plan[safe_step]
            if self._is_explicit_prerequisite_variant(current_task, original_step):
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

    @staticmethod
    def _is_explicit_prerequisite_variant(current_task: str, original_step: str) -> bool:
        task = (current_task or "").strip()
        original = (original_step or "").strip()
        if task == original:
            return False
        # Only treat as prerequisite when fallback explicitly marked it.
        return "[Then continue objective:" in task

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

    @staticmethod
    def _clip_text(value: str, max_chars: int) -> str:
        text = (value or "").strip()
        if max_chars <= 0:
            return ""
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n... [truncated]"

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
        stages = [
            f"Page loaded at {url}. Navigation and content elements visible.",
            "Interacted with page. Elements responding to actions.",
            "Progress made. Page state updated.",
            "Near completion. Final actions pending.",
            "Task completed successfully.",
        ]
        return stages[min(step, len(stages) - 1)]
