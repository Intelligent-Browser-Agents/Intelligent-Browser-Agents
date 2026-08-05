"""
Fallback Agent
Uses an LLM to diagnose failures and propose a revised step or recovery.

Recoveries mutate the plan for real: `revise_step` rewrites the current plan
step and `insert_step_before` inserts a genuine prerequisite step, so the
orchestrator's ordinary advance logic carries the run forward. The old
mechanism — decorating current_task with `[Recovery Hint: ...]` /
`[Then continue objective: ...]` markers while the plan stayed frozen — is gone.
"""

import re

from langchain_core.messages import SystemMessage, HumanMessage

from state import ProjectState, get_mission_goal
from schema import FallbackStrategy, infer_step_intent
from models import Models
from prompt_loader import get_fallback_prompt, load_site_notes


class Fallback:
    """
    LLM-based fallback: given the failed step and execution/verification logs,
    the model decides how to recover (revise step, insert step, request context, or abort).
    """

    # After this many failed attempts on one step, a detected action loop
    # escalates from another step revision to a full replan from live page
    # state. Bounded by max_step_attempts and the transaction budget.
    _REPLAN_ATTEMPT_THRESHOLD = 3

    def __init__(self):
        self.llm = Models.fallback(FallbackStrategy)
        self.prompt = get_fallback_prompt()

    _SCREENSHOT_MAX_DATA_URL_CHARS = 420_000
    _SCREENSHOT_STALE_TRANSACTION_WINDOW = 4

    def __call__(self, state: ProjectState) -> dict:
        current_task = state.get("current_task", "Unknown task")
        rc_in = state.get("recovery_context")
        objective_task = self._base_task(
            current_task, rc_in if isinstance(rc_in, dict) else None
        )
        reasoning_log = state.get("reasoning_log", [])
        user_intent = get_mission_goal(state)
        current_url = state.get("current_url", "")
        dom_cache = state.get("dom_cache") or []
        last_dom_snapshot = dom_cache[-1] if dom_cache else ""
        # Keep the context bounded; dom_cache entries can be large.
        last_dom_snapshot = (last_dom_snapshot or "").strip()[:4500]
        previous_dom_snapshot = dom_cache[-2] if len(dom_cache) >= 2 else ""
        previous_dom_snapshot = (previous_dom_snapshot or "").strip()[:2500]
        popup_signal = self._detect_blocking_popup(
            objective_task=objective_task,
            user_intent=user_intent,
            last_dom_snapshot=last_dom_snapshot,
            previous_dom_snapshot=previous_dom_snapshot,
            reasoning_log=reasoning_log,
        )

        if popup_signal.get("is_blocking", False):
            # A blocking popup is a prerequisite, not a rewording of the step:
            # insert a real dismissal step before the objective so the
            # orchestrator returns to the objective by ordinary advancement.
            popup_hint = self._build_popup_recovery_hint(popup_signal)
            mutation = self._mutate_plan(
                state,
                update_type="insert_step_before",
                new_step_text=popup_hint,
                objective_task=objective_task,
            )
            fallback_log = (
                "[Fallback] Update Type: insert_step_before\n"
                "[Fallback] Diagnosis: Blocking popup/modal likely intercepting interactions.\n"
                "[Fallback] Message to Orchestration: Dismiss the popup first, then continue objective.\n"
                f"[Fallback] Proposed Step: {mutation.get('current_task', popup_hint)}\n"
                f"[Fallback] Popup Signal: {popup_signal.get('reason', 'detected by DOM evidence')}"
            )
            out = {
                "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                "reasoning_log": [fallback_log],
                "needs_fallback": False,
                "step_intent": infer_step_intent(mutation.get("current_task", popup_hint)),
            }
            out.update(mutation)
            return out

        loop_signal = self._detect_repeat_loop(
            reasoning_log=reasoning_log,
            last_dom_snapshot=last_dom_snapshot,
            previous_dom_snapshot=previous_dom_snapshot,
        )

        # Escalate to a full replan when revisions have stopped helping: the
        # executor is looping on the same action and several attempts on this
        # step are already burnt. The orchestrator rebuilds the plan from live
        # page context (plan_status=CREATE with an empty current_plan).
        if (
            loop_signal.get("is_loop", False)
            and int(state.get("step_attempts", 0) or 0) >= self._REPLAN_ATTEMPT_THRESHOLD
            and (state.get("current_plan") or [])
        ):
            fallback_log = (
                "[Fallback] Update Type: replan\n"
                "[Fallback] Diagnosis: Repeated action loop persists after step-level recovery; "
                "the current plan no longer fits the page.\n"
                "[Fallback] Message to Orchestration: Rebuild the plan from the current page state.\n"
                f"[Fallback] Abandoned Step: {objective_task}"
            )
            return {
                "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                "current_plan": [],
                "current_step_index": 0,
                "plan_status": "CREATE",
                "current_task": objective_task,
                "reasoning_log": [fallback_log],
                "needs_fallback": False,
                "recovery_context": None,
                "step_attempts": 0,
                "step_intent": infer_step_intent(objective_task),
            }

        loop_analysis_block = (
            "LOOP_ANALYSIS:\n"
            f"- repeated_action: {loop_signal.get('action') or 'none'}\n"
            f"- repeated_signature_count: {loop_signal.get('repeat_count', 0)}\n"
            f"- dom_unchanged: {loop_signal.get('dom_unchanged', False)}\n"
            f"- loop_detected: {loop_signal.get('is_loop', False)}\n"
            "If loop_detected=true, do NOT propose repeating the same action/target again. "
            "Use DOM evidence to steer to a different concrete tactic."
        )

        last_verification = self._find_latest_log(reasoning_log, "[Verifier]") or "Verification failed."
        last_execution = (
            self._find_latest_log(reasoning_log, "[Executor]")
            or self._find_latest_log(reasoning_log, "[Verifier]")
            or "No execution log."
        )

        screenshot_data_url, screenshot_reasons = self._select_last_resort_screenshot(
            state=state,
            loop_signal=loop_signal,
            last_verification=last_verification,
            last_dom_snapshot=last_dom_snapshot,
        )
        screenshot_block = self._build_screenshot_context_block(
            state=state,
            screenshot_enabled=bool(screenshot_data_url),
            screenshot_reasons=screenshot_reasons,
        )

        mission_status = self._clip_text(state.get("mission_status") or "", 2000)
        site_notes = load_site_notes(current_url)
        site_notes_block = (
            f"SITE_NOTES (guidance specific to the current site):\n{site_notes}\n"
            if site_notes
            else ""
        )
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

