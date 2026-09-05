"""
Interaction Agent
Formats internal results into user-facing responses.
Uses LangGraph's interrupt() for human-in-the-loop:
  - "finish" responses are delivered to the user via interrupt, then the graph ends.
  - "request" (clarification) responses pause the graph, collect user input, and resume.

Two interrupt-lifecycle rules this file must keep:

* LangGraph re-runs a node from the top when interrupt() resumes. The LLM call
  is therefore memoized on a fingerprint of the input state: the replay reuses
  the first response instead of paying for a second call whose sampling could
  take a different branch and consume the resume value at the wrong call site.
* Every interrupt payload carries a deterministic correlation_id, and a resume
  value shaped {"correlation_id": ..., "user_input": ...} is only accepted when
  the ids match; otherwise the same question is asked again. Replies are
  matched by id, never by call order.
"""

import hashlib
import re

from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.types import interrupt
from schema import InteractionResponse
from state import ProjectState, get_mission_goal
from models import Models
from prompt_loader import get_interaction_prompt


class InteractionAgent:
    """
    LLM-powered Interaction agent that generates user-facing responses.
    Uses the interaction prompt from the prompts directory.
    """

    _LLM_CACHE_MAX = 8

    def __init__(self):
        self.llm = Models.interaction(InteractionResponse)
        self.system_prompt = get_interaction_prompt()
        # Fingerprint of input state -> InteractionResponse | None. Survives the
        # node re-execution that follows every interrupt() resume.
        self._llm_cache: dict = {}

    # ── interrupt plumbing ─────────────────────────────────

    @staticmethod
    def _correlation_id(state: ProjectState, kind: str, message: str) -> str:
        """Deterministic id for one interrupt: stable across the node replay
        that follows a resume (same input state → same id), distinct across
        different questions."""
        basis = f"{kind}|{int(state.get('number_of_transactions', 0) or 0)}|{message}"
        return hashlib.sha1(basis.encode("utf-8", errors="replace")).hexdigest()[:12]

    @staticmethod
    def _ask_user(state: ProjectState, payload: dict) -> str:
        """interrupt() with correlation-id matching.

        Accepts either a plain string reply (legacy) or a dict
        {"correlation_id": ..., "user_input": ...}. A dict whose id does not
        match this payload is a reply to a different question; the same
        question is asked again rather than consuming the stale value.
        """
        cid = InteractionAgent._correlation_id(
            state, str(payload.get("type", "request")), str(payload.get("message", ""))
        )
        payload = dict(payload)
        payload["correlation_id"] = cid
        while True:
            reply = interrupt(payload)
            if isinstance(reply, dict) and "correlation_id" in reply:
                if str(reply.get("correlation_id")) == cid:
                    return str(reply.get("user_input", ""))
                continue
            if isinstance(reply, dict):
                return str(reply.get("user_input", ""))
            return str(reply)

    @staticmethod
    def _announce_finish(state: ProjectState, message: str) -> None:
        payload = {
            "type": "finish",
            "message": message,
            "correlation_id": InteractionAgent._correlation_id(state, "finish", message),
        }
        # Per-item outcomes ride the finish payload so the server can persist
        # them with the run and the UI can render a per-application report.
        item_results = state.get("item_results") or []
        if item_results:
            payload["item_results"] = [r for r in item_results if isinstance(r, dict)]
        interrupt(payload)

    def __call__(self, state: ProjectState) -> dict:
        user_intent = get_mission_goal(state)
        plan_history = state.get("plan_history", [])
        reasoning_log = state.get("reasoning_log", [])
        current_url = state.get("current_url", "unknown")
        is_complete = state.get("is_complete", False)
        mission_failed = state.get("mission_failed", False)
        abort_reason = state.get("abort_reason", "")

        # ── Fast path: explicit sensitive-action confirmation checkpoint ──
        pending_sensitive = state.get("pending_sensitive_action") or {}
        if isinstance(pending_sensitive, dict) and pending_sensitive.get("action_signature"):
            target = str(pending_sensitive.get("target") or pending_sensitive.get("action") or "the action")
            confirmation_message = (
                pending_sensitive.get("message")
                or "Please confirm this sensitive action. Reply yes to proceed or no to cancel."
            )
            user_reply = self._ask_user(state, {
                "type": "request",
                "message": confirmation_message,
                "requested_fields": ["approval"],
            })
            parsed = self._parse_sensitive_confirmation(str(user_reply))
            # An unclear reply ("yesd") is re-asked right here. Bouncing it back
            # through the orchestrator and a fresh executor call cost three
            # transactions per typo, and the executor, told to act "after an
            # explicit yes", once went looking for the word "yes" on the page.
            while parsed is None:
                retry_message = (
                    f"I did not understand \"{str(user_reply)[:60]}\". "
                    f"Reply yes to run {target}, or no to cancel it."
                )
                user_reply = self._ask_user(state, {
                    "type": "request",
                    "message": retry_message,
                    "requested_fields": ["approval"],
                })
                parsed = self._parse_sensitive_confirmation(str(user_reply))
            interaction_log = (
                "[Interaction] Type: request (sensitive_confirmation)\n"
                f"[Interaction] User replied: {str(user_reply)[:200]}"
            )

            if parsed is True:
                # The approval carries the exact action and arguments that were
                # proposed. The graph routes straight back to the executor, which
                # dispatches them as-is (Executor._execute_approved_action):
                # no new model decision gets to reword the task or pick another
                # target in between.
                return {
                    "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                    "reasoning_log": [
                        interaction_log + f"\n[Interaction] Approved: {target}; executing it next."
                    ],
                    "handoff_interaction": False,
                    "is_complete": False,
                    "pending_sensitive_action": None,
                    "sensitive_action_approval": {
                        "approved": True,
                        "reply": str(user_reply)[:200],
                        "action_signature": pending_sensitive.get("action_signature"),
                        "action": pending_sensitive.get("action"),
                        "args": dict(pending_sensitive.get("args") or {}),
                        "target": target,
                    },
                    "messages": [
                        {"role": "assistant", "content": confirmation_message},
                        {"role": "user", "content": str(user_reply)},
                    ],
                }

            final_message = "Sensitive action canceled. No irreversible action was executed."
            self._announce_finish(state, final_message)
            return {
                "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                "reasoning_log": [
                    "[Interaction] Type: finish (sensitive_confirmation_denied)\n"
                    f"[Interaction] User replied: {str(user_reply)[:200]}\n"
                    f"[Interaction] Final:\n{final_message}"
                ],
                "messages": [{"role": "assistant", "content": final_message}],
                "is_complete": True,
                "handoff_interaction": False,
                "pending_sensitive_action": None,
                "sensitive_action_approval": {
                    "approved": False,
                    "reply": str(user_reply)[:200],
                    "action_signature": pending_sensitive.get("action_signature"),
                    "action": pending_sensitive.get("action"),
                },
            }

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

            user_reply = self._ask_user(state, {
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
                "plan_status": "CREATE",
                "messages": [
                    {"role": "assistant", "content": message},
                    {"role": "user", "content": str(user_reply)},
                ],
            }

        # ── Fast path: fallback requested additional user context ──
        requested_context = state.get("requested_context") or []
        if isinstance(requested_context, list) and requested_context:
            message = "I need a bit more context to continue:"
            for item in requested_context:
                if str(item).strip():
                    message += f"\n- {str(item).strip()}"

            user_reply = self._ask_user(state, {
                "type": "request",
                "message": message,
                "requested_fields": [str(item).strip() for item in requested_context if str(item).strip()],
            })
            return {
                "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                "reasoning_log": [
                    f"[Interaction] Type: request (fallback context)\n"
                    f"[Interaction] Requested {len(requested_context)} context fields\n"
                    f"[Interaction] User replied: {str(user_reply)[:200]}"
                ],
                "handoff_interaction": False,
                "is_complete": False,
                "requested_context": [],
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
            self._announce_finish(state, final_message)
            return {
                "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                "reasoning_log": [
                    "[Interaction] Type: finish\n"
                    "[Interaction] Mission aborted due to safety stop\n"
                    f"[Interaction] Final:\n{final_message}"
                ],
                "messages": [{"role": "assistant", "content": final_message}],
                "is_complete": True,
                "handoff_interaction": False,
            }

        extracted_content = state.get("extracted_content") or []
        # Fall back to dom_cache (page text captured after each action) when
        # no explicit extract_text action populated extracted_content.
        if not extracted_content:
            dom_cache = state.get("dom_cache") or []
            if dom_cache:
                extracted_content = dom_cache[-2:]  # most recent page snapshots

        # Use status_signals to detect if human action is needed (current,
        # not historical).  A non-empty blocking_issue means the fallback
        # just requested human intervention for this specific cycle.
        signals = state.get("status_signals") or {}
        needs_human_action = bool(signals.get("blocking_issue"))

        if is_complete:
            system_status = "goal_completed"
        elif needs_human_action:
            system_status = "needs_human_action"
        else:
            system_status = "in_progress"

        actions_summary = "\n".join([
            f"- {log[:150]}..." if len(log) > 150 else f"- {log}"
            for log in reasoning_log[-5:]
        ])
        extracted_block = "\n\n---\n\n".join(extracted_content) if extracted_content else "(No content extracted from pages.)"
        extracted_block = self._clip_text(extracted_block, 15000)

        # Per-item outcomes for work-queue missions ("apply to these 5 jobs").
        item_results = state.get("item_results") or []
        if item_results:
            item_lines = [
                f"- item {int(r.get('index', 0)) + 1}: {r.get('description', '?')} → {r.get('status', '?')}"
                for r in item_results if isinstance(r, dict)
            ]
            item_results_block = "\n".join(item_lines)
        else:
            item_results_block = "(No per-item results; this was a single-objective mission.)"

        mission_status = self._clip_text(state.get("mission_status") or "", 2200)
        context = f"""
            MAIN_GOAL: {user_intent}

            VERIFIED_RESULT:
            Final URL: {current_url}
            Plan Executed: {plan_history[-1] if plan_history else 'N/A'}

            EXTRACTED_CONTENT (from pages visited; use this to answer the user):
            {extracted_block}

            Recent Actions:
            {actions_summary}

            SYSTEM_STATUS: {system_status}

            WORK_ITEM_RESULTS (per-item outcomes for bulk missions):
            {item_results_block}

            MISSION_STATUS:
            {mission_status}

            Generate a user-facing response based on this information. If EXTRACTED_CONTENT is present, summarize or use it to answer the user's goal. If WORK_ITEM_RESULTS has entries, report the outcome of every item.
            """

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=context)
        ]

        # Memoized across the node replay that follows an interrupt resume:
        # the same input state must produce the same response object, so the
        # replay walks the same branch and the resume value is consumed by the
        # same interrupt call site (and the second LLM call is never paid).
        cache_key = hashlib.sha1(
            f"{state.get('number_of_transactions', 0)}|{system_status}|{context}".encode("utf-8", errors="replace")
        ).hexdigest()
        if cache_key in self._llm_cache:
            response = self._llm_cache[cache_key]
        else:
            try:
                response: InteractionResponse = self.llm.invoke(messages)
            except Exception:
                response = None
            if len(self._llm_cache) >= self._LLM_CACHE_MAX:
                self._llm_cache.pop(next(iter(self._llm_cache)))
            self._llm_cache[cache_key] = response

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
            user_reply = self._ask_user(state, {
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
        self._announce_finish(state, final_message)

        interaction_log = (
            "[Interaction] Type: finish\n"
            "[Interaction] Generated user response\n"
            f"[Interaction] Final:\n{final_message}"
        )
        return {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "reasoning_log": [interaction_log],
            "handoff_interaction": False,
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

    @staticmethod
    def _clip_text(value: str, max_chars: int) -> str:
        text = (value or "").strip()
        if max_chars <= 0:
            return ""
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n... [truncated]"

    @staticmethod
    def _parse_sensitive_confirmation(reply: str) -> bool | None:
        text = (reply or "").strip().lower()
        if not text:
            return None
        collapsed = re.sub(r"\s+", " ", text)
        positive = bool(re.search(r"\b(yes|y|approve|approved|confirm|confirmed|proceed|continue|go ahead|ok|okay)\b", collapsed))
        negative = bool(re.search(r"\b(no|n|deny|denied|cancel|stop|do not|don't|dont|abort)\b", collapsed))
        if positive and not negative:
            return True
        if negative and not positive:
            return False
        return None
