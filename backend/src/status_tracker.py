"""
Mission Status Tracker — a living-document approach to shared agent context.

Maintains a markdown status page in state["mission_status"] that every agent
can read.  Deterministic fields (plan progress, last action, URL) are derived
from raw state; narrative fields (situation summary, blocking issues) are
recycled from existing agent outputs so no extra LLM calls are needed.

Usage in main.py:
    wrapped = StatusTracker.wrap(agent_callable, "execution")
    workflow.add_node("execution", wrapped)

Each agent then reads state["mission_status"] for a concise, structured
summary of where the mission stands.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from schema import last_execution_event_to_executor_log

_LOGIN_KEYWORDS = (
    "log in", "login", "sign in", "sign-in", "authenticate",
    "credential", "password", "username",
)

_FIELD_ENTRY_KEYWORDS = (
    "fill", "enter", "type", "populate", "write", "draft", "answer",
    "provide", "input", "complete", "form", "survey", "question", "field", "box",
)

_FINALIZATION_KEYWORDS = (
    "send", "submit", "review", "confirm", "finish", "finalize",
)

_MAX_HITL_EVENTS = 10


def _type_event_haystack(event: dict[str, Any]) -> str:
    """Lowercase string from structured type() target metadata + args (for slot matching)."""
    args = event.get("args") if isinstance(event.get("args"), dict) else {}
    parts = [
        str(args.get("target_description") or ""),
        str(args.get("target_name") or ""),
        str(args.get("target_role") or ""),
        str(args.get("text") or ""),
    ]
    return " ".join(parts).lower()


def _classify_compose_slot_from_type_event(event: dict[str, Any]) -> str | None:
    """
    Map a successful type event to a generic compose slot using target metadata.
    Returns None if the event is not a typed success or lacks target metadata (use legacy log heuristics).
    """
    if (event.get("action") or "").strip().lower() != "type":
        return None
    if str(event.get("status") or "").lower() != "success":
        return None
    args = event.get("args") if isinstance(event.get("args"), dict) else {}
    if not any(
        str(args.get(k) or "").strip()
        for k in ("target_description", "target_name", "target_role")
    ):
        return None

    h = _type_event_haystack(event)
    text = (args.get("text") or "").strip()
    has_at = "@" in text

    def hits(markers: tuple[str, ...]) -> bool:
        return any(m in h for m in markers)

    # Generic markers (not provider-specific URLs).
    recipient_markers = (
        "label=to",
        ", to,",
        "name=to",
        "recipient",
        "add recipients",
        "search my contacts",
        "search for email",
        "placeholder=to",
    )
    subject_markers = (
        "subject",
        "title",
        "add a subject",
        "heading",
    )
    body_markers = (
        "message body",
        "messagebody",
        "label=message",
        "placeholder=message",
    )

    rec = hits(recipient_markers)
    sub = hits(subject_markers)
    bod = hits(body_markers)

    if rec:
        return "recipient"
    if sub:
        return "subject"
    if bod:
        return "body"
    if "contenteditable=true" in h and not rec and not sub:
        return "body"
    if has_at:
        return "recipient"
    if len(text) >= 50:
        return "body"
    return None


# ── public helpers ─────────────────────────────────────────────────────


def wrap(agent_callable: Callable, node_name: str) -> Callable:
    """Return a node function that runs the agent, then refreshes the status."""

    # Executor is async; the others are sync.  We need to handle both.
    if node_name == "execution":
        async def _async_wrapped(state: dict) -> dict:
            result = await agent_callable(state)
            _post_update(state, node_name, result)
            result["mission_status"] = build(state, overlay=result)
            return result
        return _async_wrapped

    def _sync_wrapped(state: dict) -> dict:
        result = agent_callable(state)
        _post_update(state, node_name, result)
        result["mission_status"] = build(state, overlay=result)
        return result
    return _sync_wrapped


def build(state: dict, *, overlay: dict | None = None) -> str:
    """Render the full status markdown from current state (+ an optional overlay
    of fields that were just produced but haven't merged yet)."""

    def _get(key: str, default: Any = None):
        if overlay and key in overlay:
            return overlay[key]
        return state.get(key, default)

    signals = _get("status_signals") or {}
    plan = _get("current_plan") or []
    step_idx = _get("current_step_index", 0)
    task = _get("current_task", "")
    url = _get("current_url", "")
    tx = _get("number_of_transactions", 0)

    # ── Objective ──────────────────────────────────────────────────────
    messages = state.get("messages") or []
    objective = ""
    if messages:
        first = messages[0]
        if isinstance(first, dict):
            objective = first.get("content", "")
        elif hasattr(first, "content"):
            objective = first.content
    objective = objective.replace("USER REQUEST: ", "").strip() or "(not set)"
    objective = objective[:500] + ("..." if len(objective) > 500 else "")

    # ── Plan progress ──────────────────────────────────────────────────
    plan_lines: list[str] = []
    completed_steps: set[int] = set(signals.get("completed_steps", []))
    for i, step_text in enumerate(plan):
        if i in completed_steps:
            mark = "[x]"
        elif i == step_idx:
            mark = "[~]"
        else:
            mark = "[ ]"
        arrow = " ← CURRENT" if i == step_idx else ""
        plan_lines.append(f"- {mark} {i + 1}. {step_text}{arrow}")
    plan_section = "\n".join(plan_lines) if plan_lines else "(no plan yet)"

    # ── Last action ────────────────────────────────────────────────────
    last = signals.get("last_action") or {}
    if last:
        action_line = (
            f"- **Action**: {last.get('type', '?')} → "
            f"{last.get('target', '')} ({last.get('status', '?')})"
        )
        msg_line = f"- **Detail**: {last.get('message', '')}"
        last_action_section = f"{action_line}\n{msg_line}"
    else:
        last_action_section = "(none yet)"

    # ── Situation (from last verifier or fallback message) ─────────────
    situation = signals.get("situation", "(awaiting first action)")

    # ── Blocking issues ────────────────────────────────────────────────
    blocking = signals.get("blocking_issue") or "None."

    # ── Login phase ────────────────────────────────────────────────────
    login_phase = signals.get("login_phase", "not_started")

    # ── Compose fields ─────────────────────────────────────────────────
    compose_fields = signals.get("compose_fields") or {
        "recipient": False,
        "subject": False,
        "body": False,
    }
    compose_draft = signals.get("compose_draft") or {}
    compose_section = (
        f"- recipient: {'done' if compose_fields.get('recipient') else 'pending'}\n"
        f"- subject: {'done' if compose_fields.get('subject') else 'pending'}\n"
        f"- body: {'done' if compose_fields.get('body') else 'pending'}"
    )
    draft_subject = (compose_draft.get("subject") or "").strip()
    draft_body = (compose_draft.get("body") or "").strip()
    if draft_subject or draft_body:
        body_preview = draft_body[:220] + ("..." if len(draft_body) > 220 else "")
        compose_draft_section = (
            f"- subject: {draft_subject or '(not captured)'}\n"
            f"- body preview: {body_preview or '(not captured)'}"
        )
    else:
        compose_draft_section = "(none captured yet)"

    # ── Generic field progress ───────────────────────────────────────
    field_progress = signals.get("field_progress") or {}
    required_count = int(field_progress.get("required_count") or 0)
    completed_fields = list(field_progress.get("completed_fields") or [])
    completed_count = len(completed_fields)
    if required_count > 0:
        missing_count = max(required_count - completed_count, 0)
        tracked = ", ".join(completed_fields[:8]) or "none"
        field_progress_section = (
            f"- required: {required_count}\n"
            f"- completed: {min(completed_count, required_count)}\n"
            f"- missing: {missing_count}\n"
            f"- tracked fields: {tracked}"
        )
    else:
        field_progress_section = "(not tracking field-by-field completion for current step)"

    # ── HITL history ───────────────────────────────────────────────────
    hitl_events: list[dict] = (signals.get("hitl_events") or [])[-_MAX_HITL_EVENTS:]
    if hitl_events:
        hitl_lines = []
        for ev in hitl_events:
            hitl_lines.append(
                f"- Tx {ev.get('transaction', '?')}: "
                f"{ev.get('reason', '?')} → user replied \"{ev.get('reply', '?')}\""
            )
        hitl_section = "\n".join(hitl_lines)
    else:
        hitl_section = "(none)"

    return f"""# Mission Status

## Objective
{objective}

## Plan Progress
{plan_section}

## Current Situation
{situation}

## Last Action
{last_action_section}
- **URL**: {url}

## Login Phase
{login_phase}

## Compose Fields
{compose_section}

## Compose Draft
{compose_draft_section}

## Field Progress
{field_progress_section}

## Blocking Issues
{blocking}

## HITL History
{hitl_section}

## Stats
- Transactions: {tx}
- Current step: {step_idx + 1}/{len(plan) if plan else '?'}
- Current task: {task}
"""


# ── internal update helpers ────────────────────────────────────────────


def _post_update(state: dict, node_name: str, result: dict) -> None:
    """Mutate result["status_signals"] to accumulate structured signals."""

    # Start from current signals (copy to avoid mutating state in-place)
    signals = dict(state.get("status_signals") or {})

    if node_name == "orchestrator":
        _update_orchestrator(signals, state, result)
    elif node_name == "execution":
        _update_executor(signals, state, result)
    elif node_name == "verification":
        _update_verifier(signals, state, result)
    elif node_name == "fallback":
        _update_fallback(signals, state, result)
    elif node_name == "interaction":
        _update_interaction(signals, state, result)

    result["status_signals"] = signals


def _update_orchestrator(signals: dict, state: dict, result: dict) -> None:
    plan = result.get("current_plan") or state.get("current_plan") or []
    step_idx = result.get("current_step_index", state.get("current_step_index", 0))

    # Track completed steps
    completed: list[int] = list(signals.get("completed_steps", []))
    prev_step = state.get("current_step_index", 0)
    if result.get("last_step_complete") or step_idx > prev_step:
        if prev_step not in completed:
            completed.append(prev_step)
    signals["completed_steps"] = completed

    # Clear blocking issue when orchestrator advances
    if step_idx > prev_step:
        signals["blocking_issue"] = None

    # Detect login phase from current task
    task = (result.get("current_task") or state.get("current_task") or "").lower()
    if any(k in task for k in _LOGIN_KEYWORDS):
        if signals.get("login_phase") in (None, "not_started"):
            signals["login_phase"] = "in_progress"
    elif signals.get("login_phase") == "in_progress":
        signals["login_phase"] = "completed"

    # Reset compose field tracker when starting/opening a fresh draft step.
    if any(tok in task for tok in ("new email draft", "open a new email draft", "start a new email draft", "new mail")):
        signals["compose_fields"] = {
            "recipient": False,
            "subject": False,
            "body": False,
        }
        signals["compose_draft"] = {
            "subject": "",
            "body": "",
        }

    # Start/reset generic field progress when the step objective changes.
    current_task = (result.get("current_task") or state.get("current_task") or "").strip()
    rc = result.get("recovery_context")
    if not isinstance(rc, dict):
        rc = state.get("recovery_context")
    task_signature = _normalize_task_signature(
        current_task, rc if isinstance(rc, dict) else None
    )
    existing = signals.get("field_progress") if isinstance(signals.get("field_progress"), dict) else {}
    if _is_field_tracking_task(task_signature):
        required_count = _infer_required_field_count(task_signature)
        if existing.get("task_signature") != task_signature:
            signals["field_progress"] = {
                "task_signature": task_signature,
                "required_count": required_count,
                "completed_fields": [],
                "named_required_fields": _infer_required_field_names(task_signature),
            }
        elif existing:
            existing["required_count"] = max(int(existing.get("required_count") or 0), required_count)
            existing["named_required_fields"] = existing.get("named_required_fields") or _infer_required_field_names(task_signature)
            signals["field_progress"] = existing
    else:
        signals.pop("field_progress", None)


def _update_executor(signals: dict, state: dict, result: dict) -> None:
    log_entries = result.get("reasoning_log") or []
    event = result.get("last_execution_event")
    if isinstance(event, dict) and (event.get("action") or "").strip():
        last_entry = last_execution_event_to_executor_log(event)
    else:
        # DEPRECATED: parse last reasoning_log line; remove once all executor paths emit last_execution_event
        last_entry = log_entries[-1] if log_entries else ""

    action_type = _extract(last_entry, r"\[Executor\] Action:\s*(\S+)")
    action_status = _extract(last_entry, r"\[Executor\] Status:\s*(\S+)")
    action_args = _extract(last_entry, r"\[Executor\] Args:\s*(.+?)(?:\n|$)")
    action_msg = _extract(last_entry, r"\[Executor\] Message:\s*(.+?)(?:\n|$)")
    action_error = _extract(last_entry, r"\[Executor\] Error Type:\s*(\S+)")

    # Derive a human-readable target from args
    target = action_args or ""
    # Trim verbose AFTER_STATE from message
    if action_msg and "AFTER_STATE" in action_msg:
        action_msg = action_msg[: action_msg.index("AFTER_STATE")].strip()

    last_action: dict[str, Any] = {
        "type": action_type or "unknown",
        "target": target[:120],
        "status": action_status or "unknown",
        "message": (action_msg or "")[:200],
    }
    if isinstance(event, dict):
        ev_args = event.get("args")
        if isinstance(ev_args, dict):
            for k in ("target_name", "target_role", "target_description"):
                v = ev_args.get(k)
                if v is not None and str(v).strip():
                    last_action[k] = str(v)[:300]
    signals["last_action"] = last_action

    if (
        (action_status or "").lower() == "failure"
        and (action_error or "").lower() == "tool_limit"
        and "sensitive action requires explicit user confirmation" in (action_msg or "").lower()
    ):
        signals["blocking_issue"] = "Sensitive action confirmation required before proceeding."

    compose_fields = dict(signals.get("compose_fields") or {
        "recipient": False,
        "subject": False,
        "body": False,
    })
    compose_draft = dict(signals.get("compose_draft") or {
        "subject": "",
        "body": "",
    })
    entry_l = (last_entry or "").lower()
    target_l = (target or "").lower()

    # Successful recipient entry or selection.
    if action_status == "success":
        if action_type == "type":
            typed_text = _extract_typed_text(last_entry or "")
            normalized_typed = (typed_text or "").strip()
            structured_slot = (
                _classify_compose_slot_from_type_event(event)
                if isinstance(event, dict)
                else None
            )

            if structured_slot == "recipient":
                compose_fields["recipient"] = True
            elif structured_slot == "subject" and len(normalized_typed) >= 3:
                compose_fields["subject"] = True
                if normalized_typed and not compose_draft.get("subject"):
                    compose_draft["subject"] = normalized_typed[:200]
            elif structured_slot == "body" and normalized_typed:
                compose_fields["body"] = True
                if normalized_typed and not compose_draft.get("body"):
                    compose_draft["body"] = normalized_typed[:1400]
            elif structured_slot is None:
                if "@" in typed_text and any(tok in entry_l for tok in (
                    "label=to",
                    "name=to",
                    "label=recipient",
                    "placeholder=recipient",
                    "search my contacts",
                    "add recipients",
                    "search for email",
                )):
                    compose_fields["recipient"] = True

                if any(tok in entry_l for tok in ("label=subject", "placeholder=add a subject", "name=subject")):
                    if len(typed_text) >= 3:
                        compose_fields["subject"] = True
                        if normalized_typed and not compose_draft.get("subject"):
                            compose_draft["subject"] = normalized_typed[:200]

                recipient_context = any(tok in entry_l for tok in (
                    "label=to",
                    "name=to",
                    "label=recipient",
                    "search my contacts",
                    "add recipients",
                    "search for email",
                ))
                body_context = any(tok in entry_l for tok in (
                    "label=message body",
                    "placeholder=message",
                )) or ("contenteditable=true" in entry_l and not recipient_context)
                if body_context and bool((typed_text or "").strip()):
                    compose_fields["body"] = True
                    if normalized_typed and not compose_draft.get("body"):
                        compose_draft["body"] = normalized_typed[:1400]

            # Generic field-progress tracking for any multi-field step.
            field_progress = signals.get("field_progress") if isinstance(signals.get("field_progress"), dict) else None
            _rc = state.get("recovery_context")
            task_signature = _normalize_task_signature(
                (state.get("current_task") or "").strip(),
                _rc if isinstance(_rc, dict) else None,
            )
            if field_progress and field_progress.get("task_signature") == task_signature:
                completed = list(field_progress.get("completed_fields") or [])
                field_id = _extract_field_identifier(last_entry or "")
                required_count = int(field_progress.get("required_count") or 0)
                if not field_id and typed_text.strip():
                    # For multi-field steps, avoid synthetic per-typing IDs that can
                    # falsely inflate completion; only allow generic fallback on
                    # single-field objectives.
                    if required_count <= 1 and not completed:
                        field_id = "typed:generic"

                if field_id and field_id not in completed:
                    completed.append(field_id)
                    cap = max(required_count, 20) if required_count > 0 else 20
                    if len(completed) > cap:
                        completed = completed[-cap:]
                    field_progress["completed_fields"] = completed
                    signals["field_progress"] = field_progress

        if action_type == "click" and "role=option" in target_l and "@" in target_l:
            compose_fields["recipient"] = True

    signals["compose_fields"] = compose_fields
    signals["compose_draft"] = compose_draft

    # Update login phase based on executor actions
    lp = signals.get("login_phase", "not_started")
    if lp == "in_progress" and action_type == "type" and action_status == "success":
        signals["login_phase"] = "credentials_entering"
    if lp in ("in_progress", "credentials_entering"):
        if action_type == "click" and action_status == "success":
            target_l = target.lower()
            if any(k in target_l for k in ("next", "submit", "sign in", "log in")):
                signals["login_phase"] = "submitted"


def _update_verifier(signals: dict, state: dict, result: dict) -> None:
    log_entries = result.get("reasoning_log") or []
    last_entry = log_entries[-1] if log_entries else ""

    message = _extract(last_entry, r"\[Verifier\] Message:\s*(.+?)(?:\n|$)") or ""
    verdict = _extract(last_entry, r"\[Verifier\] Verdict:\s*(\S+)")

    signals["situation"] = message[:300] if message else signals.get("situation", "")

    # Clear blocking issue on success
    if verdict == "success":
        signals["blocking_issue"] = None

    # Detect MFA
    msg_l = message.lower()
    if any(k in msg_l for k in ("multi-factor", "mfa", "2fa", "two-factor", "two-step")):
        signals["login_phase"] = "mfa_pending"

    compose_fields = dict(signals.get("compose_fields") or {
        "recipient": False,
        "subject": False,
        "body": False,
    })
    if "recipient entry appears confirmed" in msg_l:
        compose_fields["recipient"] = True
    if "subject and message body appear populated" in msg_l:
        compose_fields["subject"] = True
        compose_fields["body"] = True
    signals["compose_fields"] = compose_fields

    # Allow verifier messages to finalize generic field-progress state.
    field_progress = signals.get("field_progress") if isinstance(signals.get("field_progress"), dict) else None
    if field_progress and "field-entry step complete" in msg_l:
        required_count = int(field_progress.get("required_count") or 0)
        completed = list(field_progress.get("completed_fields") or [])
        while required_count > 0 and len(completed) < required_count:
            completed.append(f"verified:{len(completed) + 1}")
        field_progress["completed_fields"] = completed
        signals["field_progress"] = field_progress


def _update_fallback(signals: dict, state: dict, result: dict) -> None:
    log_entries = result.get("reasoning_log") or []
    last_entry = log_entries[-1] if log_entries else ""

    diagnosis = _extract(last_entry, r"\[Fallback\] Diagnosis:\s*(.+?)(?:\n|$)") or ""
    update_type = _extract(last_entry, r"\[Fallback\] Update Type:\s*(\S+)")
    requested_context = [str(item).strip() for item in (result.get("requested_context") or []) if str(item).strip()]

    if update_type == "request_human_action":
        signals["blocking_issue"] = diagnosis[:200] or "Human action required."
    elif update_type == "request_context":
        if requested_context:
            signals["blocking_issue"] = "Need user context: " + ", ".join(requested_context[:3])
        else:
            signals["blocking_issue"] = diagnosis[:200] or "Additional user context required."
    elif update_type == "revise_step":
        signals["blocking_issue"] = None
        signals["situation"] = f"Fallback revised step: {diagnosis[:200]}"
    elif update_type == "abort":
        signals["blocking_issue"] = diagnosis[:200] or "Mission aborted by fallback."


def _update_interaction(signals: dict, state: dict, result: dict) -> None:
    log_entries = result.get("reasoning_log") or []
    last_entry = log_entries[-1] if log_entries else ""

    reply = _extract(last_entry, r"\[Interaction\] User replied:\s*(.+?)(?:\n|$)")
    if reply:
        tx = state.get("number_of_transactions", 0)
        hitl_events = list(signals.get("hitl_events") or [])
        reason = signals.get("blocking_issue") or "unknown"
        hitl_events.append({
            "reason": reason[:100],
            "reply": reply[:100],
            "transaction": tx,
        })
        signals["hitl_events"] = hitl_events[-_MAX_HITL_EVENTS:]
        signals["blocking_issue"] = None

        # MFA completed
        if signals.get("login_phase") == "mfa_pending":
            signals["login_phase"] = "completed"


def _extract(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text or "", re.IGNORECASE)
    return m.group(1).strip() if m else None


def _normalize_task_signature(task: str, recovery_context: dict | None = None) -> str:
    rc = recovery_context if isinstance(recovery_context, dict) else {}
    base = (rc.get("base_task") or "").strip()
    if base:
        return base.lower()
    # DEPRECATED: strip recovery markers from current_task text
    text = (task or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s*\[Recovery Hint:.*$", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*\[Then continue objective:.*$", "", text, flags=re.IGNORECASE).strip()
    return text.lower()


def _is_field_tracking_task(task_signature: str) -> bool:
    if not task_signature:
        return False
    if any(tok in task_signature for tok in _LOGIN_KEYWORDS):
        return False
    if any(tok in task_signature for tok in _FINALIZATION_KEYWORDS):
        return False
    return any(tok in task_signature for tok in _FIELD_ENTRY_KEYWORDS)


def _infer_required_field_names(task_signature: str) -> list[str]:
    text = task_signature or ""
    names: list[str] = []

    # Generic compose-writing inference: when the step asks to write/draft an email
    # but does not explicitly enumerate fields, track both subject and body.
    is_compose_write = (
        any(tok in text for tok in ("email", "mail", "message"))
        and any(tok in text for tok in ("write", "draft", "compose"))
        and not any(tok in text for tok in ("recipient", "to field", "to:", "send", "review", "confirm"))
    )
    if is_compose_write:
        names.extend(["subject", "body"])

    keyword_map = (
        ("recipient", ("recipient", "to field", "to:")),
        ("subject", ("subject", "subject line")),
        ("body", ("message body", "email body", "body", "message content", "content")),
        ("name", ("full name", "name")),
        ("email", ("email", "e-mail")),
        ("phone", ("phone", "telephone")),
        ("address", ("address",)),
        ("city", ("city",)),
        ("state", ("state", "province")),
        ("zip", ("zip", "postal code")),
        ("country", ("country",)),
    )
    for canonical, variants in keyword_map:
        if any(v in text for v in variants):
            if canonical not in names:
                names.append(canonical)
    return names


def _infer_required_field_count(task_signature: str) -> int:
    text = task_signature or ""

    count_match = re.search(
        r"\b(\d{1,3})\b\s+(?:different\s+)?(?:boxes|fields|inputs|textboxes|questions|answers)\b",
        text,
        re.IGNORECASE,
    )
    if count_match:
        try:
            parsed = int(count_match.group(1))
            if parsed > 0:
                return parsed
        except Exception:
            pass

    named = _infer_required_field_names(text)
    if named:
        return len(named)

    return 1 if _is_field_tracking_task(text) else 0


def _extract_typed_text(entry: str) -> str:
    args_match = re.search(r"\[Executor\] Args:\s*.*text=([^\n]+)", entry or "", re.IGNORECASE)
    if not args_match:
        return ""
    return args_match.group(1).strip().strip("\"'")


def _extract_field_identifier(entry: str) -> str:
    text = (entry or "").lower()
    patterns = (
        r"label=([^,\n]+)",
        r"placeholder=([^,\n]+)",
        r"name=([^,\n]+)",
        r"id=([^,\n]+)",
    )
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            value = (m.group(1) or "").strip().strip("\"'")
            if value:
                return value
    return ""