{screenshot_block}

{loop_analysis_block}

{site_notes_block}
Diagnose the failure and propose a recovery. Use update_type: revise_step with proposed_step for a single revised instruction; use insert_step_before with insert_step to add a prerequisite; use request_context if user input is needed; use abort only if the goal cannot be continued. If SCREENSHOT_SIGNAL says enabled, use screenshot evidence only as a last-resort tie-breaker for visual blockers/occlusion.
"""

        err = None
        used_multimodal = False
        try:
            if screenshot_data_url:
                strategy: FallbackStrategy = self.llm.invoke(
                    self._build_llm_messages(
                        context=context.strip(),
                        screenshot_data_url=screenshot_data_url,
                    )
                )
                used_multimodal = True
            else:
                strategy = self.llm.invoke(self._build_llm_messages(context=context.strip()))
        except Exception as e:
            err = e
            strategy = None

        if strategy is None and screenshot_data_url:
            # Failsafe: if multimodal invocation fails, retry once as text-only.
            try:
                strategy = self.llm.invoke(self._build_llm_messages(context=context.strip()))
            except Exception as retry_err:
                err = RuntimeError(f"multimodal={err}; text_retry={retry_err}")
                strategy = None

        if strategy is None:
            update_type = "revise_step"
            proposed = objective_task
            needs_human = False
            requested_context = []
            fallback_log = (
                "[Fallback] LLM failed; retrying same step.\n"
                f"[Fallback] Error: {err}\n"
                f"[Fallback] Message to Orchestration: Retry the current step."
            )
        else:
            proposed = (
                (strategy.proposed_step or "").strip()
                or (strategy.insert_step or "").strip()
                or objective_task
            )
            update_type = strategy.update_type

            needs_human = strategy.update_type in {"request_human_action", "request_context"}
            requested_context = [str(item).strip() for item in (strategy.requested_context or []) if str(item).strip()]
            if strategy.update_type == "request_context" and not requested_context:
                requested_context = ["additional context about the missing information"]

            if strategy.update_type == "abort":
                reason = (
                    (strategy.message_to_orchestration or "").strip()
                    or (strategy.diagnosis or "").strip()
                    or "Fallback requested mission abort."
                )
                return {
                    "number_of_transactions": state.get("number_of_transactions", 0) + 1,
                    "reasoning_log": [
                        "[Fallback] Update Type: abort\n"
                        f"[Fallback] Diagnosis: {strategy.diagnosis}\n"
                        f"[Fallback] Message to Orchestration: {strategy.message_to_orchestration}\n"
                        f"[Fallback] Abort Reason: {reason}"
                    ],
                    "needs_fallback": False,
                    "handoff_interaction": True,
                    "is_complete": True,
                    "mission_failed": True,
                    "abort_reason": reason,
                    "current_task": objective_task,
                    "recovery_context": None,
                    "step_intent": infer_step_intent(objective_task),
                }

            fallback_log = (
                f"[Fallback] Update Type: {strategy.update_type}\n"
                f"[Fallback] Diagnosis: {strategy.diagnosis}\n"
                f"[Fallback] Message to Orchestration: {strategy.message_to_orchestration}\n"
                f"[Fallback] Last Verification: {last_verification[:180]}"
            )

        if screenshot_data_url:
            mode = "last_resort_multimodal" if used_multimodal else "last_resort_text_retry"
            fallback_log += (
                "\n"
                f"[Fallback] Screenshot Escalation: {mode}; reasons={', '.join(screenshot_reasons) or 'none'}"
            )

        # Loop steering: a "revision" that just restates the objective while the
        # executor loops on one action would repeat the loop. Force a different
        # tactical direction instead.
        if (
            not needs_human
            and update_type in {"revise_step", "insert_step_before"}
            and loop_signal.get("is_loop", False)
            and proposed.strip().lower() == objective_task.strip().lower()
        ):
            forced_hint = self._build_forced_recovery_hint(loop_signal)
            proposed = f"{objective_task} (Recovery guidance: {forced_hint})"
            update_type = "revise_step"
            fallback_log += (
                "\n[Fallback] Objective Steering: Detected repeated executor action with "
                "little page-state change; forcing a different tactical direction instead "
                "of repeating the same step."
            )

        out = {
            "number_of_transactions": state.get("number_of_transactions", 0) + 1,
            "reasoning_log": [fallback_log],
            "needs_fallback": False,
        }

        if needs_human:
            # No plan mutation while waiting on the user. The objective stays the
            # current task; the proposal travels in recovery_context for context.
            out["current_task"] = objective_task
            out["recovery_context"] = (
                {
                    "base_task": objective_task,
                    "recovery_hint": proposed,
                    "continuation_objective": None,
                }
                if proposed and proposed.strip().lower() != objective_task.strip().lower()
                else None
            )
            out["step_intent"] = infer_step_intent(objective_task)
            out["handoff_interaction"] = True
            out["requested_context"] = requested_context
            # Reset step_attempts so that human-in-the-loop pauses do not trigger
            # the orchestrator safety stop immediately after the user completes
            # the required action.
            out["step_attempts"] = 0
            return out

        # A "revision" that is really a repositioning prerequisite (navigate back,
        # reopen the right surface) becomes a genuine inserted step, so the
        # original objective is reached again by ordinary plan advancement.
        if update_type == "revise_step" and self._looks_like_prerequisite_realign(proposed, objective_task):
            update_type = "insert_step_before"

        mutation = self._mutate_plan(
            state,
            update_type=update_type,
            new_step_text=proposed,
            objective_task=objective_task,
        )
        out.update(mutation)
        out["step_intent"] = infer_step_intent(out.get("current_task") or objective_task)
        fallback_log += f"\n[Fallback] Applied: {update_type} → {out.get('current_task', objective_task)}"
        out["reasoning_log"] = [fallback_log]
        return out

    @staticmethod
    def _mutate_plan(
        state: ProjectState,
        *,
        update_type: str,
        new_step_text: str,
        objective_task: str,
    ) -> dict:
        """Apply a recovery to current_plan and return the state delta.

        insert_step_before inserts a real prerequisite step at the current
        index; revise_step replaces the current step in place. Both record the
        new plan version in plan_history and mark plan_status=UPDATE. When
        there is nothing to change, only current_task is (re)asserted.
        """
        plan = list(state.get("current_plan") or [])
        idx = int(state.get("current_step_index", 0) or 0)
        step_text = (new_step_text or "").strip()

        if not plan or not step_text:
            return {"current_task": step_text or objective_task, "recovery_context": None}

        idx = min(max(idx, 0), len(plan) - 1)

        if update_type == "insert_step_before":
            plan.insert(idx, step_text)
            return {
                "current_plan": plan,
                "plan_history": plan,
                "current_step_index": idx,
                "plan_status": "UPDATE",
                "current_task": step_text,
                "recovery_context": None,
            }

        # revise_step (and anything unrecognized): replace in place.
        original = (plan[idx] or "").strip()
        if step_text.lower() == original.lower():
            return {"current_task": original, "recovery_context": None}
        plan[idx] = step_text
        return {
            "current_plan": plan,
            "plan_history": plan,
            "current_step_index": idx,
            "plan_status": "UPDATE",
            "current_task": step_text,
            # base_task keeps the pre-revision wording as the stable signature so
            # mid-step field progress is not reset by a tactical rewording.
            "recovery_context": {
                "base_task": objective_task or original,
                "recovery_hint": step_text,
                "continuation_objective": None,
            },
        }

    @staticmethod
    def _base_task(task: str, recovery_context: dict | None = None) -> str:
        rc = recovery_context if isinstance(recovery_context, dict) else {}
        base = (rc.get("base_task") or "").strip()
        if base:
            return base
        # DEPRECATED: parse bracket markers in current_task
        text = (task or "").strip()
        for marker in (" [Recovery Hint:", " [Then continue objective:"):
            idx = text.find(marker)
            if idx >= 0:
                return text[:idx].strip()
        return text or "Unknown task"

    @staticmethod
    def _extract_executor_entries(reasoning_log: list) -> list[str]:
        return [
            entry for entry in (reasoning_log or [])
            if isinstance(entry, str) and "[Executor] Action:" in entry
        ]

    @staticmethod
    def _parse_executor_action_signature(entry: str) -> tuple[str, str]:
        text = (entry or "").lower()
        action_match = re.search(r"\[executor\]\s*action:\s*([^\n]+)", text)
        args_match = re.search(r"\[executor\]\s*args:\s*([^\n]+)", text)
        action = action_match.group(1).strip() if action_match else ""
        args = args_match.group(1).strip() if args_match else ""
        args = re.sub(r"\s+", " ", args)
        return action, args

    @staticmethod
    def _dom_snapshots_unchanged(last_dom_snapshot: str, previous_dom_snapshot: str) -> bool:
        last_norm = re.sub(r"\s+", " ", (last_dom_snapshot or "").strip().lower())
        prev_norm = re.sub(r"\s+", " ", (previous_dom_snapshot or "").strip().lower())
        if not last_norm or not prev_norm:
            return False
        if last_norm == prev_norm:
            return True
        last_tokens = set(last_norm.split())
        prev_tokens = set(prev_norm.split())
        if not last_tokens or not prev_tokens:
            return False
        overlap = len(last_tokens & prev_tokens)
        baseline = max(min(len(last_tokens), len(prev_tokens)), 1)
        return (overlap / baseline) >= 0.93

    @classmethod
    def _detect_repeat_loop(
        cls,
        reasoning_log: list,
        last_dom_snapshot: str,
        previous_dom_snapshot: str,
    ) -> dict:
        entries = cls._extract_executor_entries(reasoning_log)
        recent = entries[-4:]
        signatures: list[tuple[str, str]] = [
            cls._parse_executor_action_signature(entry) for entry in recent
        ]
        repeat_count = 1
        anchor = signatures[-1] if signatures else ("", "")
        for signature in reversed(signatures[:-1]):
            if signature == anchor and signature != ("", ""):
                repeat_count += 1
            else:
                break

        dom_unchanged = cls._dom_snapshots_unchanged(last_dom_snapshot, previous_dom_snapshot)
        is_loop = bool(anchor[0]) and (repeat_count >= 3 or (repeat_count >= 2 and dom_unchanged))
        return {
            "is_loop": is_loop,
            "action": anchor[0],
            "args": anchor[1],
            "repeat_count": repeat_count,
            "dom_unchanged": dom_unchanged,
        }

    @staticmethod
    def _looks_like_auth_goal(text: str) -> bool:
        lowered = (text or "").lower()
        tokens = (
            "log in",
            "login",
            "sign in",
            "sign-in",
            "register",
            "create account",
            "authenticate",
            "2fa",
            "mfa",
            "verify identity",
        )
        return any(token in lowered for token in tokens)

    @classmethod
    def _detect_blocking_popup(
        cls,
        objective_task: str,
        user_intent: str,
        last_dom_snapshot: str,
        previous_dom_snapshot: str,
        reasoning_log: list,
    ) -> dict:
        text = (last_dom_snapshot or "").lower()
        if not text:
            return {"is_blocking": False, "reason": ""}

        # If authentication is the actual objective, auth surfaces are not a popup blocker.
        if cls._looks_like_auth_goal(objective_task) or cls._looks_like_auth_goal(user_intent):
            return {"is_blocking": False, "reason": "auth_goal"}

        booking_genius_style = "sign in or register" in text and "save money" in text
        cookie_wall_style = "cookie" in text and ("accept" in text or "reject" in text or "consent" in text)
        popup_markers = (
            "popup",
            "modal",
            "dialog",
            "overlay",
            "subscribe",
            "newsletter",
            "enable notifications",
            "allow notifications",
            "limited-time",
            "special offer",
        )
        has_popup_marker = any(marker in text for marker in popup_markers)

        loop_signal = cls._detect_repeat_loop(
            reasoning_log=reasoning_log,
            last_dom_snapshot=last_dom_snapshot,
            previous_dom_snapshot=previous_dom_snapshot,
        )
        looping = bool(loop_signal.get("is_loop", False))

        if booking_genius_style:
            return {
                "is_blocking": True,
                "reason": "marketing_auth_modal_detected",
                "looping": looping,
            }
        if cookie_wall_style:
            return {
                "is_blocking": True,
                "reason": "cookie_consent_wall_detected",
                "looping": looping,
            }
        if has_popup_marker and looping:
            return {
                "is_blocking": True,
                "reason": "popup_marker_plus_action_loop",
                "looping": looping,
            }
        return {"is_blocking": False, "reason": ""}

    @staticmethod
    def _build_popup_recovery_hint(popup_signal: dict) -> str:
        reason = (popup_signal or {}).get("reason", "")
        if reason == "cookie_consent_wall_detected":
            return (
                "Dismiss the cookie/consent wall first (accept or reject as needed) so the page is interactive again, "
                "then continue the objective."
            )
        return (
            "Close the blocking popup/modal using Close/X/Not now, then continue the objective on the underlying page."
        )

    @staticmethod
    def _build_forced_recovery_hint(loop_signal: dict) -> str:
        action = (loop_signal.get("action") or "").lower()
        args = (loop_signal.get("args") or "").lower()
        if action == "click":
            return (
                "Avoid repeating the same click target. Scroll to reveal alternative controls, "
                "then click a different element that advances this objective."
            )
        if action == "press_key" and "key=tab" in args:
            return (
                "Stop focus-only Tab cycling. Click the intended editable field directly and enter the required value."
            )
        if action == "type":
            return (
                "Do not retype in the same lane. Re-locate the correct editable field and type once, then confirm the selection if required."
            )
        if action == "search":
            return (
                "Use an alternative query or result path from the current page instead of repeating the same search submission."
            )
        return (
            "Avoid repeating the same action sequence. Use current DOM cues to choose an alternative actionable path toward this objective."
        )

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

    @staticmethod
    def _clip_text(value: str, max_chars: int) -> str:
        text = (value or "").strip()
        if max_chars <= 0:
            return ""
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n... [truncated]"

    def _build_llm_messages(self, context: str, screenshot_data_url: str | None = None) -> list:
        if screenshot_data_url:
            return [
                SystemMessage(content=self.prompt),
                HumanMessage(
                    content=[
                        {"type": "text", "text": context},
                        {"type": "image_url", "image_url": {"url": screenshot_data_url}},
                    ]
                ),
            ]
        return [
            SystemMessage(content=self.prompt),
            HumanMessage(content=context),
        ]

    @classmethod
    def _select_last_resort_screenshot(
        cls,
        *,
        state: ProjectState,
        loop_signal: dict,
        last_verification: str,
        last_dom_snapshot: str,
    ) -> tuple[str, list[str]]:
        screenshot_data_url = (state.get("screenshot") or "").strip()
        if not screenshot_data_url.startswith("data:image/"):
            return "", []
        if len(screenshot_data_url) > cls._SCREENSHOT_MAX_DATA_URL_CHARS:
            return "", []

        meta = state.get("screenshot_meta") or {}
        if not isinstance(meta, dict):
            meta = {}
        if not cls._screenshot_is_fresh(meta=meta, state=state):
            return "", []

        reasons: list[str] = []
        step_attempts = int(state.get("step_attempts", 0) or 0)
        stall_cycles = int(state.get("stall_cycles", 0) or 0)
        if step_attempts >= 2:
            reasons.append("high_step_attempts")
        if stall_cycles >= 2:
            reasons.append("stall_cycles")
        if bool(loop_signal.get("is_loop", False)):
            reasons.append("repeat_loop")
        if bool(loop_signal.get("dom_unchanged", False)):
            reasons.append("dom_unchanged")

        verifier_lower = (last_verification or "").lower()
        verifier_tokens = (
            "blocked",
            "insufficient_evidence",
            "unexpected_state",
            "captcha",
            "human action required",
        )
        if any(token in verifier_lower for token in verifier_tokens):
            reasons.append("verifier_block_signal")

        if not (last_dom_snapshot or "").strip():
            reasons.append("dom_missing")
        elif len((last_dom_snapshot or "").strip()) < 220:
            reasons.append("dom_sparse")

        should_escalate = (
            "repeat_loop" in reasons
            or "high_step_attempts" in reasons
            or "stall_cycles" in reasons
            or "verifier_block_signal" in reasons
            or "dom_missing" in reasons
            or ("dom_sparse" in reasons and "dom_unchanged" in reasons)
        )
        if not should_escalate:
            return "", []
        return screenshot_data_url, reasons

    @classmethod
    def _screenshot_is_fresh(cls, *, meta: dict, state: ProjectState) -> bool:
        tx = meta.get("transaction_index")
        step_index = meta.get("step_index")
        try:
            tx_i = int(tx)
        except (TypeError, ValueError):
            return False
        current_tx = int(state.get("number_of_transactions", 0) or 0)
        if (current_tx - tx_i) > cls._SCREENSHOT_STALE_TRANSACTION_WINDOW:
            return False
        try:
            snap_step = int(step_index)
        except (TypeError, ValueError):
            return False
        current_step = int(state.get("current_step_index", 0) or 0)
        return snap_step == current_step

    @staticmethod
    def _build_screenshot_context_block(
        *,
        state: ProjectState,
        screenshot_enabled: bool,
        screenshot_reasons: list[str],
    ) -> str:
        meta = state.get("screenshot_meta") or {}
        tx = meta.get("transaction_index", "unknown") if isinstance(meta, dict) else "unknown"
        if screenshot_enabled:
            return (
                "SCREENSHOT_SIGNAL:\n"
                "- mode: enabled_last_resort\n"
                f"- trigger_reasons: {', '.join(screenshot_reasons)}\n"
                f"- captured_transaction: {tx}\n"
                "- use_policy: use screenshot only to resolve visual ambiguity/occlusion when DOM evidence is insufficient"
            )
        return (
            "SCREENSHOT_SIGNAL:\n"
            "- mode: disabled\n"
            "- use_policy: default to DOM and execution evidence"
        )
