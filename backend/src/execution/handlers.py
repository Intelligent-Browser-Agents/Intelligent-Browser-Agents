"""
Playwright action handlers for browser automation.

Each handler executes a specific browser action and returns a structured result.
"""

import asyncio
import re
from playwright.async_api import Page
from .models import ExecutionOutput


async def handle_navigate(page: Page, url: str) -> ExecutionOutput:
    """
    Navigate to a URL.

    Args:
        page: Playwright page instance
        url: Target URL

    Returns:
        ExecutionOutput with result
    """
    start = asyncio.get_event_loop().time()

    try:
        await page.goto(url, timeout=15000, wait_until="domcontentloaded")
        # Give dynamic login portals a short stabilization window before verifier snapshot.
        try:
            await page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass
        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)

        return ExecutionOutput(
            action="navigate",
            args={"url": url},
            status="success",
            error_type="none",
            message=f"Navigated to {url}",
            execution_time_ms=elapsed
        )
    except Exception as e:
        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)

        return ExecutionOutput(
            action="navigate",
            args={"url": url},
            status="failure",
            error_type="navigation_blocked",
            message=f"Failed to navigate: {str(e)}",
            execution_time_ms=elapsed
        )


async def handle_click(page: Page, role: str, name: str) -> ExecutionOutput:
    """
    Click a DOM element identified by ARIA role and accessible name.
    Uses .first to target the first match and waits for visibility before clicking.
    """
    start = asyncio.get_event_loop().time()
    timeout_ms = 12000
    raw_role = (role or "").strip().lower()
    # LLMs often emit HTML tag names; Playwright expects ARIA roles (e.g. <a> → link).
    _ROLE_ALIASES = {
        "a": "link",
        "anchor": "link",
        "hyperlink": "link",
    }
    role_normalized = _ROLE_ALIASES.get(raw_role, raw_role)
    name_trimmed = (name or "").strip()
    short_name = len(name_trimmed) <= 3 if name_trimmed else False

    def _elapsed():
        return int((asyncio.get_event_loop().time() - start) * 1000)

    def _name_variants(raw: str) -> list[str]:
        s = (raw or "").strip()
        # Common decorative glyphs that may appear/disappear between HTML text and
        # accessibility label rendering.
        stripped = s.lstrip("🔒").strip()
        variants = [s]
        if stripped and stripped != s:
            variants.append(stripped)
        # Remove trailing punctuation/artifacts.
        variants.append(variants[-1].rstrip(" .,:;!?"))
        # De-dup while preserving order.
        seen = set()
        out: list[str] = []
        for v in variants:
            v = (v or "").strip()
            if v and v not in seen:
                seen.add(v)
                out.append(v)
        return out

    def _role_attempts(r: str) -> list[str]:
        rr = (r or "").strip().lower()
        if not rr:
            return []
        rr = _ROLE_ALIASES.get(rr, rr)
        # If our discovery inferred link vs button, attempt both.
        if rr == "link":
            return [rr, "button", "tab"]
        if rr == "button":
            return [rr, "link", "tab"]
        if rr == "tab":
            return [rr, "button", "link"]
        # div/span/etc. from the a11y tree or LLM guesses — try real interactives first.
        if rr in ("div", "span", "section", "article", "group", "generic", "presentation"):
            return ["link", "button", "tab", rr]
        return [rr]

    async def _settle_after_navigation():
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass
        try:
            await page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass
        await asyncio.sleep(0.6)

    async def _try_locator_click(locator) -> bool:
        try:
            try:
                await locator.scroll_into_view_if_needed(timeout=timeout_ms)
            except Exception:
                pass
            await locator.wait_for(state="visible", timeout=timeout_ms)
            await locator.click(timeout=timeout_ms)
            return True
        except Exception:
            try:
                await locator.scroll_into_view_if_needed(timeout=timeout_ms)
                await locator.click(timeout=timeout_ms, force=True)
                return True
            except Exception:
                return False

    frames = [page.main_frame] + list(page.frames)

    try:
        if role_normalized and name_trimmed:
            role_tries = _role_attempts(role_normalized)
            name_tries = _name_variants(name_trimmed)
            last_error: str | None = None

            for fr in frames:
                for rt in role_tries:
                    for nt in name_tries:
                        try:
                            locator = fr.get_by_role(rt, name=nt, exact=short_name).first
                            if await _try_locator_click(locator):
                                await _settle_after_navigation()
                                return ExecutionOutput(
                                    action="click",
                                    args={"role": role_normalized, "name": name_trimmed},
                                    status="success",
                                    error_type="none",
                                    message=f"Clicked {role_normalized} '{name_trimmed}'",
                                    execution_time_ms=_elapsed(),
                                )
                        except Exception as e:
                            last_error = str(e)
                            continue

            # Substring / regex accessible name (labels differ slightly from training text).
            # Skip for very short labels (e.g. "To") to avoid misclicks such as "To Do".
            if not short_name:
                for fr in frames:
                    for rt in ("link", "button", "tab"):
                        for nt in name_tries:
                            if len(nt) < 2:
                                continue
                            try:
                                pat = re.compile(r".*" + re.escape(nt) + r".*", re.I | re.DOTALL)
                                locator = fr.get_by_role(rt, name=pat).first
                                if await _try_locator_click(locator):
                                    await _settle_after_navigation()
                                    return ExecutionOutput(
                                        action="click",
                                        args={"role": role_normalized, "name": name_trimmed},
                                        status="success",
                                        error_type="none",
                                        message=f"Clicked {rt} (name~'{nt}') for '{name_trimmed}'",
                                        execution_time_ms=_elapsed(),
                                    )
                            except Exception as e:
                                last_error = str(e)
                                continue

            # get_by_text fallback when role was wrong or name is visible text only.
            # Do not use this for text-entry roles; labels often resolve to chips/buttons.
            disallow_text_fallback_roles = {"textbox", "searchbox", "combobox"}
            if role_normalized not in disallow_text_fallback_roles:
                for fr in frames:
                    for nt in name_tries:
                        try:
                            loc = fr.get_by_text(nt, exact=True).first
                            if await _try_locator_click(loc):
                                await _settle_after_navigation()
                                return ExecutionOutput(
                                    action="click",
                                    args={"role": role_normalized, "name": name_trimmed},
                                    status="success",
                                    error_type="none",
                                    message=f"Clicked element with exact text '{nt}'",
                                    execution_time_ms=_elapsed(),
                                )
                        except Exception as e:
                            last_error = str(e)
                            continue
                        if not short_name:
                            try:
                                loc = fr.get_by_text(nt, exact=False).first
                                if await _try_locator_click(loc):
                                    await _settle_after_navigation()
                                    return ExecutionOutput(
                                        action="click",
                                        args={"role": role_normalized, "name": name_trimmed},
                                        status="success",
                                        error_type="none",
                                        message=f"Clicked element matching text '{nt}'",
                                        execution_time_ms=_elapsed(),
                                    )
                            except Exception as e:
                                last_error = str(e)
                                continue

            # Last resort: anchors/buttons whose visible text matches (dashboard tiles).
            if not short_name:
                for fr in frames:
                    for nt in name_tries:
                        if len(nt) < 2:
                            continue
                        try:
                            pat = re.compile(re.escape(nt), re.I)
                            for tag in ("a", "button"):
                                loc = fr.locator(tag).filter(has_text=pat).first
                                if await _try_locator_click(loc):
                                    await _settle_after_navigation()
                                    return ExecutionOutput(
                                        action="click",
                                        args={"role": role_normalized, "name": name_trimmed},
                                        status="success",
                                        error_type="none",
                                        message=f"Clicked {tag} matching text '{nt}'",
                                        execution_time_ms=_elapsed(),
                                    )
                        except Exception as e:
                            last_error = str(e)
                            continue

            # If we got here, nothing matched anywhere (including iframes).
            return ExecutionOutput(
                action="click",
                args={"role": role_normalized, "name": name_trimmed},
                status="failure",
                error_type="element_not_found",
                message=f"Could not click element in any frame: {last_error or 'not found'}",
                execution_time_ms=_elapsed(),
            )

        if role_normalized:
            last_error: str | None = None
            role_tries = _role_attempts(role_normalized)
            for fr in frames:
                for rt in role_tries:
                    try:
                        locator = fr.get_by_role(rt).first
                        await locator.wait_for(state="visible", timeout=timeout_ms)
                        await locator.click(timeout=timeout_ms)
                        try:
                            await page.wait_for_load_state("domcontentloaded", timeout=3000)
                        except Exception:
                            pass
                        try:
                            await page.wait_for_load_state("networkidle", timeout=3000)
                        except Exception:
                            pass
                        await asyncio.sleep(0.6)
                        return ExecutionOutput(
                            action="click",
                            args={"role": role_normalized, "name": name_trimmed or ""},
                            status="success",
                            error_type="none",
                            message=f"Clicked first {role_normalized}",
                            execution_time_ms=_elapsed(),
                        )
                    except Exception as e:
                        last_error = str(e)
                        continue

            try:
                if last_error:
                    raise RuntimeError(last_error)
            except Exception as e:
                return ExecutionOutput(
                    action="click",
                    args={"role": role_normalized, "name": name_trimmed or ""},
                    status="failure",
                    error_type="element_not_found",
                    message=f"Could not click role '{role_normalized}': {str(e)}",
                    execution_time_ms=_elapsed(),
                )

        if name_trimmed:
            last_error: str | None = None
            for fr in frames:
                for nt in _name_variants(name_trimmed):
                    try:
                        locator = fr.get_by_text(nt).first
                        await locator.wait_for(state="visible", timeout=timeout_ms)
                        await locator.click(timeout=timeout_ms)
                        try:
                            await page.wait_for_load_state("domcontentloaded", timeout=3000)
                        except Exception:
                            pass
                        try:
                            await page.wait_for_load_state("networkidle", timeout=3000)
                        except Exception:
                            pass
                        await asyncio.sleep(0.6)
                        return ExecutionOutput(
                            action="click",
                            args={"role": role_normalized or "", "name": name_trimmed},
                            status="success",
                            error_type="none",
                            message=f"Clicked element with text '{name_trimmed}'",
                            execution_time_ms=_elapsed(),
                        )
                    except Exception as e:
                        last_error = str(e)
                        continue

            return ExecutionOutput(
                action="click",
                args={"role": role_normalized or "", "name": name_trimmed},
                status="failure",
                error_type="element_not_found",
                message=f"Could not click element by text: {last_error or 'not found'}",
                execution_time_ms=_elapsed(),
            )

        return ExecutionOutput(
            action="click",
            args={"role": "", "name": ""},
            status="failure",
            error_type="ambiguous_step",
            message="No role or name provided for click",
            execution_time_ms=_elapsed(),
        )

    except Exception as e:
        return ExecutionOutput(
            action="click",
            args={"role": role_normalized or "", "name": name_trimmed or ""},
            status="failure",
            error_type="element_not_found",
            message=f"Could not click element: {str(e)}",
            execution_time_ms=_elapsed(),
        )

