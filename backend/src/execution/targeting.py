"""
Element targeting for browser actions.

Every action that touches an element resolves it here, so ambiguity and
not-found are handled once and consistently.

What this replaces
------------------
`handle_click` used to cascade through five strategies (role+name, a
non-anchored `.*name.*` regex over three roles, `get_by_text` exact then
inexact, an `a`/`button` filter, then role-only) across every frame, every role
alias and every name variant, taking `.first` at each step. Three consequences:

* Picking `.first` out of several matches is a coin flip decided by DOM order,
  not by what the user meant. On a form with "Save", "Save and Continue",
  "Submit" and "Submit application", no target could be addressed reliably.
* Each attempt carried a 12s actionability timeout, and a failure ran through
  all of them. A single miss could burn minutes. Observed in a real run: two
  60s timeouts on `click(link, "🔒 Log In to myUCF")` where the emoji-prefixed
  name did not match the computed accessible name, followed by an instant
  success on `click(link, "Log In")`.
* A miss reported only "element not found", so the model had nothing to correct
  with and simply retried the same wrong target.

Resolution here is cheap (`count()`, no actionability waits), and a failure
returns the role/name pairs that *do* exist so the next turn can pick one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from playwright.async_api import Frame, Locator, Page


# Roles Playwright's get_by_role accepts. Passing anything else raises, so an
# invalid role has to be caught before it reaches the locator.
VALID_ARIA_ROLES = frozenset({
    "alert", "alertdialog", "application", "article", "banner", "blockquote",
    "button", "caption", "cell", "checkbox", "code", "columnheader", "combobox",
    "complementary", "contentinfo", "definition", "deletion", "dialog",
    "directory", "document", "emphasis", "feed", "figure", "form", "generic",
    "grid", "gridcell", "group", "heading", "img", "insertion", "link", "list",
    "listbox", "listitem", "log", "main", "marquee", "math", "menu", "menubar",
    "menuitem", "menuitemcheckbox", "menuitemradio", "meter", "navigation",
    "none", "note", "option", "paragraph", "presentation", "progressbar",
    "radio", "radiogroup", "region", "row", "rowgroup", "rowheader",
    "scrollbar", "search", "searchbox", "separator", "slider", "spinbutton",
    "status", "strong", "subscript", "superscript", "switch", "tab", "table",
    "tablist", "tabpanel", "term", "textbox", "time", "timer", "toolbar",
    "tooltip", "tree", "treegrid", "treeitem",
})

# The DOM extractor and the model both sometimes emit HTML tag names instead of
# ARIA roles. Map the common ones rather than failing the action.
ROLE_ALIASES = {
    "a": "link", "anchor": "link", "hyperlink": "link",
    "input": "textbox", "text": "textbox", "textarea": "textbox",
    "select": "combobox", "dropdown": "combobox",
    "submit": "button", "btn": "button",
    "td": "cell", "th": "columnheader", "tr": "row",
    "ul": "list", "ol": "list", "li": "listitem",
    "label": "textbox",
}

# Roles that accept typed input.
EDITABLE_ROLES = frozenset({"textbox", "searchbox", "combobox", "spinbutton"})

# Roles with a checked state.
CHECKABLE_ROLES = frozenset({"checkbox", "radio", "switch", "menuitemcheckbox", "menuitemradio"})


@dataclass
class Candidate:
    """A role/name pair that actually exists on the page."""

    role: str
    name: str
    nth: int = 0
    frame_index: int = 0

    def as_hint(self) -> str:
        base = f'click(role={self.role}, name="{self.name}")'
        if self.nth:
            base = f'click(role={self.role}, name="{self.name}", nth={self.nth})'
        return base


@dataclass
class Resolution:
    """Outcome of resolving a target.

    Exactly one of `locator` or `error` is set.
    """

    locator: Optional[Locator] = None
    frame: Optional[Frame] = None
    error: Optional[str] = None          # "element_not_found" | "ambiguous_target" | "invalid_role"
    message: str = ""
    candidates: list[Candidate] = field(default_factory=list)
    match_count: int = 0

    @property
    def ok(self) -> bool:
        return self.locator is not None

    def candidate_hint(self, limit: int = 8) -> str:
        """Human/LLM readable list of usable targets, for the failure message."""
        if not self.candidates:
            return ""
        shown = self.candidates[:limit]
        lines = "\n".join(f"  - {c.as_hint()}" for c in shown)
        more = "" if len(self.candidates) <= limit else f"\n  ... and {len(self.candidates) - limit} more"
        return f"\nAvailable targets:\n{lines}{more}"


def normalize_role(role: Optional[str]) -> str:
    """Lowercase, de-alias, and validate a role. Returns '' when unusable."""
    value = (role or "").strip().lower()
    if not value:
        return ""
    value = ROLE_ALIASES.get(value, value)
    return value if value in VALID_ARIA_ROLES else ""


def unique_frames(page: Page) -> list[Frame]:
    """Every frame exactly once.

    `[page.main_frame] + list(page.frames)` processed the main frame twice,
    doubling the work on every failing lookup.
    """
    seen: set[int] = set()
    frames: list[Frame] = []
    for frame in page.frames:
        key = id(frame)
        if key not in seen:
            seen.add(key)
            frames.append(frame)
    return frames


_ARIA_LINE = re.compile(r'^-\s+([a-zA-Z][\w-]*)(?:\s+"((?:[^"\\]|\\.)*)")?')


async def element_inventory(page: Page, roles: Optional[set[str]] = None, limit: int = 120) -> list[Candidate]:
    """Every addressable role/name pair on the page, across all frames.

    Built from the accessibility tree, so the names match what `get_by_role`
    computes. One call per frame rather than a probe per guess.
    """
    inventory: list[Candidate] = []
    per_name_counts: dict[tuple[int, str, str], int] = {}

    for frame_index, frame in enumerate(unique_frames(page)):
        try:
            yaml_text = await frame.locator("body").aria_snapshot()
        except Exception:
            continue

        for raw in (yaml_text or "").splitlines():
            stripped = raw.strip()
            if not stripped.startswith("-") or stripped[1:].lstrip().startswith("/"):
                continue
            match = _ARIA_LINE.match(stripped)
            if not match:
                continue
            role = (match.group(1) or "").strip().lower()
            name = (match.group(2) or "").strip()
            if not name or role in {"generic", "none", "presentation", "text"}:
                continue
            if roles is not None and role not in roles:
                continue

            key = (frame_index, role, name)
            nth = per_name_counts.get(key, 0)
            per_name_counts[key] = nth + 1
            inventory.append(Candidate(role=role, name=name, nth=nth, frame_index=frame_index))
            if len(inventory) >= limit:
                return inventory
    return inventory


def _similar(target: str, other: str) -> bool:
    """Loose containment either way, ignoring case and non-alphanumerics.

    Lets an emoji-prefixed or punctuation-padded name still suggest its plain
    counterpart, which is how `🔒 Log In to myUCF` should have surfaced `Log In`.
    """
    def norm(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()

    a, b = norm(target), norm(other)
    if not a or not b:
        return False
    return a in b or b in a


async def suggest_candidates(
    page: Page,
    role: str,
    name: str,
    *,
    limit: int = 40,
) -> list[Candidate]:
    """Targets worth trying after a miss: same role first, then similar names."""
    inventory = await element_inventory(page, limit=200)
    if not inventory:
        return []

    same_role_similar = [c for c in inventory if c.role == role and _similar(name, c.name)]
    similar_any_role = [c for c in inventory if c.role != role and _similar(name, c.name)]
    same_role = [c for c in inventory if c.role == role and c not in same_role_similar]

    ordered = same_role_similar + similar_any_role + same_role
    return ordered[:limit]


async def resolve_target(
    page: Page,
    role: Optional[str],
    name: Optional[str],
    *,
    nth: Optional[int] = None,
    restrict_roles: Optional[set[str]] = None,
) -> Resolution:
    """Locate exactly one element by role and accessible name.

    Match order is exact name, then substring. A substring pass that yields more
    than one element is reported as `ambiguous_target` with the candidate list
    and their `nth` indices, rather than silently taking the first.
    """
    raw_role = (role or "").strip()
    clean_name = (name or "").strip()
    resolved_role = normalize_role(raw_role)

    if not resolved_role:
        candidates = await element_inventory(page, limit=60) if clean_name else []
        similar = [c for c in candidates if _similar(clean_name, c.name)] or candidates
        return Resolution(
            error="invalid_role",
            message=(
                f"'{raw_role}' is not a usable ARIA role."
                if raw_role else "No role was provided."
            ),
            candidates=similar[:20],
        )

    if restrict_roles is not None and resolved_role not in restrict_roles:
        return Resolution(
            error="invalid_role",
            message=(
                f"role='{resolved_role}' cannot be used for this action; "
                f"expected one of: {', '.join(sorted(restrict_roles))}."
            ),
            candidates=await element_inventory(page, roles=restrict_roles, limit=20),
        )

    if not clean_name:
        # Role alone is not a target. Previously this clicked the first element of
        # that role on the page, which is typically a nav or cookie-consent button.
        return Resolution(
            error="element_not_found",
            message=f"No accessible name given for role='{resolved_role}'.",
            candidates=await element_inventory(page, roles={resolved_role}, limit=20),
        )

    frames = unique_frames(page)

    # Exact first: unambiguous when it hits.
    for exact in (True, False):
        matches: list[tuple[Frame, Locator, int]] = []
        for frame in frames:
            try:
                locator = frame.get_by_role(resolved_role, name=clean_name, exact=exact)
                count = await locator.count()
            except Exception:
                # Detached frame or an unsupported role/name combination.
                continue
            for index in range(count):
                matches.append((frame, locator.nth(index), index))

        if not matches:
            continue

        if nth is not None:
            if 0 <= nth < len(matches):
                frame, locator, _ = matches[nth]
                return Resolution(locator=locator, frame=frame, match_count=len(matches))
            return Resolution(
                error="element_not_found",
                message=(
                    f"nth={nth} is out of range: {len(matches)} element(s) match "
                    f"role='{resolved_role}', name='{clean_name}'."
                ),
                match_count=len(matches),
            )

        if len(matches) == 1:
            frame, locator, _ = matches[0]
            return Resolution(locator=locator, frame=frame, match_count=1)

        # More than one match and no nth: make the model choose.
        candidates = [
            Candidate(role=resolved_role, name=clean_name, nth=i, frame_index=0)
            for i in range(len(matches))
        ]
        return Resolution(
            error="ambiguous_target",
            message=(
                f"{len(matches)} elements match role='{resolved_role}', name='{clean_name}'. "
                "Re-issue the action with nth= to choose one."
            ),
            candidates=candidates,
            match_count=len(matches),
        )

    return Resolution(
        error="element_not_found",
        message=f"No element matches role='{resolved_role}', name='{clean_name}'.",
        candidates=await suggest_candidates(page, resolved_role, clean_name),
    )
