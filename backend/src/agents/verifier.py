"""
Verification Agent
Decides whether the execution satisfied the current plan step.

Structural evidence comes first: the executor's own status and post-condition
verification, the field-progress tracker (fed by read_form), and URL/DOM deltas
between consecutive snapshots. One LLM call judges the genuinely ambiguous
residue. There are deliberately no task-keyword classifiers here; gating on
words like "send", "review" or "complete" is how job applications used to be
misread as email drafts and blocked.
"""

import re

from langchain_core.messages import SystemMessage, HumanMessage

from state import ProjectState, get_mission_goal
from schema import VerificationResult, last_execution_event_to_executor_log
from models import Models
from prompt_loader import get_verification_prompt, load_site_notes


class Verifier:
    """
    LLM-based verifier: given the plan step, the structural signals, and the
    post-action page evidence, decide if the step is complete and whether to
    hand off to orchestration or fallback.
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
        *,
        made_progress: bool = False,
    ) -> dict:
        """
        General stall detection: count consecutive incomplete verification
        cycles on the same plan step and force fallback when the cap is hit.
        `made_progress` is passed explicitly; it is a control signal for this
        counter, not a state field.
        """
        out = dict(partial)
        if made_progress or out.get("needs_fallback") or bool(out.get("last_step_complete")):
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
        event = state.get("last_execution_event")
        event = event if isinstance(event, dict) else {}
        mission_goal = get_mission_goal(state)

        recent_executor_logs = [
            entry for entry in (reasoning_log or [])
            if isinstance(entry, str) and entry.startswith("[Executor]")
        ]

        # Two views of the same action, for two jobs. The structured view is
        # rendered from last_execution_event and is what the deterministic
        # guards read. The raw executor log entry is the only *log* carrier of
        # AFTER_STATE (the post-action page snapshot); when the executor also
        # published the snapshot as state["last_page_snapshot"], that structured
        # field wins because it is not clipped by log-entry limits.
        if (event.get("action") or "").strip():
            last_execution_structured = last_execution_event_to_executor_log(event)
        else:
            last_execution_structured = recent_executor_logs[-1] if recent_executor_logs else "No execution log."

        page_snapshot = (state.get("last_page_snapshot") or "").strip()
        if page_snapshot:
            last_execution = (
                f"{last_execution_structured}\n"
                f"[Executor] AFTER_STATE (page content for verification):\n"
                f"{self._clip_text(page_snapshot, 2200)}"
            )
        else:
            last_execution = recent_executor_logs[-1] if recent_executor_logs else last_execution_structured
            if "AFTER_STATE" not in last_execution:
                # No page evidence in the raw entry; the structured view is no worse.
                last_execution = last_execution_structured

        last_exec_lower = (last_execution_structured or "").lower()
        # Three entries, matching the prompt's repeated-read-only-actions rule;
        # a 3-action pattern cannot be observed in a 2-entry window.
        recent_executor_history = "\n\n".join(recent_executor_logs[-3:]) if recent_executor_logs else ""
        recent_executor_history = self._clip_text(recent_executor_history, 2600)

        # ── Structural signals ────────────────────────────────────────────
        event_status = str(event.get("status") or "").strip().lower()
        action_failed = (
            event_status == "failure"
            if event_status
            else "[executor] status: failure" in last_exec_lower
        )
        # The Phase 2 action layer sets `verified` from post-condition readback
        # (input_value, is_checked, URL/DOM digest). The executor forwards it on
        # the action path; it is None only for pre-execution failures (invalid
        # tool call, timeout), so keep the tri-state handling.
        event_verified = event.get("verified") if isinstance(event.get("verified"), bool) else None
        extracted_present = bool(event.get("extracted_content_present"))
        url_changed, dom_changed = self._page_delta(state)
        made_progress = (not action_failed) and (
            event_verified is True or url_changed or dom_changed or extracted_present
        )

        # ── Deterministic guard: a failed action is not ambiguous ─────────
        if action_failed:
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

        # ── Safety net: page evidence of a human-required screen ──────────
        # High-confidence phrases that unambiguously indicate MFA/CAPTCHA
        # screens the LLM might occasionally miss. This scans page evidence
        # (AFTER_STATE), not task text.
        _HUMAN_REQUIRED_PHRASES = (
            "approve sign-in request",
            "approve sign in request",
            "open your authenticator",
            "verify your identity",
            "blocked by captcha",
            "anti-bot challenge",
        )
        page_evidence_lower = (page_snapshot or last_execution or "").lower()
        if any(phrase in page_evidence_lower for phrase in _HUMAN_REQUIRED_PHRASES):
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

        # ── Structural completion: the field-progress tracker ─────────────
        # status_tracker keeps one tracker (fed by read_form and typed-field
        # readback) keyed to the current step's task signature. When every
        # required field is captured, the step is complete; no prose needed.
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
                    "reasoning_log": [verification_log],
                },
                made_progress=True,
            )

        mission_status = self._clip_text(state.get("mission_status") or "", 2200)

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

        site_notes = load_site_notes(current_url)
        site_notes_block = (
            f"\nSITE_NOTES (completion semantics specific to the current site):\n{site_notes}\n"
            if site_notes
            else ""
        )
        verified_display = "unknown" if event_verified is None else str(event_verified)
        fp_display = (
            f"{fp_done}/{fp_required} required fields captured"
            if fp_required > 0
            else "not tracking fields for this step"
        )

        context = f"""