def _looks_like_password(text: str) -> bool:
    """Heuristic: passwords typically mix cases, digits, and symbols."""
    has_upper = any(c.isupper() for c in text)
    has_lower = any(c.islower() for c in text)
    has_digit = any(c.isdigit() for c in text)
    has_symbol = any(not c.isalnum() and not c.isspace() for c in text)
    return has_upper and has_lower and has_digit and has_symbol and " " not in text


async def handle_type(page: Page, text: str) -> ExecutionOutput:
    """
    Type text into the appropriate input field.

    Strategy:
      1. If an input/textarea is currently focused (LLM just clicked it), use that.
      2. If text looks like credentials, find the matching login field.
      3. Otherwise find any visible general text input.
    """
    start = asyncio.get_event_loop().time()

    try:
        text = (text or "").strip()
        is_email_like = "@" in text
        is_password_like = _looks_like_password(text)
        is_credential = is_email_like or is_password_like

        password_selectors = ["input[type='password']", "input[name*='password' i]"]
        username_selectors = [
            "input[type='email']",
            "input[name*='email' i]",
            "input[id*='email' i]",
            "input[name*='user' i]",
            "input[id*='user' i]",
            "input[name*='username' i]",
            "input[id*='username' i]",
            "input[autocomplete*='username' i]",
            "input[autocomplete*='email' i]",
        ]
        general_selectors = [
            "input[type='search']",
            "input[type='text']",
            "input[role='combobox']",
            "input[role='searchbox']",
            "input:not([type='hidden']):not([type='checkbox']):not([type='radio']):not([type='submit']):not([type='button'])",
            "textarea",
            "[contenteditable='true']",
        ]
        contact_selectors = [
            "input[aria-label*='recipient' i]",
            "input[name*='recipient' i]",
            "input[placeholder*='recipient' i]",
            "input[aria-label*='add recipients' i]",
            "input[placeholder*='add recipients' i]",
            "input[aria-label*='to' i]",
            "input[name='to' i]",
            "input[placeholder*='to' i]",
            "input[aria-label*='email' i]",
            "input[name*='email' i]",
            "input[placeholder*='email' i]",
            "input[aria-label*='contact' i]",
            "input[placeholder*='contact' i]",
            "input[aria-label*='address' i]",
            "input[placeholder*='address' i]",
            "input[aria-label*='phone' i]",
            "input[name*='phone' i]",
            "input[placeholder*='phone' i]",
        ]
        compose_recipient_selectors = [
            "input[aria-label='to' i]",
            "input[name='to' i]",
            "input[placeholder*='to' i]",
            "input[aria-label*='recipient' i]",
            "input[name*='recipient' i]",
            "input[placeholder*='recipient' i]",
            "input[aria-label*='add recipients' i]",
            "input[placeholder*='add recipients' i]",
            "[contenteditable='true'][aria-label*='to' i]",
            "[contenteditable='true'][aria-label*='recipient' i]",
            "[role='combobox'][aria-label*='add recipients' i]",
            "[role='textbox'][aria-label*='to' i]",
        ]
        title_selectors = [
            "input[aria-label*='subject' i]",
            "textarea[aria-label*='subject' i]",
            "input[name*='subject' i]",
            "textarea[name*='subject' i]",
            "input[placeholder*='subject' i]",
            "textarea[placeholder*='subject' i]",
            "input[aria-label*='title' i]",
            "input[name*='title' i]",
            "input[placeholder*='title' i]",
        ]
        code_selectors = [
            "input[aria-label*='code' i]",
            "input[name*='code' i]",
            "input[placeholder*='code' i]",
            "input[aria-label*='otp' i]",
            "input[name*='otp' i]",
            "input[placeholder*='otp' i]",
            "input[aria-label*='verification' i]",
            "input[name*='verification' i]",
            "input[placeholder*='verification' i]",
        ]
        body_selectors = [
            "textarea[aria-label*='message' i]",
            "textarea[name*='message' i]",
            "textarea[placeholder*='message' i]",
            "[contenteditable='true'][aria-label*='message' i]",
            "[contenteditable='true'][role='textbox']",
            "textarea",
            "[contenteditable='true']",
        ]

        frames = [page.main_frame] + list(page.frames)

        async def _find_visible_in_frame(frame, selectors: list[str]):
            for sel in selectors:
                try:
                    loc = frame.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        return loc
                except Exception:
                    continue
            return None

        async def _is_search_like_input(locator) -> bool:
            try:
                meta = await locator.evaluate(
                    """el => {
                        const bits = [
                            el.getAttribute && el.getAttribute('aria-label'),
                            el.getAttribute && el.getAttribute('placeholder'),
                            el.getAttribute && el.getAttribute('name'),
                            el.getAttribute && el.getAttribute('role'),
                            el.id,
                            el.className,
                        ].filter(Boolean).join(' ').toLowerCase();
                        return bits;
                    }"""
                )
            except Exception:
                return False
            return any(tok in (meta or "") for tok in ("search", "find", "lookup", "directory"))

        async def _find_visible_contact_in_frame(frame, selectors: list[str], avoid_search_like: bool):
            for sel in selectors:
                try:
                    loc = frame.locator(sel).first
                    if await loc.count() == 0 or not await loc.is_visible():
                        continue
                    if avoid_search_like and await _is_search_like_input(loc):
                        continue
                    return loc
                except Exception:
                    continue
            return None

        async def _looks_empty(locator) -> bool:
            try:
                return await locator.evaluate(
                    """el => {
                        const tag = (el.tagName || '').toLowerCase();
                        if (tag === 'input' || tag === 'textarea') {
                            return !((el.value || '').trim());
                        }
                        if (el.isContentEditable) {
                            return !((el.innerText || '').trim());
                        }
                        return true;
                    }"""
                )
            except Exception:
                return True

        async def _find_visible_prefer_empty(frame, selectors: list[str]):
            candidate = await _find_visible_in_frame(frame, selectors)
            if candidate is None:
                return None
            try:
                if await _looks_empty(candidate):
                    return candidate
            except Exception:
                return candidate
            return candidate

        async def _get_page_hint_text() -> str:
            try:
                return await page.evaluate(
                    """() => {
                        const t = (document.body && (document.body.innerText || document.body.textContent)) || '';
                        return t.slice(0, 4000).toLowerCase();
                    }"""
                )
            except Exception:
                return ""

        async def _get_focused_info() -> dict:
            try:
                return await page.evaluate(
                    """() => {
                        const el = document.activeElement;
                        if (!el) return { tag: '', type: '', meta: '', isContentEditable: false };
                        const tag = (el.tagName || '').toLowerCase();
                        const type = (el.type || '').toLowerCase();
                        const meta = [
                            el.getAttribute && el.getAttribute('aria-label'),
                            el.getAttribute && el.getAttribute('placeholder'),
                            el.getAttribute && el.getAttribute('name'),
                            el.id,
                            el.getAttribute && el.getAttribute('role'),
                        ].filter(Boolean).join(' ').toLowerCase();
                        return {
                            tag,
                            type,
                            meta,
                            isContentEditable: !!el.isContentEditable,
                        };
                    }"""
                )
            except Exception:
                return {"tag": "", "type": "", "meta": "", "isContentEditable": False}

        async def _describe_target(locator) -> str:
            try:
                return await locator.evaluate(
                    """el => {
                        const tag = (el.tagName || '').toLowerCase();
                        const role = (el.getAttribute && el.getAttribute('role')) || '';
                        const label = (el.getAttribute && el.getAttribute('aria-label')) || '';
                        const placeholder = (el.getAttribute && el.getAttribute('placeholder')) || '';
                        const name = (el.getAttribute && el.getAttribute('name')) || '';
                        const id = el.id || '';
                        const t = (el.type || '').toLowerCase();
                        const contentEditable = !!el.isContentEditable;
                        const bits = [
                            tag && `tag=${tag}`,
                            role && `role=${role}`,
                            label && `label=${label}`,
                            placeholder && `placeholder=${placeholder}`,
                            name && `name=${name}`,
                            id && `id=${id}`,
                            t && `type=${t}`,
                            contentEditable && 'contenteditable=true',
                        ].filter(Boolean);
                        return bits.join(', ') || 'unknown target';
                    }"""
                )
            except Exception:
                return "unknown target"

        def _looks_auth_context(hint_text: str) -> bool:
            if not hint_text:
                return False
            auth_tokens = ("sign in", "log in", "login", "password", "authenticate", "verification")
            compose_tokens = ("subject", "message", "recipient", "to:", "send")
            has_auth = any(tok in hint_text for tok in auth_tokens)
            has_compose = any(tok in hint_text for tok in compose_tokens)
            return has_auth and not has_compose

        def _looks_compose_context(hint_text: str) -> bool:
            if not hint_text:
                return False
            compose_tokens = ("new mail", "compose", "subject", "message body", "recipient", "to:", "send")
            return any(tok in hint_text for tok in compose_tokens)

        def _infer_text_intent(value: str) -> str:
            v = (value or "").strip()
            if not v:
                return "generic"
            if _looks_like_password(v):
                return "password"
            if re.fullmatch(r"\d{4,8}", v):
                return "code"
            if "@" in v:
                return "contact"
            words = len(re.findall(r"\S+", v))
            longish = len(v) >= 40 or words >= 8 or any(p in v for p in (".", "!", "?"))
            if longish:
                return "body"
            return "title"

        target = None
        page_hint = await _get_page_hint_text()
        auth_context = _looks_auth_context(page_hint)
        compose_context = _looks_compose_context(page_hint)
        text_intent = _infer_text_intent(text)
        focused_info = await _get_focused_info()
        focused_meta = (focused_info.get("meta") or "").lower()
        focused_tag = (focused_info.get("tag") or "").lower()
        focused_type = (focused_info.get("type") or "").lower()
        focused_is_typeable_input = focused_tag in ("input", "textarea") and focused_type not in (
            "hidden", "checkbox", "radio", "submit", "button", "file", "image",
        )
        focused_is_contenteditable = bool(focused_info.get("isContentEditable"))
        focused_is_contactish = any(tok in focused_meta for tok in ("to", "recipient", "contact", "email", "address", "phone"))
        focused_is_subjectish = any(tok in focused_meta for tok in ("subject", "title"))
        focused_is_bodyish = any(tok in focused_meta for tok in ("message", "body", "content"))
        focused_is_codeish = any(tok in focused_meta for tok in ("code", "otp", "verification"))

        # Respect explicit focus intent for non-credential typing. This avoids
        # typing body text into a different semantic field selected by heuristics.
        if not is_credential and (focused_is_typeable_input or focused_is_contenteditable):
            target = page.locator(":focus").first
            if await target.count() == 0:
                target = None

        # For credential typing, only trust focus when it semantically matches.
        if target is None and text_intent == "contact" and focused_is_typeable_input and focused_is_contactish:
            target = page.locator(":focus").first
            if await target.count() == 0:
                target = None
        if target is None and text_intent == "password" and focused_is_typeable_input and (
            "password" in focused_meta or focused_type == "password"
        ):
            target = page.locator(":focus").first
            if await target.count() == 0:
                target = None
        if target is None and text_intent == "code" and focused_is_typeable_input and focused_is_codeish:
            target = page.locator(":focus").first
            if await target.count() == 0:
                target = None

        # 0. Semantic field targeting first, to avoid typing into unrelated focus.
        if target is None and text_intent == "contact":
            for fr in frames:
                if auth_context:
                    target = await _find_visible_in_frame(fr, username_selectors)
                elif compose_context:
                    target = await _find_visible_contact_in_frame(
                        fr, compose_recipient_selectors, avoid_search_like=True
                    )
                    if target is None:
                        target = await _find_visible_contact_in_frame(
                            fr, contact_selectors, avoid_search_like=True
                        )
                else:
                    target = await _find_visible_prefer_empty(fr, contact_selectors)
                    if target is None:
                        target = await _find_visible_in_frame(fr, username_selectors)
                if target is not None:
                    break
        elif target is None and text_intent == "password":
            for fr in frames:
                target = await _find_visible_in_frame(fr, password_selectors)
                if target is not None:
                    break
        elif target is None and text_intent == "code":
            for fr in frames:
                target = await _find_visible_in_frame(fr, code_selectors)
                if target is not None:
                    break
        elif target is None:
            # For general text, prefer semantic form fields by intent.
            if (focused_is_subjectish or focused_is_bodyish) and (focused_is_typeable_input or focused_is_contenteditable):
                target = page.locator(":focus").first
                if await target.count() == 0:
                    target = None
            if target is None and text_intent == "title":
                for fr in frames:
                    target = await _find_visible_prefer_empty(fr, title_selectors)
                    if target is not None:
                        break
            if target is None:
                for fr in frames:
                    target = await _find_visible_in_frame(fr, body_selectors)
                    if target is not None:
                        break

        # 1. Respect current focus only if semantic targeting didn't find a field.
        try:
            if target is None:
                focused_tag = await page.evaluate(
                    "() => { const el = document.activeElement; "
                    "return el ? el.tagName.toLowerCase() : ''; }"
                )
                if focused_tag in ("input", "textarea"):
                    focused_type = await page.evaluate(
                        "() => (document.activeElement.type || '').toLowerCase()"
                    )
                    typeable = focused_type not in (
                        "hidden", "checkbox", "radio", "submit", "button", "file", "image",
                    )
                    if typeable:
                        target = page.locator(":focus").first
                        if await target.count() == 0:
                            target = None
                elif focused_tag and await page.evaluate(
                    "() => document.activeElement.isContentEditable"
                ):
                    target = page.locator(":focus").first
                    if await target.count() == 0:
                        target = None
        except Exception:
            pass

        # 2. If no semantic/focus target, use broader context-appropriate selectors.
        if target is None:
            if is_credential:
                preferred = username_selectors if "@" in (text or "") else password_selectors
                other = password_selectors if "@" in (text or "") else username_selectors
                for fr in frames:
                    target = await _find_visible_in_frame(fr, preferred)
                    if target is not None:
                        break
                    target = await _find_visible_in_frame(fr, other)
                    if target is not None:
                        break
            else:
                for fr in frames:
                    target = await _find_visible_in_frame(fr, general_selectors)
                    if target is not None:
                        break

        # 3. Last resort: try whichever selector group we haven't tried yet.
        if target is None:
            fallback = general_selectors if is_credential else (username_selectors + password_selectors)
            for fr in frames:
                target = await _find_visible_in_frame(fr, fallback)
                if target is not None:
                    break

        if target is not None:
            target_desc = await _describe_target(target)
            try:
                await target.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass

            try:
                await target.wait_for(state="visible", timeout=5000)
            except Exception:
                raise

            try:
                if focused_is_contenteditable or "contenteditable=true" in target_desc:
                    await target.click(timeout=5000)
                    await page.keyboard.press("Control+A")
                    await page.keyboard.type(text)
                else:
                    await target.fill(text, timeout=5000)
            except Exception:
                await target.click(timeout=5000)
                try:
                    if focused_is_contenteditable or "contenteditable=true" in target_desc:
                        await page.keyboard.press("Control+A")
                        await page.keyboard.type(text)
                    else:
                        await target.fill(text, timeout=5000)
                except Exception:
                    await target.type(text, timeout=5000)
        else:
            return ExecutionOutput(
                action="type",
                args={"text": text},
                status="failure",
                error_type="element_not_found",
                message="No visible text input field found to type into.",
                execution_time_ms=int((asyncio.get_event_loop().time() - start) * 1000),
            )

        # Give the UI a moment to react to the input.
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=1500)
        except Exception:
            pass
        await asyncio.sleep(0.4)
        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)

        return ExecutionOutput(
            action="type",
            args={"text": text},
            status="success",
            error_type="none",
            message=f"Typed '{text}' into {target_desc}",
            execution_time_ms=elapsed
        )
    except Exception as e:
        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)

        return ExecutionOutput(
            action="type",
            args={"text": text},
            status="failure",
            error_type="tool_limit",
            message=f"Failed to type: {str(e)}",
            execution_time_ms=elapsed
        )


