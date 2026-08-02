"""
Executor capability vocabulary and plan-step normalization.

Planner emits free-text steps; the executor only supports a fixed action set.
normalize_plan_steps rewrites common unsupported phrases before execution.
"""

from __future__ import annotations

import re
from typing import List, Tuple

# Primitive actions the executor / dispatch layer can perform (reference set).
EXECUTOR_CAPABILITIES = frozenset(
    {
        "navigate",
        "click",
        "fill",
        "select_option",
        "set_checkbox",
        "upload_file",
        "wait_for",
        "read_form",
        "read_page",
        "scroll_to",
        "list_tabs",
        "switch_tab",
        "close_tab",
        "go_back",
        # Legacy, target-free. Still dispatched, but `fill` and `wait_for` are preferred.
        "type",
        "search",
        "scroll",
        "press_key",
        "wait",
        "extract_content",
    }
)

# Map unsupported natural-language phrases (substring match, longest first) to a short rewrite hint.
#
# The upload rules used to rewrite "upload a file" into "click the file input and
# use the system file chooser when prompted", which nothing implemented, so a plan
# step was rewritten into an instruction the executor could never carry out.
# Uploads, dropdowns and checkboxes are now real primitives and are no longer
# rewritten away.
_CAPABILITY_REWRITE_RULES: List[Tuple[str, str]] = [
    ("copy to clipboard", "Extract the needed text or value using extract_content (clipboard is not available)."),
    ("to clipboard", "using extract_content instead of clipboard"),
    ("clipboard", "using extract_content instead of clipboard"),
    ("copy ", "extract the relevant content with extract_content rather than copy; "),
    (" right click ", "click the target, then use context-appropriate follow-up actions; "),
    ("right-click", "click the target, then use context-appropriate follow-up actions; "),
    ("hover ", "click to focus the element if needed; "),
    ("drag and drop", "use click and type interactions to achieve the same outcome; "),
    ("drag ", "use click interactions to reposition or select; "),
    ("download ", "navigate or click the download control, then use extract_content if you need the file text; "),
    ("paste ", "type the intended content into the focused field; "),
    ("select all", "focus the field and use press_key or type as appropriate; "),
    ("screenshot", "use extract_content to capture visible page text; "),
    ("take a screenshot", "use extract_content to capture visible page text; "),
    ("print ", "use extract_content to gather printable content; "),
    ("save as", "use extract_content or navigate to persist content as needed; "),
]


def normalize_plan_steps(steps: List[str]) -> Tuple[List[str], List[str]]:
    """
    Rewrite plan steps that reference unsupported capabilities.

    Returns:
        (normalized_steps, human-readable notes for reasoning_log)
    """
    out_steps: List[str] = []
    notes: List[str] = []
    for raw in steps or []:
        step = raw if isinstance(raw, str) else str(raw)
        new_step, step_notes = _normalize_one_step(step)
        out_steps.append(new_step)
        notes.extend(step_notes)
    return out_steps, notes


def _normalize_one_step(step: str) -> Tuple[str, List[str]]:
    if not (step or "").strip():
        return step, []
    applied: List[str] = []
    new_step = step
    lower = new_step.lower()

    for phrase, replacement in sorted(_CAPABILITY_REWRITE_RULES, key=lambda x: -len(x[0])):
        if phrase in lower:
            applied.append(f"{phrase!r} -> {replacement.strip()}")
            pattern = re.compile(re.escape(phrase), re.IGNORECASE)
            new_step = pattern.sub(replacement, new_step, count=1)
            lower = new_step.lower()

    if not applied:
        return step, []
    summary = "; ".join(applied[:5])
    if len(applied) > 5:
        summary += "; ..."
    return new_step, [f"Normalized step for executor capabilities: {summary}"]
