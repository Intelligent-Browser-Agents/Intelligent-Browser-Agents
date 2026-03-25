"""
Playwright action handlers for browser automation.

Each handler executes a specific browser action and returns a structured result.
"""

import asyncio
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
    timeout_ms = 5000
    role_normalized = (role or "").strip().lower()
    name_trimmed = (name or "").strip()

    def _elapsed():
        return int((asyncio.get_event_loop().time() - start) * 1000)

    try:
        if role_normalized and name_trimmed:
            locator = page.get_by_role(role_normalized, name=name_trimmed).first
            await locator.wait_for(state="visible", timeout=timeout_ms)
            await locator.click(timeout=timeout_ms)
            return ExecutionOutput(
                action="click",
                args={"role": role_normalized, "name": name_trimmed},
                status="success",
                error_type="none",
                message=f"Clicked {role_normalized} '{name_trimmed}'",
                execution_time_ms=_elapsed(),
            )

        if role_normalized:
            locator = page.get_by_role(role_normalized).first
            await locator.wait_for(state="visible", timeout=timeout_ms)
            await locator.click(timeout=timeout_ms)
            return ExecutionOutput(
                action="click",
                args={"role": role_normalized, "name": name_trimmed or ""},
                status="success",
                error_type="none",
                message=f"Clicked first {role_normalized}",
                execution_time_ms=_elapsed(),
            )

        if name_trimmed:
            locator = page.get_by_text(name_trimmed).first
            await locator.wait_for(state="visible", timeout=timeout_ms)
            await locator.click(timeout=timeout_ms)
            return ExecutionOutput(
                action="click",
                args={"role": role_normalized or "", "name": name_trimmed},
                status="success",
                error_type="none",
                message=f"Clicked element with text '{name_trimmed}'",
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
        await page.keyboard.type(text)
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
        """Wait for navigation/results after submitting search so AFTER_STATE sees the results page."""
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=8000)
            await asyncio.sleep(0.5)
        except Exception:
            pass

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