MAIN_GOAL: {mission_goal}

PLAN_POSITION: step {current_step + 1} of {step_count or "?"}{" (this is the FINAL step)" if is_last_step else ""}

PLAN_STEP (current): {current_task}
{hitl_note}
STRUCTURAL_SIGNALS (measured, prefer these over prose):
- action_verified_by_readback: {verified_display}
- url_changed_since_previous_action: {url_changed}
- page_content_changed_since_previous_action: {dom_changed}
- extracted_content_present: {extracted_present}
- field_progress: {fp_display}

EXECUTION_OUTPUT (action, args, status, message) and AFTER_STATE (page content after the action) from the Execution Agent:
{self._clip_text(last_execution, 2200)}

RECENT_EXECUTION_HISTORY (last few executor logs):
{recent_executor_history}

CURRENT_URL (after action): {current_url}

MISSION_STATUS:
{mission_status}
{site_notes_block}
Use the EXECUTION_OUTPUT and especially AFTER_STATE (page content) as evidence. If the page content or action result shows the step was satisfied (e.g. the right page loaded, the target was clicked, or the required information is visible), set verdict=success and step_complete=true. Do not mark failure with "insufficient_evidence" if AFTER_STATE is present and supports success.
A successful action that did not finish the whole step is verdict=success with step_complete=false.
goal_complete=true requires PLAN_POSITION to be the final step AND the overall MAIN_GOAL to be visibly achieved.
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
            # Match on the structured view: the raw entry carries AFTER_STATE,
            # where the word "success" can appear in ordinary page copy.
            step_complete = "status: success" in (last_execution_structured or "").lower()
            goal_complete = step_complete and is_last_step
            needs_fallback = not step_complete
            next_step_attempts = 0 if step_complete else int(state.get("step_attempts", 0)) + 1
            verification_log = f"[Verifier] LLM failed: {err}; step_complete={step_complete}\n[Verifier] Handoff: {'fallback' if needs_fallback else 'orchestration'}"
        else:
            step_complete = result.step_complete
            goal_complete = result.goal_complete
            needs_fallback = result.handoff == "fallback"

            # Structural guard: an authentication step is not finished while the
            # page is still asking for credentials.
            #
            # Observed failure: on "Log in to MyUCF using saved credentials", the
            # model returned step_complete=True after merely *arriving* at the
            # identity provider's sign-in form. The orchestrator advanced to
            # "go to the grades section", which then could not proceed, and the run
            # ended asking the user to log in by hand. This judges the objective
            # from page evidence rather than trusting the action's own success.
            if step_complete and self._credentials_still_requested(state, last_execution):
                step_complete = False
                goal_complete = False
                needs_fallback = False
                result_message_suffix = (
                    " [guard: credential fields still present, so the login step is not complete]"
                )
            else:
                result_message_suffix = ""
            # Only count "attempts" for automated retries. If we're handing off to fallback
            # due to a hard block (CAPTCHA/2FA/human action), do not burn the safety budget.
            error_type = (result.error_type or "").strip().lower()
            verdict_is_success = (result.verdict or "").strip().lower() == "success"
            if step_complete:
                next_step_attempts = 0
            elif needs_fallback and error_type == "blocked":
                next_step_attempts = 0
            elif verdict_is_success:
                # verdict=success with step_complete=False means progress
                # (e.g. typing credentials during multi-step login). Don't
                # burn the safety budget on forward progress.
                next_step_attempts = int(state.get("step_attempts", 0))
            else:
                next_step_attempts = int(state.get("step_attempts", 0)) + 1
            made_progress = made_progress or (verdict_is_success and not needs_fallback)
            verification_log = (
                f"[Verifier] Verdict: {result.verdict}\n"
                f"[Verifier] Step Complete: {step_complete}\n"
                f"[Verifier] Goal Complete: {goal_complete}\n"
                f"[Verifier] Message: {result.message}{result_message_suffix}\n"
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
            made_progress=made_progress,
        )

    # ── page-delta evidence ────────────────────────────────────────────────

    @staticmethod
    def _split_dom_cache_entry(entry: str) -> tuple[str, str]:
        """dom_cache entries are 'URL: {url}\\n\\n{page text}'."""
        text = (entry or "").strip()
        if text.lower().startswith("url:"):
            head, _, rest = text.partition("\n")
            return head[4:].strip(), rest.strip()
        return "", text

    @classmethod
    def _page_delta(cls, state: ProjectState) -> tuple[bool, bool]:
        """(url_changed, content_changed) between the last two page snapshots.

        Conservative on missing evidence: with fewer than two snapshots both
        deltas are False, so a fresh run never counts a no-op as progress.
        """
        cache = state.get("dom_cache") or []
        if len(cache) < 2:
            return False, False
        last_url, last_text = cls._split_dom_cache_entry(cache[-1])
        prev_url, prev_text = cls._split_dom_cache_entry(cache[-2])
        url_changed = bool(last_url and prev_url and last_url != prev_url)

        last_norm = re.sub(r"\s+", " ", last_text.lower()).strip()
        prev_norm = re.sub(r"\s+", " ", prev_text.lower()).strip()
        if not last_norm or not prev_norm:
            return url_changed, False
        if last_norm == prev_norm:
            return url_changed, False
        last_tokens = set(last_norm.split())
        prev_tokens = set(prev_norm.split())
        if not last_tokens or not prev_tokens:
            return url_changed, False
        overlap = len(last_tokens & prev_tokens)
        baseline = max(min(len(last_tokens), len(prev_tokens)), 1)
        return url_changed, (overlap / baseline) < 0.93

    # A password field in the post-action snapshot is the strongest available
    # signal that authentication has not finished. Deliberately not a list of
    # identity-provider domains: those go stale and only cover known vendors.
    _CREDENTIAL_FIELD_MARKERS = (
        '[role="textbox"] "password"',
        '[role="textbox"] "enter the password',
        'label=password',
        'placeholder=password',
        'type=password',
        '"password"',
    )

    @classmethod
    def _credentials_still_requested(cls, state: ProjectState, last_execution: str) -> bool:
        """True when an authentication step still has credential fields on screen.

        Only applies to steps whose intent is authentication, so an ordinary form
        that happens to contain a password field (registration, say) is unaffected
        once its own step objective is met.
        """
        step_intent = (state.get("step_intent") or "").strip().lower()
        task = (state.get("current_task") or "").lower()
        # `[\s-]*` so hyphenated spellings ("sign-in", "log-in") also match.
        looks_like_login = step_intent == "authenticate" or bool(
            re.search(r"\blog[\s-]*in\b|\bsign[\s-]*in\b|\bauthenticat", task)
        )
        if not looks_like_login:
            return False

        after_state = ""
        marker = "AFTER_STATE"
        if marker in (last_execution or ""):
            after_state = last_execution.split(marker, 1)[1].lower()
        if not after_state:
            # No page evidence to judge from; do not override the model.
            return False

        return any(m in after_state for m in cls._CREDENTIAL_FIELD_MARKERS)

    @staticmethod
    def _clip_text(value: str, max_chars: int) -> str:
        text = (value or "").strip()
        if max_chars <= 0:
            return ""
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n... [truncated]"

    @staticmethod
    def _normalize_task_signature(task: str, recovery_context: dict | None = None) -> str:
        rc = recovery_context if isinstance(recovery_context, dict) else {}
        base = (rc.get("base_task") or "").strip()
        if base:
            return base.lower()
        text = (task or "").strip()
        if not text:
            return ""
        # Legacy runs may still carry bracket markers in current_task.
        text = re.sub(r"\s*\[Recovery Hint:.*$", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s*\[Then continue objective:.*$", "", text, flags=re.IGNORECASE).strip()
        return text.lower()

    def _field_progress_step_complete(self, state: ProjectState, current_task: str) -> tuple[bool, int, int]:
        signals = state.get("status_signals") or {}
        progress = signals.get("field_progress") if isinstance(signals.get("field_progress"), dict) else None
        if not progress:
            return False, 0, 0
        rc = state.get("recovery_context")
        task_sig = self._normalize_task_signature(
            current_task, rc if isinstance(rc, dict) else None
        )
        if not task_sig or progress.get("task_signature") != task_sig:
            return False, 0, 0
        required = int(progress.get("required_count") or 0)
        completed = list(progress.get("completed_fields") or [])
        done = len(completed)
        if required <= 0:
            return False, done, required
        return done >= required, done, required
