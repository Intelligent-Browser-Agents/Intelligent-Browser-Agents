"""
Integration tests for execution agent handlers.

Tests actual browser actions with Playwright.
"""

import pytest
import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent.parent
execution_agent_path = backend_path / "Prototype" / "agents" / "execution-agent"
sys.path.insert(0, str(backend_path))
sys.path.insert(0, str(execution_agent_path))

from handlers import (
    handle_navigate,
    handle_click,
    handle_type,
    handle_search,
    handle_scroll,
    handle_press_key,
    handle_wait,
)


@pytest.mark.asyncio
async def test_handle_navigate_success(page):
    """Test successful navigation."""
    result = await handle_navigate(page, "https://example.com")

    assert result.status == "success"
    assert result.error_type == "none"
    assert result.action == "navigate"
    assert result.args["url"] == "https://example.com"
    assert "example.com" in result.message.lower()
    assert result.execution_time_ms > 0


@pytest.mark.asyncio
async def test_handle_navigate_failure(page):
    """Test navigation to invalid URL."""
    result = await handle_navigate(page, "https://invalid-domain-that-does-not-exist-12345.com")

    assert result.status == "failure"
    assert result.error_type == "navigation_blocked"
    assert result.action == "navigate"


@pytest.mark.asyncio
async def test_handle_click_button(page):
    """Test clicking a button."""
    # Set up a test page with a button
    await page.set_content("""
        <button role="button" aria-label="Submit">Submit</button>
    """)

    result = await handle_click(page, "button", "Submit")

    assert result.status == "success"
    assert result.error_type == "none"
    assert result.action == "click"
    assert "Submit" in result.message


@pytest.mark.asyncio
async def test_handle_click_link(page):
    """Test clicking a link."""
    await page.set_content("""
        <a href="#" role="link">Click me</a>
    """)

    result = await handle_click(page, "link", "Click me")

    assert result.status == "success"
    assert result.error_type == "none"


@pytest.mark.asyncio
async def test_handle_click_element_not_found(page):
    """Test clicking non-existent element."""
    await page.set_content("<div>Nothing here</div>")

    result = await handle_click(page, "button", "NonExistent")

    assert result.status == "failure"
    assert result.error_type == "element_not_found"
    assert "Could not click" in result.message


@pytest.mark.asyncio
async def test_handle_click_no_target(page):
    """Test click with no role or name."""
    await page.set_content("<div>Test</div>")

    result = await handle_click(page, None, None)

    assert result.status == "failure"
    assert result.error_type == "ambiguous_step"


@pytest.mark.asyncio
async def test_handle_type(page):
    """Test typing text."""
    # Set up input field and focus it
    await page.set_content('<input type="text" id="test" />')
    await page.focus("#test")

    result = await handle_type(page, "Hello World")

    assert result.status == "success"
    assert result.error_type == "none"
    assert result.action == "type"
    assert result.args["text"] == "Hello World"

    # Verify text was actually typed
    value = await page.input_value("#test")
    assert value == "Hello World"


@pytest.mark.asyncio
async def test_handle_scroll_down(page):
    """Test scrolling down."""
    # Create long page
    await page.set_content("""
        <div style="height: 3000px;">
            <div id="top">Top</div>
            <div id="bottom" style="margin-top: 2500px;">Bottom</div>
        </div>
    """)

    result = await handle_scroll(page, "down")

    assert result.status == "success"
    assert result.error_type == "none"
    assert result.action == "scroll"
    assert result.args["direction"] == "down"


@pytest.mark.asyncio
async def test_handle_scroll_up(page):
    """Test scrolling up."""
    await page.set_content('<div style="height: 3000px;">Content</div>')

    result = await handle_scroll(page, "up")

    assert result.status == "success"
    assert result.error_type == "none"
    assert "up" in result.message.lower()


@pytest.mark.asyncio
async def test_handle_press_key_enter(page):
    """Test pressing Enter key."""
    await page.set_content('<input type="text" />')
    await page.focus("input")

    result = await handle_press_key(page, "Enter")

    assert result.status == "success"
    assert result.error_type == "none"
    assert result.action == "press_key"
    assert result.args["key"] == "Enter"
    assert "Enter" in result.message


@pytest.mark.asyncio
async def test_handle_press_key_escape(page):
    """Test pressing Escape key."""
    await page.set_content("<div>Test</div>")

    result = await handle_press_key(page, "Escape")

    assert result.status == "success"
    assert "Escape" in result.message


@pytest.mark.asyncio
async def test_handle_wait(page):
    """Test waiting."""
    import time
    start = time.time()

    result = await handle_wait(page, 0.5)

    elapsed = time.time() - start

    assert result.status == "success"
    assert result.error_type == "none"
    assert result.action == "wait"
    assert result.args["seconds"] == 0.5
    assert elapsed >= 0.5  # Actually waited
    assert result.execution_time_ms >= 500  # At least 500ms


@pytest.mark.asyncio
async def test_handle_search_google(page):
    """Test search on Google (integration test)."""
    # Navigate to Google first
    await page.goto("https://google.com", wait_until="domcontentloaded")

    # Try to search
    result = await handle_search(page, "Python")

    # Should succeed (either via search box or fallback)
    assert result.status == "success"
    assert result.action == "search"
    assert result.args["text"] == "Python"
    assert "Python" in result.message


@pytest.mark.asyncio
async def test_handle_search_fallback(page):
    """Test search fallback (type + enter)."""
    # Page with no search box
    await page.set_content('<input type="text" />')
    await page.focus("input")

    result = await handle_search(page, "test query")

    # Should use fallback
    assert result.status == "success"
    assert "fallback" in result.message.lower()


@pytest.mark.asyncio
async def test_execution_time_tracking(page):
    """Test that all handlers track execution time."""
    # Navigate
    nav_result = await handle_navigate(page, "https://example.com")
    assert nav_result.execution_time_ms > 0

    # Click
    await page.set_content('<button>Test</button>')
    click_result = await handle_click(page, "button", "Test")
    assert click_result.execution_time_ms > 0

    # Wait
    wait_result = await handle_wait(page, 0.1)
    assert wait_result.execution_time_ms >= 100  # Should be at least 100ms


@pytest.mark.asyncio
async def test_multiple_clicks_same_page(page):
    """Test clicking multiple elements on same page."""
    await page.set_content("""
        <button id="btn1">Button 1</button>
        <button id="btn2">Button 2</button>
        <button id="btn3">Button 3</button>
    """)

    result1 = await handle_click(page, "button", "Button 1")
    result2 = await handle_click(page, "button", "Button 2")
    result3 = await handle_click(page, "button", "Button 3")

    assert all(r.status == "success" for r in [result1, result2, result3])


@pytest.mark.asyncio
async def test_type_then_press_enter(page):
    """Test realistic flow: type text then press enter."""
    await page.set_content('<input type="text" id="search" />')
    await page.focus("#search")

    # Type
    type_result = await handle_type(page, "Python programming")
    assert type_result.status == "success"

    # Press enter
    enter_result = await handle_press_key(page, "Enter")
    assert enter_result.status == "success"

    # Verify text is there
    value = await page.input_value("#search")
    assert value == "Python programming"
