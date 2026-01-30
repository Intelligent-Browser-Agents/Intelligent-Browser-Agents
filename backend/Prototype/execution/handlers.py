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
        await page.goto(url, timeout=10000)
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
    Click a DOM element identified by ARIA role and name.

    Args:
        page: Playwright page instance
        role: ARIA role (button, link, textbox, etc.)
        name: Accessible name or label

    Returns:
        ExecutionOutput with result
    """
    start = asyncio.get_event_loop().time()

    try:
        if role and name:
            await page.get_by_role(role, name=name).click(timeout=3000)
            elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
            return ExecutionOutput(
                action="click",
                args={"role": role, "name": name},
                status="success",
                error_type="none",
                message=f"Clicked {role} '{name}'",
                execution_time_ms=elapsed
            )


        if role:
            await page.get_by_role(role).click(timeout=3000)
            elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
            return ExecutionOutput(
                action="click",
                args={"role": role, "name": name},
                status="success",
                error_type="none",
                message=f"Clicked {role}",
                execution_time_ms=elapsed
            )

        if name:
            await page.get_by_text(name).click(timeout=3000)
            elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
            return ExecutionOutput(
                action="click",
                args={"role": role, "name": name},
                status="success",
                error_type="none",
                message=f"Clicked element with text '{name}'",
                execution_time_ms=elapsed
            )

        # No valid target
        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionOutput(
            action="click",
            args={"role": role, "name": name},
            status="failure",
            error_type="ambiguous_step",
            message="No role or name provided for click",
            execution_time_ms=elapsed
        )

    except Exception as e:
        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionOutput(
            action="click",
            args={"role": role, "name": name},
            status="failure",
            error_type="element_not_found",
            message=f"Could not click element: {str(e)}",
            execution_time_ms=elapsed
        )


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

    try:
        search_box = page.get_by_role("combobox", name="Search")
        await search_box.click()
        await search_box.fill(query)
        await page.keyboard.press("Enter")

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
        try:
            await page.keyboard.type(query)
            await page.keyboard.press("Enter")

            elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
            return ExecutionOutput(
                action="search",
                args={"text": query},
                status="success",
                error_type="none",
                message=f"Searched for '{query}' (fallback)",
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
