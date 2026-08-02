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


async def handle_click(page: Page, role: str, name: str, nth: int | None = None) -> ExecutionOutput:
    """Click an element addressed by ARIA role and accessible name.

    Delegates to execution.actions.do_click. The 310-line cascade this replaces
    tried five strategies across every frame, role alias and name variant, taking
    `.first` at each step with a 12s actionability budget per attempt. That made a
    duplicate label unaddressable and a miss cost minutes.
    """
    from .actions import do_click

    return await do_click(page, role, name, nth=nth)


async def handle_type(page: Page, text: str) -> ExecutionOutput:
    """Type into whatever currently has focus.

    Retained only for the legacy `type` action, which carries no target. Prefer
    `fill(role, name, text)`: it names the field instead of guessing it.

    The 500+ lines removed here chose the target by classifying the *value* being
    typed against seven hardcoded selector lists, so "Edwin Villanueva" was read as
    a title and routed to the cover-letter textarea, and a password without a
    symbol failed the password test and went into a visible field.
    """
    from .actions import ELEMENT_TIMEOUT_MS

    start = asyncio.get_event_loop().time()

    def _elapsed() -> int:
        return int((asyncio.get_event_loop().time() - start) * 1000)

    value = "" if text is None else str(text)
    focused = page.locator(":focus")
    try:
        if not await focused.count():
            return ExecutionOutput(
                action="type",
                args={"text": value},
                status="failure",
                error_type="element_not_found",
                message=(
                    "Nothing is focused, so there is no field to type into. "
                    "Use fill(role, name, text) to address a field directly."
                ),
                execution_time_ms=_elapsed(),
                verified=False,
            )
        await focused.fill(value, timeout=ELEMENT_TIMEOUT_MS)
        try:
            actual = await focused.input_value(timeout=ELEMENT_TIMEOUT_MS)
        except Exception:
            actual = None
    except Exception as e:
        return ExecutionOutput(
            action="type",
            args={"text": value},
            status="failure",
            error_type="not_interactable",
            message=f"Failed to type: {str(e).splitlines()[0]}",
            execution_time_ms=_elapsed(),
            verified=False,
        )

    return ExecutionOutput(
        action="type",
        args={"text": value},
        status="success",
        error_type="none",
        # Never echo the typed value: this reaches the model context and the log.
        message=f"Typed {len(value)} character(s) into the focused field.",
        execution_time_ms=_elapsed(),
        verified=actual == value,
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
