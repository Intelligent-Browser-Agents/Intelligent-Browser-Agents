"""
Element-addressed browser actions.

Every action here names its target explicitly as `(role, name[, nth])` and then
confirms its own effect by reading state back. Two deliberate departures from the
handlers this replaces:

**The model says where, not just what.** `type(text)` only carried a value; the
handler guessed the field from seven hardcoded selector lists and by classifying
the *value* being typed. So "Edwin Villanueva" was classified as a title and
routed to the cover-letter textarea, and a password without a symbol failed the
password test and was typed into a visible field. `fill(role, name, text)` removes
the guess.

**Success means observed, not attempted.** `fill` re-reads the value, `set_checkbox`
re-reads the checked state, `select_option` re-reads the selection, and `click`
compares URL and a DOM digest. Handlers that cannot confirm their effect report
`verified=False` instead of a bare success, which is what let a masked or readonly
field report a value that never landed.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from playwright.async_api import Error as PlaywrightError, Page

from .models import ExecutionOutput
from .targeting import (
    CHECKABLE_ROLES,
    EDITABLE_ROLES,
    Resolution,
    element_inventory,
    resolve_target,
    unique_frames,
)

# Per-element actionability budget. The old code allowed 12s per attempt and then
# retried across five strategies, every frame and every name variant, so one miss
# could run for minutes. Resolution is now cheap and exact, so a short budget is
# enough and a genuine failure surfaces quickly with candidates attached.
ELEMENT_TIMEOUT_MS = 8000
SETTLE_SECONDS = 0.3


def _elapsed_ms(start: float) -> int:
    return int((asyncio.get_event_loop().time() - start) * 1000)


def _fail(
    action: str,
    args: dict,
    message: str,
    error_type: str,
    start: float,
) -> ExecutionOutput:
    return ExecutionOutput(
        action=action,
        args=args,
        status="failure",
        error_type=error_type,
        message=message,
        execution_time_ms=_elapsed_ms(start),
        verified=False,
    )


def _ok(
    action: str,
    args: dict,
    message: str,
    start: float,
    *,
    verified: bool,
    extracted_text: Optional[str] = None,
) -> ExecutionOutput:
    return ExecutionOutput(
        action=action,
        args=args,
        status="success",
        error_type="none",
        message=message,
        execution_time_ms=_elapsed_ms(start),
        verified=verified,
        extracted_text=extracted_text,
    )


def _resolution_failure(action: str, args: dict, res: Resolution, start: float) -> ExecutionOutput:
    """Turn a failed resolution into an output that tells the model what to do next."""
    error_type = res.error or "element_not_found"
    if error_type == "invalid_role":
        # No target supplied at all is a malformed call, not a missing element.
        no_target = not (args.get("role") or "").strip() if isinstance(args.get("role"), str) else not args.get("role")
        error_type = "ambiguous_step" if no_target else "element_not_found"
    return _fail(action, args, f"{res.message}{res.candidate_hint()}", error_type, start)


async def _dom_digest(page: Page) -> str:
    """Cheap fingerprint of the visible page, for detecting that a click did something."""
    try:
        return await page.evaluate(
            "() => (document.body ? document.body.innerText.length + ':' + "
            "document.querySelectorAll('*').length : '')"
        )
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# click
# ---------------------------------------------------------------------------

async def do_click(
    page: Page,
    role: Optional[str],
    name: Optional[str],
    nth: Optional[int] = None,
) -> ExecutionOutput:
    start = asyncio.get_event_loop().time()
    args = {"role": role, "name": name}
    if nth is not None:
        args["nth"] = nth

    res = await resolve_target(page, role, name, nth=nth)
    if not res.ok:
        return _resolution_failure("click", args, res, start)

    url_before = page.url
    digest_before = await _dom_digest(page)

    try:
        await res.locator.scroll_into_view_if_needed(timeout=ELEMENT_TIMEOUT_MS)
    except Exception:
        pass

    try:
        # No force=True. Forcing dispatches at coordinates regardless of overlays
        # or disabled state, so a cookie banner covering the button produced a
        # success with nothing happening.
        await res.locator.click(timeout=ELEMENT_TIMEOUT_MS)
    except PlaywrightError as exc:
        detail = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        lowered = detail.lower()
        if "timeout" in lowered:
            return _fail(
                "click",
                args,
                f"Element found but not clickable within {ELEMENT_TIMEOUT_MS}ms "
                f"(it may be covered, disabled or off-screen): {detail}",
                "not_interactable",
                start,
            )
        return _fail("click", args, f"Click failed: {detail}", "not_interactable", start)

    await asyncio.sleep(SETTLE_SECONDS)

    # Confirm something actually changed.
    url_after = page.url
    digest_after = await _dom_digest(page)
    changed = url_after != url_before or digest_after != digest_before

    detail = "URL changed" if url_after != url_before else ("page content changed" if changed else "no observable change")
    return _ok(
        "click",
        args,
        f"Clicked {res.locator and role} '{name}' ({detail}).",
        start,
        verified=changed,
    )


# ---------------------------------------------------------------------------
# fill
# ---------------------------------------------------------------------------

async def do_fill(
    page: Page,
    role: Optional[str],
    name: Optional[str],
    text: Optional[str],
    nth: Optional[int] = None,
    clear: bool = True,
) -> ExecutionOutput:
    start = asyncio.get_event_loop().time()
    value = "" if text is None else str(text)
    # The value is never echoed: this message reaches the model's context and the
    # run log, and it can be a password.
    args = {"role": role, "name": name, "text": value}
    if nth is not None:
        args["nth"] = nth

    res = await resolve_target(page, role, name, nth=nth, restrict_roles=set(EDITABLE_ROLES))
    if not res.ok:
        return _resolution_failure("fill", args, res, start)

    locator = res.locator
    try:
        await locator.scroll_into_view_if_needed(timeout=ELEMENT_TIMEOUT_MS)
    except Exception:
        pass

    # Refuse rather than silently no-op on a field that cannot accept input.
    try:
        if not await locator.is_editable(timeout=ELEMENT_TIMEOUT_MS):
            return _fail(
                "fill",
                args,
                f"Field '{name}' is not editable (readonly or disabled).",
                "not_interactable",
                start,
            )
    except PlaywrightError as exc:
        return _fail("fill", args, f"Field '{name}' is not available: {str(exc).splitlines()[0]}", "not_interactable", start)

    try:
        if clear:
            await locator.fill(value, timeout=ELEMENT_TIMEOUT_MS)
        else:
            await locator.click(timeout=ELEMENT_TIMEOUT_MS)
            await locator.type(value, delay=10)
    except PlaywrightError as exc:
        detail = str(exc).splitlines()[0]
        kind = "timeout" if "timeout" in detail.lower() else "not_interactable"
        return _fail("fill", args, f"Could not fill '{name}': {detail}", kind, start)

    await asyncio.sleep(0.15)

    # Read back. A masked phone input, a date field given a non-ISO value, or a
    # React-controlled combobox all commonly leave the value empty or mangled.
    try:
        actual = await locator.input_value(timeout=ELEMENT_TIMEOUT_MS)
    except PlaywrightError:
        try:
            actual = (await locator.inner_text()).strip()
        except Exception:
            actual = None

    if actual is None:
        return _ok(
            "fill",
            args,
            f"Typed {len(value)} character(s) into {role} '{name}' (value could not be read back).",
            start,
            verified=False,
        )

    if actual == value:
        return _ok("fill", args, f"Filled {role} '{name}' with {len(value)} character(s).", start, verified=True)

    if value and value in actual:
        return _ok(
            "fill",
            args,
            f"Filled {role} '{name}'; field holds extra formatting ({len(actual)} chars stored).",
            start,
            verified=True,
        )

    return _fail(
        "fill",
        args,
        (
            f"Value did not stick in {role} '{name}': wrote {len(value)} character(s) "
            f"but the field now holds {len(actual)} character(s). The field may be masked, "
            "reformatted, or controlled by a script that rejected the input."
        ),
        "verification_failed",
        start,
    )


# ---------------------------------------------------------------------------
# set_checkbox
# ---------------------------------------------------------------------------

async def do_set_checkbox(
    page: Page,
    role: Optional[str],
    name: Optional[str],
    checked: bool = True,
    nth: Optional[int] = None,
) -> ExecutionOutput:
    """Set a checkbox, radio or switch to an explicit state.

    Previously the only option was a bare `click`, which toggles. A retry after a
    click that actually worked but was reported as failed would silently turn the
    box back off, and nothing ever read the state. Radio groups were worse: option
    labels repeat across questions, so `.first` answered the first question on the
    page regardless of which was intended.
    """
    start = asyncio.get_event_loop().time()
    args = {"role": role, "name": name, "checked": checked}
    if nth is not None:
        args["nth"] = nth

    res = await resolve_target(page, role, name, nth=nth, restrict_roles=set(CHECKABLE_ROLES))
    if not res.ok:
        return _resolution_failure("set_checkbox", args, res, start)

    locator = res.locator
    try:
        already = await locator.is_checked(timeout=ELEMENT_TIMEOUT_MS)
    except PlaywrightError as exc:
        return _fail(
            "set_checkbox",
            args,
            f"Could not read the state of '{name}': {str(exc).splitlines()[0]}",
            "not_interactable",
            start,
        )

    if already == checked:
        return _ok(
            "set_checkbox",
            args,
            f"{role} '{name}' was already {'checked' if checked else 'unchecked'}.",
            start,
            verified=True,
        )

    try:
        if checked:
            await locator.check(timeout=ELEMENT_TIMEOUT_MS)
        else:
            await locator.uncheck(timeout=ELEMENT_TIMEOUT_MS)
    except PlaywrightError as exc:
        detail = str(exc).splitlines()[0]
        kind = "timeout" if "timeout" in detail.lower() else "not_interactable"
        return _fail("set_checkbox", args, f"Could not set '{name}': {detail}", kind, start)

    try:
        now = await locator.is_checked(timeout=ELEMENT_TIMEOUT_MS)
    except PlaywrightError:
        now = None

    if now is None:
        return _ok("set_checkbox", args, f"Set {role} '{name}' (state not readable).", start, verified=False)
    if now == checked:
        return _ok(
            "set_checkbox",
            args,
            f"{role} '{name}' is now {'checked' if checked else 'unchecked'}.",
            start,
            verified=True,
        )
    return _fail(
        "set_checkbox",
        args,
        f"'{name}' did not change state; it is still {'checked' if now else 'unchecked'}.",
        "verification_failed",
        start,
    )


# ---------------------------------------------------------------------------
# select_option
# ---------------------------------------------------------------------------

async def do_select_option(
    page: Page,
    role: Optional[str],
    name: Optional[str],
    value: Optional[str] = None,
    label: Optional[str] = None,
    nth: Optional[int] = None,
) -> ExecutionOutput:
    """Choose an option in a native <select>.

    There was no way to do this at all. The DOM extractor advertised each
    `<option>` as a clickable target, but Chromium does not expose native select
    options to clicks, so every attempt was wasted. Country, state, degree and
    "how did you hear about us" are native selects on most application forms.
    """
    start = asyncio.get_event_loop().time()
    args = {"role": role, "name": name, "value": value, "label": label}
    if nth is not None:
        args["nth"] = nth

    if value is None and label is None:
        return _fail("select_option", args, "Provide either value= or label= to choose an option.", "ambiguous_step", start)

    res = await resolve_target(page, role, name, nth=nth, restrict_roles={"combobox", "listbox"})
    if not res.ok:
        return _resolution_failure("select_option", args, res, start)

    locator = res.locator
    wanted = label if label is not None else value

    # Enumerate first. Handing an absent option straight to select_option burns the
    # full actionability timeout and then reports only "Timeout exceeded", which
    # tells the model nothing about what it could have picked.
    options: list[dict] = []
    try:
        options = await locator.evaluate(
            "el => Array.from(el.options || []).map(o => ({value: o.value, label: o.label || o.text}))"
        ) or []
    except Exception:
        options = []

    if options:
        available_labels = [str(o.get("label") or "").strip() for o in options]
        available_values = [str(o.get("value") or "").strip() for o in options]
        target_list = available_labels if label is not None else available_values
        if wanted not in target_list:
            shown = ", ".join(f"'{o}'" for o in (available_labels if label is not None else available_values) if o)
            return _fail(
                "select_option",
                args,
                f"'{wanted}' is not an option in {role} '{name}'.\nAvailable options: {shown}",
                "element_not_found",
                start,
            )

    try:
        if label is not None:
            await locator.select_option(label=label, timeout=ELEMENT_TIMEOUT_MS)
        else:
            await locator.select_option(value=value, timeout=ELEMENT_TIMEOUT_MS)
    except PlaywrightError as exc:
        detail = str(exc).splitlines()[0]
        shown = ", ".join(
            f"'{o.get('label') or o.get('value')}'" for o in options[:20]
        )
        hint = f"\nAvailable options: {shown}" if shown else ""
        return _fail(
            "select_option",
            args,
            f"Could not select '{wanted}' in '{name}': {detail}{hint}",
            "element_not_found",
            start,
        )

    try:
        selected = await locator.input_value(timeout=ELEMENT_TIMEOUT_MS)
    except PlaywrightError:
        selected = None

    if selected is None:
        return _ok("select_option", args, f"Selected '{wanted}' in '{name}' (not read back).", start, verified=False)

    matched = selected == value if value is not None else True
    if label is not None:
        try:
            chosen_label = (await locator.locator("option:checked").inner_text()).strip()
            matched = chosen_label == label
        except Exception:
            matched = True

    return _ok(
        "select_option",
        args,
        f"Selected '{wanted}' in {role} '{name}'.",
        start,
        verified=bool(matched),
    )


# ---------------------------------------------------------------------------
# upload_file
# ---------------------------------------------------------------------------

async def do_upload_file(
    page: Page,
    role: Optional[str],
    name: Optional[str],
    file_path: Optional[str] = None,
    nth: Optional[int] = None,
) -> ExecutionOutput:
    """Attach a local file to a file input.

    Nothing in the action set could do this, which made every application
    requiring a resume unfinishable. `capabilities.py` rewrote "upload a file"
    into "click the file input and use the system file chooser when prompted",
    which nothing implemented, and the DOM extractor reported `input[type=file]`
    as a plain textbox, so the model would try to type a path into it.
    """
    start = asyncio.get_event_loop().time()
    args = {"role": role, "name": name, "file_path": file_path}

    if not file_path:
        return _fail("upload_file", args, "No file was provided to upload.", "ambiguous_step", start)

    import os

    if not os.path.isfile(file_path):
        return _fail("upload_file", args, f"File not found on the agent host: {file_path}", "ambiguous_step", start)

    # File inputs are frequently visually hidden behind a styled button, so a
    # role-based lookup often will not see them. Resolve by role when possible and
    # fall back to the file inputs present in each frame.
    locator = None
    if name:
        res = await resolve_target(page, role or "textbox", name, nth=nth)
        if res.ok:
            locator = res.locator

    if locator is None:
        for frame in unique_frames(page):
            try:
                candidate = frame.locator("input[type='file']")
                count = await candidate.count()
            except Exception:
                continue
            if count:
                locator = candidate.nth(nth or 0)
                break

    if locator is None:
        return _fail("upload_file", args, "No file input found on the page.", "element_not_found", start)

    try:
        await locator.set_input_files(file_path, timeout=ELEMENT_TIMEOUT_MS)
    except PlaywrightError as exc:
        return _fail("upload_file", args, f"Upload failed: {str(exc).splitlines()[0]}", "not_interactable", start)

    # Read back the attached filename.
    try:
        attached = await locator.evaluate("el => el.files && el.files.length ? el.files[0].name : ''")
    except Exception:
        attached = ""

    expected = os.path.basename(file_path)
    if attached == expected:
        return _ok("upload_file", args, f"Attached '{expected}'.", start, verified=True)
    return _ok(
        "upload_file",
        args,
        f"Attached '{expected}' (readback returned '{attached or 'nothing'}').",
        start,
        verified=False,
    )


# ---------------------------------------------------------------------------
# wait_for
# ---------------------------------------------------------------------------

async def do_wait_for(
    page: Page,
    role: Optional[str] = None,
    name: Optional[str] = None,
    url_contains: Optional[str] = None,
    text_contains: Optional[str] = None,
    seconds: float = 10.0,
) -> ExecutionOutput:
    """Wait for an observable condition instead of sleeping blindly.

    `wait(seconds)` was a bare `asyncio.sleep`, so multi-page form transitions and
    async result loading were handled by guessing a duration.
    """
    start = asyncio.get_event_loop().time()
    args = {"role": role, "name": name, "url_contains": url_contains, "text_contains": text_contains, "seconds": seconds}
    timeout_ms = max(500, int(seconds * 1000))

    if not any([role and name, url_contains, text_contains]):
        return _fail(
            "wait_for",
            args,
            "Provide role+name, url_contains, or text_contains to wait for.",
            "ambiguous_step",
            start,
        )

    try:
        if url_contains:
            await page.wait_for_url(f"**{url_contains}**", timeout=timeout_ms)
            return _ok("wait_for", args, f"URL now contains '{url_contains}'.", start, verified=True)

        if text_contains:
            await page.get_by_text(text_contains, exact=False).first.wait_for(
                state="visible", timeout=timeout_ms
            )
            return _ok("wait_for", args, f"Text '{text_contains}' is visible.", start, verified=True)

        deadline = asyncio.get_event_loop().time() + seconds
        while asyncio.get_event_loop().time() < deadline:
            res = await resolve_target(page, role, name)
            if res.ok:
                try:
                    await res.locator.wait_for(state="visible", timeout=1000)
                    return _ok("wait_for", args, f"{role} '{name}' is visible.", start, verified=True)
                except PlaywrightError:
                    pass
            await asyncio.sleep(0.25)

        return _fail("wait_for", args, f"{role} '{name}' did not appear within {seconds}s.", "timeout", start)
    except PlaywrightError as exc:
        return _fail("wait_for", args, f"Wait failed: {str(exc).splitlines()[0]}", "timeout", start)


# ---------------------------------------------------------------------------
# read_form
# ---------------------------------------------------------------------------

async def do_read_form(page: Page) -> ExecutionOutput:
    """Report every field on the page with its current state.

    Answers "which fields are still empty?", which nothing could do before. The
    model had to re-read a truncated snapshot and infer, and because truncation is
    in DOM order the unfilled fields at the bottom of a long form were exactly
    what got cut.

    Uses the same collector as the page snapshot, so this inventory and
    DOM_SNAPSHOT cannot disagree, and both see the composed tree: fields inside
    open shadow roots (Salesforce/LWC, many airline widgets) and names resolved
    through aria-labelledby (Workday, most React form libraries) are included.
    """
    from dom_extraction.snapshot import collect_form_fields

    start = asyncio.get_event_loop().time()
    rows: list[str] = []

    for frame_index, frame in enumerate(unique_frames(page)):
        for f in await collect_form_fields(frame):
            kind = f.get("type") or "text"
            if f.get("tag") not in ("input", "select", "textarea"):
                if kind in ("submit", "button", "reset", "image") or f.get("tag") == "button":
                    continue
                kind = f.get("role") or kind
            if kind in ("submit", "button", "reset", "image"):
                continue
            if f.get("checked") is not None:
                state = "checked" if f.get("checked") else "unchecked"
            elif kind in ("select", "combobox", "listbox"):
                selected = (f.get("selectedValue") or "").strip()
                state = f"selected: {selected}" if selected else "empty"
            elif kind == "file":
                state = f"file: {f.get('fileName')}" if f.get("filled") else "no file"
            elif f.get("filled"):
                state = f"filled ({f.get('valueLen') or '?'} chars)"
            else:
                state = "empty"
            flags = []
            if f.get("required"):
                flags.append("required")
            if f.get("disabled") or f.get("readonly"):
                flags.append("readonly")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            prefix = f"frame{frame_index} " if frame_index else ""
            name = str(f.get("name") or f.get("fallbackId") or "")[:80]
            rows.append(f"- {prefix}{kind} \"{name}\": {state}{suffix}")

    if not rows:
        return _ok("read_form", {}, "No form fields found on the page.", start, verified=True, extracted_text="")

    empty = sum(1 for r in rows if r.endswith("empty") or ": empty" in r or "no file" in r)
    summary = f"{len(rows)} field(s), {empty} still empty."
    return _ok("read_form", {}, summary, start, verified=True, extracted_text=summary + "\n" + "\n".join(rows))


# ---------------------------------------------------------------------------
# read_page
# ---------------------------------------------------------------------------

async def do_read_page(page: Page, section: int = 1) -> ExecutionOutput:
    """Render one section of the paginated page snapshot.

    The snapshot shown each step is budget-limited. It used to be truncated in
    DOM order, so on a long form the unfilled fields at the bottom were exactly
    what got cut, with nothing telling the model they existed. Now the snapshot
    names its section count and this action fetches the rest.
    """
    from dom_extraction.snapshot import capture_page_snapshot

    start = asyncio.get_event_loop().time()
    args = {"section": section}
    try:
        snapshot = await capture_page_snapshot(page)
    except PlaywrightError as exc:
        return _fail("read_page", args, f"Could not snapshot the page: {str(exc).splitlines()[0]}", "unknown", start)

    wanted = max(1, int(section or 1))
    total = snapshot.section_count(max_chars=4000)
    body = snapshot.render(max_chars=4000, section=wanted)
    shown = min(wanted, total)
    message = f"Section {shown} of {total} ({len(snapshot.elements)} elements total)."
    if wanted > total:
        message = f"Section {wanted} does not exist; showing last section {shown} of {total}."
    return _ok("read_page", args, message, start, verified=True, extracted_text=body)


# ---------------------------------------------------------------------------
# scroll_to
# ---------------------------------------------------------------------------

async def do_scroll_to(
    page: Page,
    role: Optional[str],
    name: Optional[str],
    nth: Optional[int] = None,
) -> ExecutionOutput:
    start = asyncio.get_event_loop().time()
    args = {"role": role, "name": name}
    res = await resolve_target(page, role, name, nth=nth)
    if not res.ok:
        return _resolution_failure("scroll_to", args, res, start)
    try:
        await res.locator.scroll_into_view_if_needed(timeout=ELEMENT_TIMEOUT_MS)
    except PlaywrightError as exc:
        return _fail("scroll_to", args, f"Could not scroll to '{name}': {str(exc).splitlines()[0]}", "not_interactable", start)
    return _ok("scroll_to", args, f"Scrolled {role} '{name}' into view.", start, verified=True)


# ---------------------------------------------------------------------------
# tabs
# ---------------------------------------------------------------------------

async def do_list_tabs(page: Page) -> ExecutionOutput:
    start = asyncio.get_event_loop().time()
    pages = page.context.pages
    lines = []
    for i, p in enumerate(pages):
        marker = " (current)" if p is page else ""
        try:
            title = await p.title()
        except Exception:
            title = ""
        lines.append(f"- {i}: {title[:60]} {p.url[:80]}{marker}")
    body = "\n".join(lines)
    return _ok("list_tabs", {}, f"{len(pages)} tab(s) open.", start, verified=True, extracted_text=body)


async def do_switch_tab(page: Page, index: Optional[int]) -> tuple[ExecutionOutput, Optional[Page]]:
    """Bring a tab to the front.

    Tab handling used to be an implicit hijack: after any successful action, if a
    second page existed the runtime silently switched to `pages[-1]`. An ad popup
    or an OAuth window became the agent's page with no way back, and it picked the
    last page rather than the one that opened.
    """
    start = asyncio.get_event_loop().time()
    args = {"index": index}
    pages = page.context.pages
    if index is None or not (0 <= index < len(pages)):
        return (
            _fail("switch_tab", args, f"Tab {index} does not exist; {len(pages)} tab(s) open.", "ambiguous_step", start),
            None,
        )
    target = pages[index]
    try:
        await target.bring_to_front()
    except Exception:
        pass
    return (
        _ok("switch_tab", args, f"Switched to tab {index}: {target.url[:100]}", start, verified=True),
        target,
    )


async def do_close_tab(page: Page, index: Optional[int]) -> tuple[ExecutionOutput, Optional[Page]]:
    start = asyncio.get_event_loop().time()
    args = {"index": index}
    pages = page.context.pages
    if len(pages) <= 1:
        return _fail("close_tab", args, "Refusing to close the only open tab.", "ambiguous_step", start), None
    if index is None or not (0 <= index < len(pages)):
        return _fail("close_tab", args, f"Tab {index} does not exist.", "ambiguous_step", start), None

    target = pages[index]
    was_current = target is page
    try:
        await target.close()
    except Exception as exc:
        return _fail("close_tab", args, f"Could not close tab {index}: {exc}", "unknown", start), None

    remaining = page.context.pages
    new_page = remaining[-1] if was_current and remaining else None
    return _ok("close_tab", args, f"Closed tab {index}.", start, verified=True), new_page


__all__ = [
    "do_click",
    "do_fill",
    "do_set_checkbox",
    "do_select_option",
    "do_upload_file",
    "do_wait_for",
    "do_read_form",
    "do_read_page",
    "do_scroll_to",
    "do_list_tabs",
    "do_switch_tab",
    "do_close_tab",
    "element_inventory",
]
