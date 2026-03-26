"""
Fallback Agent
Uses an LLM to diagnose failures and propose a revised step or recovery.
"""

import re

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
        objective_task = self._base_task(current_task)
        reasoning_log = state.get("reasoning_log", [])
        user_intent = self._get_user_intent(state)
        current_url = state.get("current_url", "")
        dom_cache = state.get("dom_cache") or []
        last_dom_snapshot = dom_cache[-1] if dom_cache else ""
        # Keep the context bounded; dom_cache entries can be large.
        last_dom_snapshot = (last_dom_snapshot or "").strip()[:12000]
        previous_dom_snapshot = dom_cache[-2] if len(dom_cache) >= 2 else ""
        previous_dom_snapshot = (previous_dom_snapshot or "").strip()[:8000]

        last_verification = self._find_latest_log(reasoning_log, "[Verifier]") or "Verification failed."
        last_execution = (
            self._find_latest_log(reasoning_log, "[Executor]")
            or self._find_latest_log(reasoning_log, "[Verifier]")
            or "No execution log."
        )

        mission_status = state.get("mission_status") or ""
        context = f"""
MAIN_GOAL: {user_intent}

PLAN_STEP (failed): {current_task}

VERIFICATION_OUTPUT:
{last_verification[:500]}

EXECUTION_OUTPUT:
{last_execution[:500]}

CURRENT_URL: {current_url}

AFTER_STATE (from dom_cache; use as DOM evidence):
LAST_DOM_SNAPSHOT:
{last_dom_snapshot or "[dom_cache missing]"}

PREVIOUS_DOM_SNAPSHOT (optional):
{previous_dom_snapshot or "[not available]"}

MISSION_STATUS:
{mission_status}

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
            revised_task = objective_task
            fallback_log = (
                "[Fallback] LLM failed; retrying same step.\n"
                f"[Fallback] Error: {err}\n"
                f"[Fallback] Message to Orchestration: Retry the current step."
            )
            needs_human = False
        else:
            proposed = (
                (strategy.proposed_step or "").strip()
                or (strategy.insert_step or "").strip()
                or objective_task
            )

            revised_task = self._compose_recovery_task(
                objective_task=objective_task,
                proposed_task=proposed,
                update_type=strategy.update_type,
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

    @staticmethod
    def _base_task(task: str) -> str:
        text = (task or "").strip()
        marker = " [Recovery Hint:"
        idx = text.find(marker)
        if idx >= 0:
            return text[:idx].strip()
        return text or "Unknown task"

    @staticmethod
    def _compose_recovery_task(objective_task: str, proposed_task: str, update_type: str) -> str:
        obj = (objective_task or "Unknown task").strip()
        hint = (proposed_task or "").strip()
        if not hint or hint.lower() == obj.lower():
            return obj
        if update_type == "insert_step_before":
            return f"{hint} [Then continue objective: {obj}]"
        if update_type == "revise_step":
            # Adaptive escape hatch: when reality requires a prerequisite
            # navigation/repositioning action, place that action first while
            # preserving the objective as an explicit continuation.
            if Fallback._looks_like_prerequisite_realign(hint, obj):
                return f"{hint} [Then continue objective: {obj}]"
            return f"{obj} [Recovery Hint: {hint}]"
        if update_type in {"request_context", "request_human_action"}:
            return f"{obj} [Recovery Hint: {hint}]"
        return obj

    @staticmethod
    def _looks_like_prerequisite_realign(hint: str, objective: str) -> bool:
        h = (hint or "").lower()
        o = (objective or "").lower()
        if not h:
            return False
        # Signals that the next best action is to re-enter the right surface
        # before continuing with the original objective.
        realign_tokens = (
            "navigate",
            "go to",
            "open",
            "return",
            "go back",
            "switch",
            "focus",
            "from",
            "instead of",
            "wrong page",
            "mail interface",
            "compose window",
        )
        has_realign_intent = any(tok in h for tok in realign_tokens)
        if not has_realign_intent:
            return False

        # If the hint shares little overlap with objective terms, treat it as
        # a prerequisite repositioning step rather than a pure wording tweak.
        objective_terms = {
            tok for tok in re.findall(r"[a-z]{4,}", o)
            if tok not in {"using", "with", "from", "that", "this", "then", "user"}
        }
        hint_terms = {
            tok for tok in re.findall(r"[a-z]{4,}", h)
            if tok not in {"using", "with", "from", "that", "this", "then", "user"}
        }
        if not objective_terms or not hint_terms:
            return True
        overlap = len(objective_terms & hint_terms)
        return overlap <= 1

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
