"""
Verification Agent
Uses an LLM to decide whether the execution satisfied the current plan step.
"""

import re

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
        if out.get("made_progress"):
            out.pop("made_progress", None)
            out["stall_cycles"] = 0
            out["stall_tracked_step"] = current_step
            return out
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

        last_exec_lower = (last_execution or "").lower()
        recent_executor_logs = [
            entry for entry in (reasoning_log or [])
            if isinstance(entry, str) and entry.startswith("[Executor]")
        ]
        recent_executor_history = "\n\n".join(recent_executor_logs[-4:]) if recent_executor_logs else ""

        # Deterministic guardrail: do not allow failed executor actions to be
        # marked as successful just because page content looks plausible.
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

        # Safety net: high-confidence phrases that unambiguously indicate a
        # human-required screen.  These are specific enough to avoid false
        # positives from generic page text while catching MFA/CAPTCHA screens
        # the LLM might occasionally miss.
        _HUMAN_REQUIRED_PHRASES = (
            "approve sign-in request",
            "approve sign in request",
            "open your authenticator",
            "verify your identity",
            "blocked by captcha",
            "anti-bot challenge",
        )
        if any(phrase in last_exec_lower for phrase in _HUMAN_REQUIRED_PHRASES):
            verification_log = (
                "[Verifier] Verdict: failure\n"
                "[Verifier] Step Complete: False\n"
                "[Verifier] Goal Complete: False\n"
                "[Verifier] Message: Human action required (MFA/CAPTCHA detected in page content).\n"
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
                    "step_attempts": 0,
                    "reasoning_log": [verification_log],
                },
            )

        # Deterministic guardrail: during finalization-oriented steps
        # (send/submit/review), reject dismissive navigation actions that
        # move away from completion (Cancel/Close/Discard/Back).
        if self._is_finalization_step(current_task) and self._is_dismissive_action(last_exec_lower):
            verification_log = (
                "[Verifier] Verdict: failure\n"
                "[Verifier] Step Complete: False\n"
                "[Verifier] Goal Complete: False\n"
                "[Verifier] Message: The last action dismissed or backed out of the active form during a finalization step; recovery is required.\n"
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

        # Generic field-dependent completion: if the status tracker reports
        # that all required fields for this step are filled, complete the step.
        fp_complete, fp_done, fp_required = self._field_progress_step_complete(state, current_task)
        if fp_complete:
            verification_log = (
                "[Verifier] Verdict: success\n"
                "[Verifier] Step Complete: True\n"
                "[Verifier] Goal Complete: False\n"
                f"[Verifier] Message: Field-entry step complete ({fp_done}/{fp_required} required fields captured).\n"
                "[Verifier] Handoff: orchestration"
            )
            return self._apply_stall_cap(
                state,
                current_step,
                {
                    "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                    "needs_fallback": False,
                    "is_complete": False,
                    "last_step_complete": True,
                    "step_attempts": 0,
                    "made_progress": True,
                    "reasoning_log": [verification_log],
                },
            )

        # Deterministic compose-progress rule: email drafting is often multi-action
        # (recipient, subject, body). A single successful click/type should count as
        # progress, and recipient-confirm sequences should complete the recipient step.
        if self._is_email_compose_step(current_task):
            task_text = (current_task or "").lower()
            requires_content = any(tok in task_text for tok in ("subject", "message body", "body", "content"))
            target_email = self._extract_email(current_task)
            if (
                not requires_content
                and target_email
                and self._recipient_step_confirmed(target_email, last_exec_lower, recent_executor_logs)
            ):
                verification_log = (
                    "[Verifier] Verdict: success\n"
                    "[Verifier] Step Complete: True\n"
                    "[Verifier] Goal Complete: False\n"
                    "[Verifier] Message: Recipient entry appears confirmed for this compose step.\n"
                    "[Verifier] Handoff: orchestration"
                )
                return self._apply_stall_cap(
                    state,
                    current_step,
                    {
                        "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                        "needs_fallback": False,
                        "is_complete": False,
                        "last_step_complete": True,
                        "step_attempts": 0,
                        "made_progress": True,
                        "reasoning_log": [verification_log],
                    },
                )

            if self._compose_step_fields_complete_from_status(state, current_task):
                verification_log = (
                    "[Verifier] Verdict: success\n"
                    "[Verifier] Step Complete: True\n"
                    "[Verifier] Goal Complete: False\n"
                    "[Verifier] Message: Required compose fields for this step are already populated.\n"
                    "[Verifier] Handoff: orchestration"
                )
                return self._apply_stall_cap(
                    state,
                    current_step,
                    {
                        "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                        "needs_fallback": False,
                        "is_complete": False,
                        "last_step_complete": True,
                        "step_attempts": 0,
                        "made_progress": True,
                        "reasoning_log": [verification_log],
                    },
                )

            if self._compose_content_step_completed(current_task, recent_executor_logs):
                verification_log = (
                    "[Verifier] Verdict: success\n"
                    "[Verifier] Step Complete: True\n"
                    "[Verifier] Goal Complete: False\n"
                    "[Verifier] Message: Subject and message body appear populated for this compose step.\n"
                    "[Verifier] Handoff: orchestration"
                )
                return self._apply_stall_cap(
                    state,
                    current_step,
                    {
                        "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                        "needs_fallback": False,
                        "is_complete": False,
                        "last_step_complete": True,
                        "step_attempts": 0,
                        "made_progress": True,
                        "reasoning_log": [verification_log],
                    },
                )

            compose_fields = self._compose_fields_from_state(state)
            recipient_done = bool(compose_fields.get("recipient", False))
            body_pending = not bool(compose_fields.get("body", False))
            action_name, args_line = self._extract_executor_action_and_args(last_exec_lower)
            if requires_content and recipient_done and body_pending and self._compose_action_targets_recipient_lane(action_name, args_line):
                verification_log = (
                    "[Verifier] Verdict: failure\n"
                    "[Verifier] Step Complete: False\n"
                    "[Verifier] Goal Complete: False\n"
                    "[Verifier] Message: Compose content step drifted back to recipient targeting; switch to message-body field interaction.\n"
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

            if requires_content and recipient_done and body_pending and self._trailing_tab_focus_churn(recent_executor_logs) >= 2:
                verification_log = (
                    "[Verifier] Verdict: failure\n"
                    "[Verifier] Step Complete: False\n"
                    "[Verifier] Goal Complete: False\n"
                    "[Verifier] Message: Compose content step is stuck in focus navigation without body entry; fallback guidance required.\n"
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

            if self._is_compose_field_progress(last_exec_lower):
                meaningful_progress = self._compose_action_is_meaningful(last_exec_lower)
                verification_log = (
                    "[Verifier] Verdict: success\n"
                    "[Verifier] Step Complete: False\n"
                    "[Verifier] Goal Complete: False\n"
                    "[Verifier] Message: Compose step is in progress; field interaction succeeded and more draft fields remain.\n"
                    "[Verifier] Handoff: orchestration"
                )
                return self._apply_stall_cap(
                    state,
                    current_step,
                    {
                        "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                        "needs_fallback": False,
                        "is_complete": False,
                        "last_step_complete": False,
                        "step_attempts": int(state.get("step_attempts", 0)),
                        "made_progress": meaningful_progress,
                        "reasoning_log": [verification_log],
                    },
                )

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

    @staticmethod
    def _is_email_compose_step(task: str) -> bool:
        text = (task or "").lower()
        has_mail_context = any(token in text for token in ("email", "mail", "draft", "compose", "recipient", "subject", "message body"))
        has_field_fill_intent = any(token in text for token in (
            "to field",
            "recipient",
            "addressed",
            "address",
            "subject",
            "message body",
            "body",
            "fill",
        ))
        return has_mail_context and has_field_fill_intent

    @staticmethod
    def _extract_email(text: str) -> str:
        match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text or "")
        return match.group(0).lower() if match else ""

    @classmethod
    def _recipient_step_confirmed(cls, target_email: str, last_exec_lower: str, recent_executor_logs: list[str]) -> bool:
        if not target_email:
            return False
        recent = [(entry or "").lower() for entry in recent_executor_logs[-8:]]
        combined_recent = "\n".join(recent)
        type_entries = [
            entry for entry in recent
            if "[executor] action: type" in entry
            and "[executor] status: success" in entry
            and target_email in entry
        ]
        if not type_entries:
            return False

        typed_into_searchbox = any(
            any(tok in entry for tok in (
                "search my contacts",
                "search for email",
                "address book",
                "directory",
                "role=searchbox",
            ))
            for entry in type_entries
        )
        typed_into_direct_recipient = any(
            any(tok in entry for tok in (
                "label=to",
                "name=to",
                "label=recipient",
                "placeholder=recipient",
            ))
            and "search my contacts" not in entry
            and "search for email" not in entry
            for entry in type_entries
        )

        confirmed_action_last = (
            "[executor] status: success" in last_exec_lower
            and (
                (
                    "[executor] action: click" in last_exec_lower
                    and any(token in last_exec_lower for token in (
                        "name=add",
                        "name=done",
                        "name=ok",
                        "name=confirm",
                        "name=apply",
                    ))
                )
                or (
                    "[executor] action: click" in last_exec_lower
                    and "role=option" in last_exec_lower
                    and (target_email in last_exec_lower or "people suggestion" in last_exec_lower)
                )
                or (
                    "[executor] action: press_key" in last_exec_lower
                    and "key=enter" in last_exec_lower
                )
            )
        )
        confirmed_action_recent = (
            "[executor] status: success" in combined_recent
            and (
                (
                    "[executor] action: click" in combined_recent
                    and any(token in combined_recent for token in (
                        "name=add",
                        "name=done",
                        "name=ok",
                        "name=confirm",
                        "name=apply",
                    ))
                )
                or (
                    "[executor] action: click" in combined_recent
                    and "role=option" in combined_recent
                    and (target_email in combined_recent or "people suggestion" in combined_recent)
                )
                or (
                    "[executor] action: press_key" in combined_recent
                    and "key=enter" in combined_recent
                )
            )
        )
        confirmed_action = confirmed_action_last or confirmed_action_recent
        recipient_visible = target_email in last_exec_lower or target_email in combined_recent

        # Direct To/recipient-field typing is usually sufficient evidence.
        if typed_into_direct_recipient and recipient_visible:
            return True

        # Searchbox typing alone is not enough; require explicit add/select/enter confirmation.
        if typed_into_searchbox:
            return confirmed_action and recipient_visible

        return confirmed_action and recipient_visible

    @staticmethod
    def _compose_action_is_meaningful(last_exec_lower: str) -> bool:
        """Identify whether the latest compose action likely made real forward progress."""
        text = (last_exec_lower or "").lower()
        if "[executor] status: success" not in text:
            return False
        if "[executor] action: type" in text:
            return True
        if "[executor] action: click" in text:
            # Treat frequent no-op controls as non-progress so stall recovery can trigger.
            low_signal = (
                "name=save",
                "name=to",
                "name=cc",
                "name=bcc",
            )
            if any(tok in text for tok in low_signal):
                return False
            return True
        if "[executor] action: press_key" in text:
            if "key=tab" in text:
                return False
            return "key=enter" in text
        return False

    @staticmethod
    def _is_compose_field_progress(last_exec_lower: str) -> bool:
        if "[executor] status: success" not in last_exec_lower:
            return False
        if Verifier._is_dismissive_action(last_exec_lower):
            return False
        action_is_interactive = any(
            marker in last_exec_lower
            for marker in (
                "[executor] action: click",
                "[executor] action: type",
                "[executor] action: press_key",
            )
        )
        if not action_is_interactive:
            return False
        if "error type:" in last_exec_lower and "none" not in last_exec_lower:
            return False
        return True

    @classmethod
    def _compose_content_step_completed(cls, task: str, recent_executor_logs: list[str]) -> bool:
        """Return True when a compose-content step has both subject and body typed."""
        task_text = (task or "").lower()
        is_content_step = (
            any(tok in task_text for tok in ("compose", "draft", "email", "mail", "message"))
            and any(tok in task_text for tok in ("subject", "message body", "email message", "body", "content"))
        )
        if not is_content_step:
            return False

        requires_recipient = any(tok in task_text for tok in ("addressed to", "recipient", "to field", "to:"))

        subject_typed = False
        body_typed = False
        recipient_typed = False
        for raw_entry in recent_executor_logs[-10:]:
            entry = (raw_entry or "").lower()
            if "[executor] action: type" not in entry or "[executor] status: success" not in entry:
                continue

            match = re.search(r"\[executor\] args:\s*text=(.*)", entry)
            text_value = match.group(1).strip().strip("\"'") if match else ""
            if not text_value:
                continue

            text_word_count = len(re.findall(r"\S+", text_value))
            target_is_subject = any(tok in entry for tok in ("label=subject", "placeholder=add a subject", "name=subject"))
            recipient_context = any(tok in entry for tok in (
                "label=to",
                "name=to",
                "label=recipient",
                "placeholder=recipient",
                "search for email",
                "search my contacts",
                "add recipients",
            ))
            target_is_body = any(tok in entry for tok in (
                "label=message body",
                "contenteditable=true",
                "role=textbox",
                "placeholder=message",
            )) and not recipient_context
            target_is_recipient = any(tok in entry for tok in (
                "label=to",
                "name=to",
                "label=recipient",
                "placeholder=recipient",
                "search for email",
            ))

            if target_is_subject and len(text_value) >= 3:
                subject_typed = True
            if target_is_body and (
                text_word_count >= 6
                or (len(text_value) >= 40 and "@" not in text_value)
            ):
                body_typed = True
            # Heuristic: long non-email content typed outside subject/recipient lanes
            # is usually body text even when the target label is sparse.
            if (
                not target_is_subject
                and not recipient_context
                and "@" not in text_value
                and text_word_count >= 8
            ):
                body_typed = True
            if target_is_recipient and "@" in text_value:
                recipient_typed = True

        return subject_typed and body_typed and (recipient_typed or not requires_recipient)

    @staticmethod
    def _compose_fields_from_state(state: ProjectState) -> dict:
        signals = state.get("status_signals") or {}
        compose_fields = signals.get("compose_fields") or {}
        return {
            "recipient": bool(compose_fields.get("recipient", False)),
            "subject": bool(compose_fields.get("subject", False)),
            "body": bool(compose_fields.get("body", False)),
        }

    @staticmethod
    def _normalize_task_signature(task: str) -> str:
        text = (task or "").strip()
        if not text:
            return ""
        text = re.sub(r"\s*\[Recovery Hint:.*$", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s*\[Then continue objective:.*$", "", text, flags=re.IGNORECASE).strip()
        return text.lower()

    def _field_progress_step_complete(self, state: ProjectState, current_task: str) -> tuple[bool, int, int]:
        signals = state.get("status_signals") or {}
        progress = signals.get("field_progress") if isinstance(signals.get("field_progress"), dict) else None
        if not progress:
            return False, 0, 0
        task_sig = self._normalize_task_signature(current_task)
        if not task_sig or progress.get("task_signature") != task_sig:
            return False, 0, 0
        required = int(progress.get("required_count") or 0)
        completed = list(progress.get("completed_fields") or [])
        done = len(completed)
        if required <= 0:
            return False, done, required
        return done >= required, done, required

    def _compose_step_fields_complete_from_status(self, state: ProjectState, task: str) -> bool:
        if not self._is_email_compose_step(task):
            return False
        fields = self._compose_fields_from_state(state)
        text = (task or "").lower()

        required: list[str] = []
        if any(tok in text for tok in ("recipient", "to field", "to:")):
            required.append("recipient")
        if "subject" in text:
            required.append("subject")
        if any(tok in text for tok in ("message body", "email body", " body", "content", "message")):
            required.append("body")

        if not required:
            return False
        return all(fields.get(name, False) for name in required)

    @staticmethod
    def _extract_executor_action_and_args(last_exec_lower: str) -> tuple[str, str]:
        text = (last_exec_lower or "").lower()
        action_match = re.search(r"^\[executor\]\s+action:\s*([^\n]+)$", text, re.IGNORECASE | re.MULTILINE)
        args_match = re.search(r"^\[executor\]\s+args:\s*([^\n]+)$", text, re.IGNORECASE | re.MULTILINE)
        action_name = action_match.group(1).strip().lower() if action_match else ""
        args_line = args_match.group(1).strip().lower() if args_match else ""
        return action_name, args_line

    @staticmethod
    def _compose_action_targets_recipient_lane(action_name: str, args_line: str) -> bool:
        if not action_name or not args_line:
            return False
        recipient_tokens = (
            "name=to",
            "name=recipient",
            "label=to",
            "label=recipient",
            "search my contacts",
            "search for email",
            "add recipients",
            "address book",
        )
        if action_name == "click":
            return any(tok in args_line for tok in recipient_tokens) or "role=searchbox" in args_line or "role=combobox" in args_line
        if action_name == "type":
            text_match = re.search(r"text=(.*)", args_line)
            typed = text_match.group(1).strip() if text_match else ""
            return "@" in typed
        return False

    @staticmethod
    def _trailing_tab_focus_churn(recent_executor_logs: list[str]) -> int:
        streak = 0
        for raw in reversed(recent_executor_logs[-6:]):
            entry = (raw or "").lower()
            if "[executor] status: success" not in entry:
                break
            if "[executor] action: press_key" in entry and "key=tab" in entry:
                streak += 1
                continue
            break
        return streak

    @staticmethod
    def _is_finalization_step(task: str) -> bool:
        text = (task or "").lower()
        return any(token in text for token in (
            "send",
            "submit",
            "finalize",
            "review",
            "confirm",
            "complete",
            "finish",
        ))

    @staticmethod
    def _is_dismissive_action(last_exec_lower: str) -> bool:
        text = (last_exec_lower or "").lower()
        if "[executor] action: click" not in text:
            return False
        dismissive_tokens = (
            "name=cancel",
            "name=close",
            "name=discard",
            "name=back",
            "name=hide",
            "name=dismiss",
            "name=exit",
        )
        return any(token in text for token in dismissive_tokens)

    @classmethod
    def reset_simulation(cls):
        pass
