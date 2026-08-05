"""
One page representation for every consumer.

This replaces two unrelated snapshot pipelines: a BeautifulSoup walk over
`page.content()` that guessed roles from tag names and could not see shadow DOM,
values, or state, and an aria-snapshot formatter in the executor that kept only
role and name. The model saw whichever was weaker for the page at hand.

The producer here is built on two sources per frame, merged:

* `locator.aria_snapshot()` is the authority for which targets exist and what
  they are called. Its names are computed by the same engine `get_by_role`
  resolves against (aria-labelledby included, open shadow DOM included), so
  every line advertised to the model is addressable by the action layer.
* One JavaScript pass over the composed tree (documents and open shadow roots)
  supplies what the accessibility snapshot does not carry: `required`, readonly,
  the input type (a file input is exposed as a bare `button` otherwise), and
  whether a value is present.

Secrets: the aria snapshot YAML contains current textbox values in plain text.
The parser records only *presence* of a value, never the text, so a typed
password cannot re-enter the LLM context through a page snapshot.

Rendering paginates instead of truncating. The old pipeline cut the snapshot at
a character budget in DOM order, so on a long form the unfilled fields at the
bottom were exactly what got dropped, silently. A snapshot that does not fit
now says how many elements are hidden and which `read_page(section=N)` call
shows them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from playwright.async_api import Frame, Page

# Kept out of the snapshot entirely: they carry no addressable target and no
# state the model can act on.
DROP_ROLES = frozenset({"generic", "none", "presentation", "text", "statictext"})

# Roles whose value/checked state the JS pass enriches.
FORM_ROLES = frozenset({
    "textbox", "searchbox", "combobox", "listbox", "checkbox", "radio",
    "switch", "spinbutton", "slider", "button",
})

# Form controls are worth showing even without an accessible name: an unlabeled
# required field is a fact about the page the model must know, and read_form
# reports the same control. Anything else unnamed is unaddressable noise.
UNNAMED_KEEP_ROLES = frozenset({
    "textbox", "searchbox", "combobox", "listbox", "checkbox", "radio",
    "switch", "spinbutton", "slider",
})

_MAX_ELEMENTS = 400
_MAX_OPTIONS_SHOWN = 8
_MAX_LINE_CHARS = 240
_ARIA_TIMEOUT_MS = 8000
SNAPSHOT_SECTION_MAX_CHARS = 3500


def unique_frames(page: Page) -> list[Frame]:
    """Every frame exactly once, in `page.frames` order.

    `page.frames` already includes the main frame; prepending it again used to
    double the work on every lookup. Order matters: `nth` hints in the snapshot
    must count matches in the same order `resolve_target` does.
    """
    seen: set[int] = set()
    frames: list[Frame] = []
    for frame in page.frames:
        key = id(frame)
        if key not in seen:
            seen.add(key)
            frames.append(frame)
    return frames


# ---------------------------------------------------------------------------
# aria_snapshot YAML parsing
# ---------------------------------------------------------------------------

@dataclass
class AriaNode:
    """One row of an aria_snapshot, with its nested children."""

    role: str
    name: str = ""
    attrs: dict = field(default_factory=dict)
    value_present: bool = False
    children: list["AriaNode"] = field(default_factory=list)


# `- role "name" [attr] [attr=x]: value` with every part after the role optional.
_ARIA_ROW = re.compile(
    r'^-\s+(?P<role>[a-zA-Z][\w-]*)'
    r'(?:\s+"(?P<name>(?:[^"\\]|\\.)*)")?'
    r'(?P<attrs>(?:\s+\[[^\]]*\])*)'
    r'(?P<colon>:)?'
    r'(?:\s+(?P<value>\S.*?))?'
    r'\s*$'
)

_ATTR = re.compile(r'\[([^\]=]+)(?:=([^\]]*))?\]')


def _unescape(name: str) -> str:
    return re.sub(r'\\(.)', r'\1', name or "")


def _unwrap_single_quoted_key(row: str) -> str:
    """Undo YAML single-quote wrapping around a whole aria row key."""
    if not row.startswith("- "):
        return row
    body = row[2:].lstrip()
    padding = row[2:len(row) - len(body)]
    if not body.startswith("'"):
        return row

    i = 1
    inner: list[str] = []
    while i < len(body):
        char = body[i]
        if char == "'":
            if i + 1 < len(body) and body[i + 1] == "'":
                inner.append("'")
                i += 2
                continue
            return f"- {padding}{''.join(inner)}{body[i + 1:]}"
        inner.append(char)
        i += 1
    return row


def parse_aria_yaml(yaml_text: str) -> list[AriaNode]:
    """Parse aria_snapshot YAML into a node tree.

    Handles the shapes Playwright emits: bare roles, quoted names with escapes,
    `[checked]`-style attributes, inline values after a colon, nested children
    by indentation, block-scalar values (skipped, recorded as value_present),
    and `- /url:`-style property rows (skipped: a property of the row above is
    not a clickable target).
    """
    roots: list[AriaNode] = []
    # (indent, node) for the current ancestry.
    stack: list[tuple[int, AriaNode]] = []

    for raw in (yaml_text or "").splitlines():
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()

        while stack and stack[-1][0] >= indent:
            stack.pop()

        if not stripped.startswith("-"):
            # Block-scalar continuation of the row above: it is value text.
            if stack:
                stack[-1][1].value_present = True
            continue

        if stripped[1:].lstrip().startswith("/"):
            continue

        match = _ARIA_ROW.match(_unwrap_single_quoted_key(stripped))
        if not match:
            continue

        role = (match.group("role") or "").strip().lower()
        if role == "text":
            continue

        attrs: dict = {}
        for attr_match in _ATTR.finditer(match.group("attrs") or ""):
            attrs[attr_match.group(1).strip()] = attr_match.group(2) or True

        node = AriaNode(
            role=role,
            name=_unescape((match.group("name") or "").strip()),
            attrs=attrs,
            # An inline value or a `: |` block scalar both mean the control
            # holds something. The text itself is never kept: it can be a
            # password, and presence is all the model needs.
            value_present=bool((match.group("value") or "").strip()),
        )

        if stack:
            stack[-1][1].children.append(node)
        else:
            roots.append(node)
        stack.append((indent, node))

    return roots


# ---------------------------------------------------------------------------
# JS metadata pass (composed tree: documents plus open shadow roots)
# ---------------------------------------------------------------------------

# Collects form-control metadata the accessibility snapshot does not expose.
# The accessible-name computation mirrors the priority Playwright uses for the
# common cases (aria-labelledby, aria-label, <label>, content, placeholder,
# title) so records line up with aria rows by (role, name). A control whose
# name computes differently simply stays unenriched in the snapshot; it is
# still listed and still addressable.
FORM_FIELDS_JS = r"""
() => {
    const out = [];
    const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
    const textOf = (el) => norm(el.innerText !== undefined ? el.innerText : el.textContent);

    const labelledByText = (el) => {
        const ids = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
        if (!ids.length) return '';
        const root = el.getRootNode();
        const lookup = (id) => (root.getElementById ? root.getElementById(id) : null);
        return norm(ids.map((id) => { const ref = lookup(id); return ref ? textOf(ref) : ''; }).join(' '));
    };

    const labelText = (el) => {
        if (el.labels && el.labels.length) {
            return norm(Array.from(el.labels).map(textOf).join(' '));
        }
        const root = el.getRootNode();
        if (el.id && root.querySelector) {
            try {
                const l = root.querySelector('label[for="' + CSS.escape(el.id) + '"]');
                if (l) return textOf(l);
            } catch (e) { /* invalid id for a selector */ }
        }
        const wrap = el.closest ? el.closest('label') : null;
        return wrap ? textOf(wrap) : '';
    };

    const accName = (el) => {
        const tag = el.tagName;
        const type = (el.type || '').toLowerCase();
        return labelledByText(el)
            || norm(el.getAttribute('aria-label'))
            || labelText(el)
            || (tag === 'BUTTON' || (el.getAttribute('role') || '') === 'button' ? textOf(el) : '')
            || (tag === 'INPUT' && ['submit', 'button', 'reset'].includes(type) ? norm(el.value) : '')
            || (tag === 'INPUT' && type === 'image' ? norm(el.getAttribute('alt')) : '')
            || norm(el.getAttribute('placeholder'))
            || norm(el.getAttribute('title'))
            || '';
    };

    const roleOf = (el) => {
        const explicit = norm(el.getAttribute('role')).toLowerCase();
        if (explicit) return explicit.split(/\s+/)[0];
        const tag = el.tagName;
        if (tag === 'SELECT') return (el.multiple || el.size > 1) ? 'listbox' : 'combobox';
        if (tag === 'TEXTAREA') return 'textbox';
        if (tag === 'BUTTON') return 'button';
        if (tag === 'A') return el.hasAttribute('href') ? 'link' : 'generic';
        const map = {
            text: 'textbox', email: 'textbox', tel: 'textbox', url: 'textbox',
            password: 'textbox', search: 'searchbox', number: 'spinbutton',
            checkbox: 'checkbox', radio: 'radio', range: 'slider',
            file: 'button', submit: 'button', button: 'button', reset: 'button',
            image: 'button', color: 'button',
        };
        return map[(el.type || 'text').toLowerCase()] || 'textbox';
    };

    const isVisible = (el) => {
        try {
            const r = el.getBoundingClientRect();
            if (!r.width && !r.height) return false;
            const st = getComputedStyle(el);
            return st.visibility !== 'hidden' && st.display !== 'none';
        } catch (e) {
            return true;
        }
    };

    const ARIA_WIDGET_ROLES = new Set([
        'textbox', 'searchbox', 'combobox', 'checkbox', 'radio', 'switch',
        'spinbutton', 'slider', 'listbox',
    ]);

    const collect = (el, inShadow) => {
        const tag = el.tagName;
        const isFormTag = tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || tag === 'BUTTON';
        const explicitRole = norm(el.getAttribute('role')).toLowerCase();
        const isAriaWidget = !isFormTag && ARIA_WIDGET_ROLES.has(explicitRole);
        if (!isFormTag && !isAriaWidget) return;

        const type = tag === 'INPUT' ? (el.type || 'text').toLowerCase() : tag.toLowerCase();
        if (type === 'hidden') return;

        const record = {
            tag: tag.toLowerCase(),
            type: type,
            role: roleOf(el),
            name: accName(el),
            // Display-only fallback for read_form. Never merged into the
            // snapshot name: get_by_role cannot resolve a name= attribute.
            fallbackId: norm(el.getAttribute('name')) || norm(el.id),
            required: !!(el.required || el.getAttribute('aria-required') === 'true'),
            disabled: !!(el.disabled || el.getAttribute('aria-disabled') === 'true'),
            readonly: !!(el.readOnly || el.getAttribute('aria-readonly') === 'true'),
            checked: null,
            filled: null,
            valueLen: 0,
            options: [],
            selectedValue: '',
            fileName: '',
            visible: isVisible(el),
            inShadow: !!inShadow,
        };

        if (type === 'checkbox' || type === 'radio') {
            record.checked = !!el.checked;
        } else if (isAriaWidget && (explicitRole === 'checkbox' || explicitRole === 'radio' || explicitRole === 'switch')) {
            record.checked = el.getAttribute('aria-checked') === 'true';
        } else if (tag === 'SELECT') {
            record.filled = !!norm(el.value);
            record.selectedValue = norm(el.value);
            record.options = Array.from(el.options).slice(0, 30).map((o) => ({
                label: norm(o.label || o.text),
                selected: !!o.selected,
            }));
        } else if (type === 'file') {
            const has = !!(el.files && el.files.length);
            record.filled = has;
            record.fileName = has ? el.files[0].name : '';
        } else if (tag === 'BUTTON' || ['submit', 'button', 'reset', 'image'].includes(type)) {
            /* buttons carry no value state */
        } else if (isAriaWidget) {
            record.filled = !!(norm(el.getAttribute('aria-valuenow')) || textOf(el) || norm(el.value));
        } else {
            const len = el.value ? String(el.value).length : 0;
            record.filled = len > 0;
            record.valueLen = len;
        }

        out.push(record);
    };

    const walk = (root, inShadow) => {
        if (out.length >= 250) return;
        const children = root.children ? Array.from(root.children) : [];
        for (const el of children) {
            if (out.length >= 250) return;
            collect(el, inShadow);
            if (el.shadowRoot) walk(el.shadowRoot, true);
            walk(el, inShadow);
        }
    };

    walk(document.body || document.documentElement, false);
    return out;
}
"""


async def collect_form_fields(frame: Frame) -> list[dict]:
    """All form controls in one frame, composed tree, with state metadata."""
    try:
        return await frame.evaluate(FORM_FIELDS_JS) or []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# The snapshot itself
# ---------------------------------------------------------------------------

@dataclass
class PageElement:
    """One addressable element as shown to the model."""

    ref: str
    role: str
    name: str
    frame_index: int = 0
    frame_url: str = ""
    # Enrichment. None means "not known / not applicable", never "no".
    input_type: str = ""
    required: bool = False
    disabled: bool = False
    readonly: bool = False
    checked: Optional[bool] = None
    filled: Optional[bool] = None
    options: list[str] = field(default_factory=list)
    selected_option: str = ""
    visible: bool = True
    in_shadow: bool = False
    nth: Optional[int] = None

    def render_line(self) -> str:
        # The name is capped before quoting so the closing quote always
        # survives; truncating the assembled line could otherwise cut it and
        # break the `[role="x"] "name"` contract consumers parse.
        display_name = self.name if len(self.name) <= 160 else self.name[:157] + "..."
        escaped = display_name.replace("\\", "\\\\").replace('"', '\\"')
        parts = [f"[ref={self.ref}]", f'[role="{self.role}"]', f'"{escaped}"']
        if not self.name:
            parts.append("[unlabeled]")
        if self.nth is not None:
            parts.append(f"[nth={self.nth}]")
        if self.input_type == "file":
            parts.append("[file input]")
        if self.required:
            parts.append("[required]")
        if self.disabled:
            parts.append("[disabled]")
        if self.readonly:
            parts.append("[readonly]")
        if self.checked is not None:
            parts.append("[checked]" if self.checked else "[unchecked]")
        if self.filled is not None:
            if self.input_type == "file":
                parts.append("[file attached]" if self.filled else "[no file]")
            else:
                parts.append("[filled]" if self.filled else "[empty]")
        if self.options:
            shown = [
                f"{opt}*" if opt == self.selected_option else opt
                for opt in self.options[:_MAX_OPTIONS_SHOWN]
            ]
            more = len(self.options) - _MAX_OPTIONS_SHOWN
            suffix = f" | ... +{more} more" if more > 0 else ""
            parts.append(f"[options: {' | '.join(shown)}{suffix}]")
        if not self.visible:
            parts.append("[hidden]")
        line = " ".join(parts)
        if len(line) > _MAX_LINE_CHARS:
            line = line[: _MAX_LINE_CHARS - 3] + "..."
        return line


@dataclass
class PageSnapshot:
    """Everything the model can see and act on, for one moment of one page."""

    url: str
    elements: list[PageElement] = field(default_factory=list)
    frame_urls: list[str] = field(default_factory=list)

    def _rendered_rows(self) -> list[tuple[int, str]]:
        """(frame_index, line) rows, with an iframe header before each frame."""
        rows: list[tuple[int, str]] = []
        current_frame = 0
        for element in self.elements:
            if element.frame_index != current_frame:
                current_frame = element.frame_index
                rows.append((current_frame, f"[iframe: {element.frame_url[:80]}]"))
            rows.append((element.frame_index, element.render_line()))
        return rows

    def _sections(self, max_chars: int) -> list[list[tuple[int, str]]]:
        rows = self._rendered_rows()
        if not rows:
            return []
        # Room for the section header/footer lines added around the body.
        budget = max(400, max_chars - 220)
        sections: list[list[tuple[int, str]]] = [[]]
        used = 0
        for row in rows:
            cost = len(row[1]) + 1
            if sections[-1] and used + cost > budget:
                sections.append([])
                used = 0
            sections[-1].append(row)
            used += cost
        return sections

    def section_count(self, max_chars: int = SNAPSHOT_SECTION_MAX_CHARS) -> int:
        return max(1, len(self._sections(max_chars)))

    def render(self, max_chars: int = SNAPSHOT_SECTION_MAX_CHARS, section: int = 1) -> str:
        """One section of the snapshot, honest about what it does not include.

        The previous pipeline truncated at `max_chars` in DOM order with a bare
        `[DOM truncated]` marker, so the model could not know what was missing
        or ask for it. Every section now names the elements it hides and the
        exact call that reveals them.
        """
        sections = self._sections(max_chars)
        if not sections:
            return "[No interactive elements in snapshot]"

        total = len(sections)
        index = min(max(section, 1), total)
        chosen = sections[index - 1]

        lines: list[str] = []
        if total > 1:
            first = sum(len([r for r in s if not r[1].startswith("[iframe")]) for s in sections[: index - 1]) + 1
            count = len([r for r in chosen if not r[1].startswith("[iframe")])
            lines.append(
                f"[page snapshot: section {index} of {total}, "
                f"elements {first}-{first + count - 1} of {len(self.elements)}]"
            )
            # A section that starts mid-frame still says which frame it is in.
            first_frame = chosen[0][0]
            if first_frame != 0 and not chosen[0][1].startswith("[iframe"):
                frame_url = self.frame_urls[first_frame] if first_frame < len(self.frame_urls) else ""
                lines.append(f"[iframe: {frame_url[:80]}]")

        lines.extend(row[1] for row in chosen)

        if index < total:
            remaining = sum(
                len([r for r in s if not r[1].startswith("[iframe")]) for s in sections[index:]
            )
            lines.append(
                f"[{remaining} more element(s) below. Call read_page(section={index + 1}) to see them.]"
            )
        return "\n".join(lines)


def _flatten_aria_nodes(nodes: list[AriaNode], out: list[PageElement], limit: int) -> None:
    def collect_options(node: AriaNode, options: list[str]) -> str:
        selected = ""
        for child in node.children:
            if child.role == "option" and child.name:
                options.append(child.name)
                if child.attrs.get("selected"):
                    selected = child.name
            else:
                nested = collect_options(child, options)
                if nested and not selected:
                    selected = nested
        return selected

    for node in nodes:
        if len(out) >= limit:
            return
        role = node.role
        if role in DROP_ROLES or role == "iframe":
            _flatten_aria_nodes(node.children, out, limit)
            continue
        if role == "option":
            # Native options are not clickable in Chromium; advertising them
            # made the model waste turns. They surface on their combobox row.
            continue

        options: list[str] = []
        selected = ""
        if role in {"combobox", "listbox"}:
            selected = collect_options(node, options)

        keep = bool(node.name) or role in UNNAMED_KEEP_ROLES
        if keep:
            # The snapshot omits [checked] on unchecked controls, so for
            # checkable roles absence means unchecked, not unknown.
            checked = None
            if role in {"checkbox", "radio", "switch", "menuitemcheckbox", "menuitemradio"}:
                checked = node.attrs.get("checked") is True
            element = PageElement(
                ref="",
                role=role,
                name=node.name,
                checked=checked,
                disabled=bool(node.attrs.get("disabled")),
                filled=node.value_present or None,
                options=options,
                selected_option=selected,
            )
            out.append(element)

        if role not in {"combobox", "listbox"}:
            _flatten_aria_nodes(node.children, out, limit)


def _merge_form_metadata(elements: list[PageElement], js_fields: list[dict]) -> None:
    """Attach JS-pass metadata to aria rows by (role, name), then by unique name.

    The aria snapshot stays the authority for existence and naming. A JS record
    that matches nothing is dropped rather than appended: appending it would
    advertise a name `get_by_role` may not resolve, which is exactly the
    failure mode this module exists to end.
    """

    def norm(value: str) -> str:
        return re.sub(r"\s+", " ", (value or "")).strip()

    by_key: dict[tuple[str, str], list[dict]] = {}
    for record in js_fields:
        by_key.setdefault((record.get("role", ""), norm(record.get("name", ""))), []).append(record)

    unmatched: list[PageElement] = []
    for element in elements:
        if element.role not in FORM_ROLES:
            continue
        queue = by_key.get((element.role, norm(element.name)))
        if queue:
            _apply_record(element, queue.pop(0))
        else:
            unmatched.append(element)

    # Second pass: a name that is unique on both sides matches even when the
    # role mapping drifted (e.g. a date input exposed under a different role).
    by_name: dict[str, list[dict]] = {}
    for queue in by_key.values():
        for record in queue:
            by_name.setdefault(norm(record.get("name", "")), []).append(record)
    for element in unmatched:
        candidates = by_name.get(norm(element.name)) or []
        if len(candidates) == 1 and element.name:
            _apply_record(element, candidates[0])
            candidates.clear()


def _apply_record(element: PageElement, record: dict) -> None:
    element.input_type = record.get("type") or ""
    element.required = bool(record.get("required"))
    element.disabled = element.disabled or bool(record.get("disabled"))
    element.readonly = bool(record.get("readonly"))
    if record.get("checked") is not None:
        element.checked = bool(record.get("checked"))
    if record.get("filled") is not None:
        element.filled = bool(record.get("filled"))
    element.visible = bool(record.get("visible", True))
    element.in_shadow = bool(record.get("inShadow"))
    js_options = [opt.get("label", "") for opt in record.get("options") or [] if opt.get("label")]
    if js_options and not element.options:
        element.options = js_options
        for opt in record.get("options") or []:
            if opt.get("selected"):
                element.selected_option = opt.get("label", "")
                break


def _assign_refs_and_nth(elements: list[PageElement]) -> None:
    """Refs are stable within one snapshot; nth mirrors resolve_target's order.

    Duplicate (role, name) pairs get explicit `nth=` markers so the model can
    disambiguate on the first try instead of after an `ambiguous_target` error.
    The index counts matches across frames in the same order the resolver does.
    """
    counts: dict[tuple[str, str], int] = {}
    for element in elements:
        key = (element.role, element.name)
        counts[key] = counts.get(key, 0) + 1

    seen: dict[tuple[str, str], int] = {}
    for position, element in enumerate(elements, start=1):
        element.ref = f"e{position}"
        key = (element.role, element.name)
        if element.name and counts[key] > 1:
            element.nth = seen.get(key, 0)
            seen[key] = element.nth + 1


async def capture_page_snapshot(page: Page, max_elements: int = _MAX_ELEMENTS) -> PageSnapshot:
    """The single producer: every frame, one merged element list."""
    elements: list[PageElement] = []
    frame_urls: list[str] = []

    for frame_index, frame in enumerate(unique_frames(page)):
        frame_urls.append(frame.url or "")
        if len(elements) >= max_elements:
            continue
        try:
            yaml_text = await frame.locator("body").aria_snapshot(timeout=_ARIA_TIMEOUT_MS)
        except Exception:
            continue

        frame_elements: list[PageElement] = []
        _flatten_aria_nodes(parse_aria_yaml(yaml_text), frame_elements, max_elements - len(elements))
        _merge_form_metadata(frame_elements, await collect_form_fields(frame))

        for element in frame_elements:
            element.frame_index = frame_index
            element.frame_url = frame.url or ""
        elements.extend(frame_elements)

    _assign_refs_and_nth(elements)
    return PageSnapshot(url=page.url, elements=elements, frame_urls=frame_urls)


# The exact line shape consumers may parse. The role/name pair is contiguous so
# substring checks like `[role="textbox"] "password"` keep working.
SNAPSHOT_LINE = re.compile(r'\[role="(?P<role>[^"]+)"\]\s+"(?P<name>(?:[^"\\]|\\.)*)"')


__all__ = [
    "AriaNode",
    "PageElement",
    "PageSnapshot",
    "SNAPSHOT_LINE",
    "capture_page_snapshot",
    "collect_form_fields",
    "parse_aria_yaml",
    "unique_frames",
    "FORM_FIELDS_JS",
]
