"""
Interaction Agent
Formats internal results into user-facing responses.
Uses LangGraph's interrupt() for human-in-the-loop:
  - "finish" responses are delivered to the user via interrupt, then the graph ends.
  - "request" (clarification) responses pause the graph, collect user input, and resume.
"""

from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.types import interrupt
from schema import InteractionResponse
from state import ProjectState
from models import Models
from prompt_loader import get_interaction_prompt


class InteractionAgent:
    """
    LLM-powered Interaction agent that generates user-facing responses.
    Uses the interaction prompt from the prompts directory.
    """
    
    def __init__(self):
        self.llm = Models.interaction(InteractionResponse)
        self.system_prompt = get_interaction_prompt()

    def __call__(self, state: ProjectState) -> dict:
        user_intent = self._get_user_intent(state)
        plan_history = state.get("plan_history", [])
        reasoning_log = state.get("reasoning_log", [])
        current_url = state.get("current_url", "unknown")
        is_complete = state.get("is_complete", False)
        mission_failed = state.get("mission_failed", False)
        abort_reason = state.get("abort_reason", "")

        # ── Fast path: orchestrator already generated clarification questions ──
        if state.get("plan_status") == "NEEDS_CLARIFICATION":
            questions = self._extract_planner_questions(reasoning_log)
            message = "Before I begin, I need a bit more information:"
            fields = []
            for q in questions:
                message += f"\n- {q}"
                fields.append(q)
            if not fields:
                message = "Could you provide more details about what you'd like me to do?"
                fields = ["additional details"]

            user_reply = interrupt({
                "type": "request",
                "message": message,
                "requested_fields": fields,
            })
            return {
                "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                "reasoning_log": [
                    f"[Interaction] Type: request (planner clarification)\n"
                    f"[Interaction] Forwarded {len(fields)} questions\n"
                    f"[Interaction] User replied: {str(user_reply)[:200]}"
                ],
                "handoff_interaction": False,
                "is_complete": False,
                "messages": [
                    {"role": "assistant", "content": message},
                    {"role": "user", "content": str(user_reply)},
                ],
            }

        if mission_failed:
            final_message = (
                "The agent stopped before completing the request.\n"
                f"Reason: {abort_reason or 'Exceeded retry safety limits.'}\n"
                f"Last URL: {current_url}"
            )
            interrupt({"type": "finish", "message": final_message})
            return {
                "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                "reasoning_log": [
                    "[Interaction] Type: finish\n"
                    "[Interaction] Mission aborted due to safety stop\n"
                    f"[Interaction] Final:\n{final_message}"
                ],
                "messages": [{"role": "assistant", "content": final_message}],
            }

        extracted_content = state.get("extracted_content") or []
        # Fall back to dom_cache (page text captured after each action) when
        # no explicit extract_text action populated extracted_content.
        if not extracted_content:
            dom_cache = state.get("dom_cache") or []
            if dom_cache:
                extracted_content = dom_cache[-2:]  # most recent page snapshots

        # Detect if fallback requested human browser interaction
        needs_human_action = any(
            "[Fallback] Update Type: request_human_action" in (log or "")
            for log in reasoning_log
        )

        if needs_human_action:
            system_status = "needs_human_action"
        else:
            system_status = "goal_completed"

        actions_summary = "\n".join([
            f"- {log[:150]}..." if len(log) > 150 else f"- {log}"
            for log in reasoning_log[-5:]
        ])
        extracted_block = "\n\n---\n\n".join(extracted_content) if extracted_content else "(No content extracted from pages.)"

        context = f"""
            MAIN_GOAL: {user_intent}

            VERIFIED_RESULT:
            Final URL: {current_url}
            Plan Executed: {plan_history[-1] if plan_history else 'N/A'}

            EXTRACTED_CONTENT (from pages visited; use this to answer the user):
            {extracted_block[:25000]}

            Recent Actions:
            {actions_summary}

            SYSTEM_STATUS: {system_status}

            Generate a user-facing response based on this information. If EXTRACTED_CONTENT is present, summarize or use it to answer the user's goal.
            """

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=context)
        ]

        try:
            response: InteractionResponse = self.llm.invoke(messages)
        except Exception:
            response = None

        if response is not None:
            is_empty_finish = (
                getattr(response, "type", None) == "finish"
                and not (getattr(response, "message", "") or "").strip()
                and not (getattr(response, "data", "") or "").strip()
            )
            is_empty_request = (
                getattr(response, "type", None) == "request"
                and not (getattr(response, "message", "") or "").strip()
                and not getattr(response, "requested_fields", [])
            )
            if is_empty_finish or is_empty_request:
                response = None

        final_message = self._build_final_message(response, extracted_content, extracted_block)

        # ── HITL: deliver response to user via interrupt ──
        if response is not None and response.type == "request":
            requested_fields = getattr(response, "requested_fields", []) or []
            user_reply = interrupt({
                "type": "request",
                "message": final_message,
                "requested_fields": requested_fields,
            })
            interaction_log = (
                f"[Interaction] Type: request\n"
                f"[Interaction] Requested {len(requested_fields)} fields\n"
                f"[Interaction] User replied: {str(user_reply)[:200]}"
            )
            return {
                "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                "reasoning_log": [interaction_log],
                "handoff_interaction": False,
                "is_complete": False,
                "messages": [
                    {"role": "assistant", "content": final_message},
                    {"role": "user", "content": str(user_reply)},
                ],
            }

        # "finish" path — deliver the final answer to the user, then let the graph end
        interrupt({"type": "finish", "message": final_message})

        interaction_log = (
            "[Interaction] Type: finish\n"
            "[Interaction] Generated user response\n"
            f"[Interaction] Final:\n{final_message}"
        )
        return {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "reasoning_log": [interaction_log],
            "messages": [{"role": "assistant", "content": final_message}],
        }

    # ── helpers ────────────────────────────────────────────
    def _build_final_message(self, response, extracted_content, extracted_block):
        if response is None:
            if extracted_content:
                fallback = (extracted_block[:2000] + "...") if len(extracted_block) > 2000 else extracted_block
                return f"Summary (from extracted content):\n\n{fallback}"
            return "The task could not be completed. The interaction agent did not produce a response."

        if response.type == "finish":
            msg = (response.message or "").strip()
            if response.data and (response.data or "").strip():
                msg += f"\n\n{(response.data or '').strip()}"
            if not msg and extracted_content:
                fallback = (extracted_block[:2000] + "...") if len(extracted_block) > 2000 else extracted_block
                return f"Summary (from extracted content):\n\n{fallback}"
            return msg or "Task completed. No additional details were generated."

        # "request" type
        msg = response.message or "Please provide the following information:"
        if response.requested_fields:
            msg += "\n\nPlease provide:"
            for field in response.requested_fields:
                msg += f"\n- {field}"
        return msg

    @staticmethod
    def _extract_planner_questions(reasoning_log: list) -> list[str]:
        """Pull clarification questions from the orchestrator's reasoning log."""
        questions = []
        for entry in reasoning_log:
            if not isinstance(entry, str) or "Needs clarification" not in entry:
                continue
            for line in entry.splitlines():
                stripped = line.strip()
                if stripped.startswith("- "):
                    questions.append(stripped[2:].strip())
        return questions

    def _get_user_intent(self, state: ProjectState) -> str:
        user_message = state["messages"][0] if state["messages"] else None
        if isinstance(user_message, dict):
            return user_message.get("content", "Unknown intent")
        elif hasattr(user_message, "content"):
            return user_message.content
        return str(user_message) if user_message else "Unknown intent"