async def handle_search(page: Page, query: str) -> ExecutionOutput:
    """
    Execute search query on Google or similar search interface.

    Args:
        page: Playwright page instance
        query: Search query

    Returns:
        ExecutionOutput with result
    """
    start = asyncio.get_event_loop().time()

    selector_candidates = [
        "input[name='q']",
        "textarea[name='q']",
        "input[type='search']",
        "input[aria-label*='Search' i]",
        "textarea[aria-label*='Search' i]",
        "#searchbox_input",
        "#search_form_input_homepage",
        "#sb_form_q",
    ]

    async def _submit_and_wait():
        """Wait for navigation/results after submitting search.

        Verifier relies on AFTER_STATE (accessibility snapshot). Search results are
        often rendered asynchronously, so we wait for network idle plus a small
        extra stabilization window.
        """
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        # Give results renderer a moment to populate.
        await asyncio.sleep(1.0)

    for selector in selector_candidates:
        try:
            locator = page.locator(selector).first
            if await locator.count() == 0:
                continue
            await locator.click(timeout=2500)
            await locator.fill(query, timeout=2500)
            await page.keyboard.press("Enter")
            await _submit_and_wait()
            elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
            return ExecutionOutput(
                action="search",
                args={"text": query},
                status="success",
                error_type="none",
                message=f"Searched for '{query}'",
                execution_time_ms=elapsed
            )
        except Exception:
            continue

    role_candidates = [
        ("searchbox", None),
        ("combobox", "Search"),
        ("textbox", "Search"),
    ]

    for role, name in role_candidates:
        try:
            locator = page.get_by_role(role, name=name) if name else page.get_by_role(role)
            target = locator.first
            await target.click(timeout=2500)
            await target.fill(query, timeout=2500)
            await page.keyboard.press("Enter")
            await _submit_and_wait()
            elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
            return ExecutionOutput(
                action="search",
                args={"text": query},
                status="success",
                error_type="none",
                message=f"Searched for '{query}'",
                execution_time_ms=elapsed
            )
        except Exception:
            continue

    try:
        await page.keyboard.type(query)
        await page.keyboard.press("Enter")
        await _submit_and_wait()
        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionOutput(
            action="search",
            args={"text": query},
            status="success",
            error_type="none",
            message=f"Searched for '{query}' (keyboard fallback)",
            execution_time_ms=elapsed
        )
    except Exception as e:
        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionOutput(
            action="search",
            args={"text": query},
            status="failure",
            error_type="element_not_found",
            message=f"Failed to search: {str(e)}",
            execution_time_ms=elapsed
        )


