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

_LOGIN_KEYWORDS = (
    "log in", "login", "sign in", "sign-in", "authenticate",
    "credential", "password", "username",
)


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

    # ── HITL history ───────────────────────────────────────────────────
    hitl_events: list[dict] = signals.get("hitl_events") or []
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


def _update_executor(signals: dict, state: dict, result: dict) -> None:
    log_entries = result.get("reasoning_log") or []
    last_entry = log_entries[-1] if log_entries else ""

    action_type = _extract(last_entry, r"\[Executor\] Action:\s*(\S+)")
    action_status = _extract(last_entry, r"\[Executor\] Status:\s*(\S+)")
    action_args = _extract(last_entry, r"\[Executor\] Args:\s*(.+?)(?:\n|$)")
    action_msg = _extract(last_entry, r"\[Executor\] Message:\s*(.+?)(?:\n|$)")

    # Derive a human-readable target from args
    target = action_args or ""
    # Trim verbose AFTER_STATE from message
    if action_msg and "AFTER_STATE" in action_msg:
        action_msg = action_msg[: action_msg.index("AFTER_STATE")].strip()

    signals["last_action"] = {
        "type": action_type or "unknown",
        "target": target[:120],
        "status": action_status or "unknown",
        "message": (action_msg or "")[:200],
    }

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


def _update_fallback(signals: dict, state: dict, result: dict) -> None:
    log_entries = result.get("reasoning_log") or []
    last_entry = log_entries[-1] if log_entries else ""

    diagnosis = _extract(last_entry, r"\[Fallback\] Diagnosis:\s*(.+?)(?:\n|$)") or ""
    update_type = _extract(last_entry, r"\[Fallback\] Update Type:\s*(\S+)")

    if update_type == "request_human_action":
        signals["blocking_issue"] = diagnosis[:200] or "Human action required."
    elif update_type == "revise_step":
        signals["blocking_issue"] = None
        signals["situation"] = f"Fallback revised step: {diagnosis[:200]}"


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
        signals["hitl_events"] = hitl_events
        signals["blocking_issue"] = None

        # MFA completed
        if signals.get("login_phase") == "mfa_pending":
            signals["login_phase"] = "completed"


def _extract(text: str, pattern: str) -> str | None:
    m = re.search(pattern, text or "", re.IGNORECASE)
    return m.group(1).strip() if m else None
