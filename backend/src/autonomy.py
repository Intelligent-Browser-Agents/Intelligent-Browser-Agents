"""
Autonomy policy: which browser actions may run unattended.

This replaces the executor's sensitive-token gate. That gate turned every click
whose label contained "submit" or "confirm" into a human-in-the-loop stop —
incompatible with "apply to jobs automatically" — while a genuinely
irreversible action whose button said "Continue" sailed through.

The policy has three parts:

* a user-chosen level: observe_only, confirm_irreversible (default), or
  autonomous;
* a hard always-confirm list that no level bypasses: moving money, deleting
  accounts or data, and sending messages on the user's behalf;
* per-domain level overrides, e.g. autonomous on a trusted job board while the
  rest of the web stays at confirm_irreversible.

The policy travels in state["autonomy_policy"] as a plain dict so it survives
checkpointing. The executor asks `assess_action(...)` before dispatching and
routes "confirm" decisions through the existing sensitive-action interrupt.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import urlparse

LEVELS = ("observe_only", "confirm_irreversible", "autonomous")
DEFAULT_LEVEL = "confirm_irreversible"

# Actions that only read the page. Safe at every level, including observe_only.
READ_ONLY_ACTIONS = frozenset({
    "read_form", "read_page", "extract_content", "list_tabs", "wait_for",
    "wait", "scroll", "scroll_to", "dom_search", "list_links",
})

# Categories that always require explicit confirmation, at every level.
ALWAYS_CONFIRM_CATEGORIES = ("money_movement", "destructive", "send_on_behalf")

# Category evidence comes from the *target's accessible name*, matched on word
# boundaries. Substring matching is exactly how `name=to` used to match
# "Total" and `name=add` matched "Address".
_CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    (
        "money_movement",
        re.compile(
            r"\b(pay|pay now|purchase|buy|buy now|place (?:your )?order|checkout|"
            r"check out|transfer|wire|send money|donate|subscribe now|"
            r"complete (?:purchase|payment|order)|confirm (?:purchase|payment|order))\b"
        ),
    ),
    (
        "destructive",
        re.compile(
            r"\b(delete|remove|erase|close account|deactivate|cancel subscription|"
            r"unsubscribe|discard draft|empty trash|clear all)\b"
        ),
    ),
    (
        "send_on_behalf",
        re.compile(
            r"\b(send|send now|reply|reply all|forward|post|publish|tweet|share now|"
            r"send message|send email)\b"
        ),
    ),
    (
        # Form/application finalization. Confirmable by level, deliberately NOT
        # on the always-confirm list: submitting a job application is the job.
        "submission",
        re.compile(
            r"\b(submit|submit application|apply now|finish|finalize|"
            r"confirm and submit|complete application|book now|reserve)\b"
        ),
    ),
)

_STATE_CHANGING_ACTIONS = frozenset({
    "click", "fill", "type", "select_option", "set_checkbox", "upload_file",
    "press_key", "navigate", "search", "go_back", "switch_tab", "close_tab",
})


def default_policy() -> dict:
    return {"level": DEFAULT_LEVEL, "domain_overrides": {}}


def load_policy(credentials: Optional[dict] = None, environ: Optional[dict] = None) -> dict:
    """Resolve the run's autonomy policy.

    Precedence: the user's stored policy (arrives inside the credential blob as
    "autonomyPolicy", so it is persisted per user in the encrypted vault), then
    AGENT_AUTONOMY_LEVEL / AGENT_AUTONOMY_DOMAIN_OVERRIDES environment
    variables, then the confirm-irreversible default.
    """
    policy = default_policy()
    env = environ or {}

    level = str(env.get("AGENT_AUTONOMY_LEVEL") or "").strip().lower()
    if level in LEVELS:
        policy["level"] = level
    raw_overrides = env.get("AGENT_AUTONOMY_DOMAIN_OVERRIDES") or ""
    if raw_overrides:
        try:
            parsed = json.loads(raw_overrides)
            if isinstance(parsed, dict):
                policy["domain_overrides"] = {
                    str(k).strip().lower(): str(v).strip().lower()
                    for k, v in parsed.items()
                    if str(v).strip().lower() in LEVELS
                }
        except json.JSONDecodeError:
            pass

    stored = (credentials or {}).get("autonomyPolicy")
    if isinstance(stored, dict):
        stored_level = str(stored.get("level") or "").strip().lower()
        if stored_level in LEVELS:
            policy["level"] = stored_level
        stored_overrides = stored.get("domain_overrides")
        if isinstance(stored_overrides, dict):
            policy["domain_overrides"] = {
                str(k).strip().lower(): str(v).strip().lower()
                for k, v in stored_overrides.items()
                if str(v).strip().lower() in LEVELS
            }
    return policy


def classify_action_category(action: str, args: Optional[dict]) -> Optional[str]:
    """Category of a state-changing action, judged from its target's name."""
    action_l = (action or "").strip().lower()
    args = args if isinstance(args, dict) else {}
    if action_l not in ("click", "press_key"):
        return None
    if action_l == "press_key":
        # Enter in a form field is routine (search boxes, autocomplete commits).
        # Finalization via Enter is caught on the page that follows, where the
        # actual named control gets clicked.
        return None
    name = str(args.get("name") or "").strip().lower()
    if not name:
        return None
    for category, pattern in _CATEGORY_PATTERNS:
        if pattern.search(name):
            return category
    return None


def _level_for_url(policy: dict, url: Optional[str]) -> str:
    level = str((policy or {}).get("level") or DEFAULT_LEVEL).strip().lower()
    if level not in LEVELS:
        level = DEFAULT_LEVEL
    overrides = (policy or {}).get("domain_overrides") or {}
    if not url or not isinstance(overrides, dict) or not overrides:
        return level
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return level
    if not host:
        return level
    for domain, domain_level in overrides.items():
        d = str(domain).strip().lower().lstrip(".")
        if not d or str(domain_level) not in LEVELS:
            continue
        if host == d or host.endswith("." + d):
            return str(domain_level)
    return level


def assess_action(
    action: str,
    args: Optional[dict],
    *,
    policy: Optional[dict] = None,
    url: Optional[str] = None,
) -> dict:
    """Decide whether an action may run unattended.

    Returns {"mode": "allow" | "confirm", "category": str | None, "reason": str}.
    "confirm" means: pause and ask the user through the sensitive-action
    interrupt before executing.
    """
    action_l = (action or "").strip().lower()
    policy = policy if isinstance(policy, dict) else default_policy()
    level = _level_for_url(policy, url)
    category = classify_action_category(action_l, args)

    if category in ALWAYS_CONFIRM_CATEGORIES:
        return {
            "mode": "confirm",
            "category": category,
            "reason": f"{category.replace('_', ' ')} always requires explicit confirmation",
        }

    if action_l in READ_ONLY_ACTIONS or action_l not in _STATE_CHANGING_ACTIONS:
        return {"mode": "allow", "category": category, "reason": "read-only action"}

    if level == "observe_only":
        return {
            "mode": "confirm",
            "category": category,
            "reason": "observe-only mode confirms every state-changing action",
        }

    if level == "confirm_irreversible" and category == "submission":
        return {
            "mode": "confirm",
            "category": category,
            "reason": "final submission requires confirmation at this autonomy level",
        }

    return {"mode": "allow", "category": category, "reason": f"allowed at level {level}"}