async def handle_scroll(page: Page, direction: str) -> ExecutionOutput:
    """
    Scroll page up or down.

    Args:
        page: Playwright page instance
        direction: "up" or "down"

    Returns:
        ExecutionOutput with result
    """
    start = asyncio.get_event_loop().time()

    try:
        delta = 800 if direction.lower() == "down" else -800
        await page.mouse.wheel(0, delta)
        await asyncio.sleep(0.3)

        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionOutput(
            action="scroll",
            args={"direction": direction},
            status="success",
            error_type="none",
            message=f"Scrolled {direction}",
            execution_time_ms=elapsed
        )
    except Exception as e:
        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)

        return ExecutionOutput(
            action="scroll",
            args={"direction": direction},
            status="failure",
            error_type="tool_limit",
            message=f"Failed to scroll: {str(e)}",
            execution_time_ms=elapsed
        )


async def handle_press_key(page: Page, key: str) -> ExecutionOutput:
    """
    Press a keyboard key.

    Args:
        page: Playwright page instance
        key: Key name (e.g., "Enter", "Escape", "ArrowDown")

    Returns:
        ExecutionOutput with result
    """
    start = asyncio.get_event_loop().time()

    try:
        await page.keyboard.press(key)
        # Some portals render state changes on Enter/Esc/etc without navigation.
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=1500)
        except Exception:
            pass
        await asyncio.sleep(0.3)

        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionOutput(
            action="press_key",
            args={"key": key},
            status="success",
            error_type="none",
            message=f"Pressed '{key}'",
            execution_time_ms=elapsed
        )
    except Exception as e:
        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)

        return ExecutionOutput(
            action="press_key",
            args={"key": key},
            status="failure",
            error_type="tool_limit",
            message=f"Failed to press key: {str(e)}",
            execution_time_ms=elapsed
        )


