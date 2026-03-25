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
                            locator = fr.get_by_role(rt, name=nt).first
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

# maybe pass in the focused input field??
async def handle_type(page: Page, text: str) -> ExecutionOutput:
    """
    Type text into focused input field.

    Args:
        page: Playwright page instance
        text: Text to type

    Returns:
        ExecutionOutput with result
    """
    start = asyncio.get_event_loop().time()

    try:
        # Prefer filling a visible input field instead of relying on current focus.
        # Also try across frames, since many UCF/PeopleSoft login UIs render form
        # fields inside iframes.
        is_emailish = "@" in (text or "")

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

        preferred_selectors = username_selectors if is_emailish else password_selectors
        other_selectors = password_selectors if is_emailish else username_selectors

        target = None
        for fr in frames:
            target = await _find_visible_in_frame(fr, preferred_selectors)
            if target is not None:
                break
            target = await _find_visible_in_frame(fr, other_selectors)
            if target is not None:
                break

        if target is not None:
            try:
                await target.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                pass

            try:
                await target.wait_for(state="visible", timeout=5000)
            except Exception:
                raise

            try:
                await target.fill(text, timeout=5000)
            except Exception:
                await target.click(timeout=5000)
                await target.fill(text, timeout=5000)
        else:
            # Truthful failure: don't type blindly into whatever currently has focus.
            # This prevents illusory/incorrect form filling when login fields haven't rendered yet.
            return ExecutionOutput(
                action="type",
                args={"text": text},
                status="failure",
                error_type="element_not_found",
                message="No visible login email/username or password field found to type into.",
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
            message=f"Typed '{text}'",
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