async def handle_go_back(page: Page) -> ExecutionOutput:
    """Navigate the browser back to the previous page."""
    start = asyncio.get_event_loop().time()
    try:
        await page.go_back(wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_load_state("networkidle", timeout=8000)
        await asyncio.sleep(1.0)
        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionOutput(
            action="go_back",
            args={},
            status="success",
            error_type="none",
            message=f"Navigated back to {page.url}",
            execution_time_ms=elapsed,
        )
    except Exception as e:
        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionOutput(
            action="go_back",
            args={},
            status="failure",
            error_type="tool_limit",
            message=f"Failed to go back: {str(e)}",
            execution_time_ms=elapsed,
        )


async def handle_wait(page: Page, seconds: float) -> ExecutionOutput:
    """
    Wait for specified duration.

    Args:
        page: Playwright page instance
        seconds: Duration in seconds

    Returns:
        ExecutionOutput with result
    """
    start = asyncio.get_event_loop().time()

    try:
        await asyncio.sleep(seconds)

        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionOutput(
            action="wait",
            args={"seconds": seconds},
            status="success",
            error_type="none",
            message=f"Waited {seconds}s",
            execution_time_ms=elapsed
        )
    except Exception as e:
        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)

        return ExecutionOutput(
            action="wait",
            args={"seconds": seconds},
            status="failure",
            error_type="tool_limit",
            message=f"Failed to wait: {str(e)}",
            execution_time_ms=elapsed
        )


async def handle_extract_content(page: Page, max_chars: int = 15000) -> ExecutionOutput:
    """
    Extract main text from the current page using the DOM extraction pipeline.
    Use when the plan step is to extract or gather information from the page.
    """
    from dom_extraction import dom_extractor

    start = asyncio.get_event_loop().time()
    try:
        text = await dom_extractor.get_page_text(page, max_chars=max_chars)
        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionOutput(
            action="extract_content",
            args={"max_chars": max_chars},
            status="success",
            error_type="none",
            message=f"Extracted {len(text)} characters from the page",
            execution_time_ms=elapsed,
            extracted_text=text if text else None,
        )
    except Exception as e:
        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionOutput(
            action="extract_content",
            args={},
            status="failure",
            error_type="unknown",
            message=f"Failed to extract content: {str(e)}",
            execution_time_ms=elapsed,
        )
