"""
Unit tests for action dispatcher.

Tests verify that the dispatcher correctly routes actions to their
corresponding handlers and handles unknown actions appropriately.
"""

import pytest
from backend.execution.models import Action, ActionArgs
from backend.execution.dispatcher import dispatch_action


@pytest.mark.asyncio
async def test_dispatch_navigate(page):
    """Test that navigate actions are routed to handle_navigate."""
    action = Action(
        action="navigate",
        args=ActionArgs(url="https://example.com")
    )

    result = await dispatch_action(page, action)

    assert result.action == "navigate"
    assert result.args["url"] == "https://example.com"
    assert result.status == "success"
    assert result.error_type == "none"
    assert "example.com" in result.message


@pytest.mark.asyncio
async def test_dispatch_click(page):
    """Test that click actions are routed to handle_click."""
    # Setup: Navigate to a page with a button
    await page.goto("data:text/html,<button aria-label='Test Button'>Click Me</button>")

    action = Action(
        action="click",
        args=ActionArgs(role="button", name="Test Button")
    )

    result = await dispatch_action(page, action)

    assert result.action == "click"
    assert result.args["role"] == "button"
    assert result.args["name"] == "Test Button"
    assert result.status == "success"
    assert result.error_type == "none"


@pytest.mark.asyncio
async def test_dispatch_type(page):
    """Test that type actions are routed to handle_type."""
    # Setup: Navigate to a page with a focused input
    await page.goto("data:text/html,<input autofocus />")

    action = Action(
        action="type",
        args=ActionArgs(text="test input")
    )

    result = await dispatch_action(page, action)

    assert result.action == "type"
    assert result.args["text"] == "test input"
    assert result.status == "success"
    assert result.error_type == "none"
    assert "test input" in result.message


@pytest.mark.asyncio
async def test_dispatch_search(page):
    """Test that search actions are routed to handle_search."""
    # Setup: Navigate to a page with a search box
    await page.goto("data:text/html,<input role='combobox' aria-label='Search' />")

    action = Action(
        action="search",
        args=ActionArgs(text="python programming")
    )

    result = await dispatch_action(page, action)

    assert result.action == "search"
    assert result.args["text"] == "python programming"
    # Search may succeed or fail depending on page structure
    assert result.status in ["success", "failure"]


@pytest.mark.asyncio
async def test_dispatch_scroll(page):
    """Test that scroll actions are routed to handle_scroll."""
    # Setup: Navigate to a page with scrollable content
    await page.goto("data:text/html,<div style='height: 2000px;'>Content</div>")

    action = Action(
        action="scroll",
        args=ActionArgs(direction="down")
    )

    result = await dispatch_action(page, action)

    assert result.action == "scroll"
    assert result.args["direction"] == "down"
    assert result.status == "success"
    assert result.error_type == "none"
    assert "down" in result.message


@pytest.mark.asyncio
async def test_dispatch_press_key(page):
    """Test that press_key actions are routed to handle_press_key."""
    await page.goto("data:text/html,<input />")

    action = Action(
        action="press_key",
        args=ActionArgs(key="Enter")
    )

    result = await dispatch_action(page, action)

    assert result.action == "press_key"
    assert result.args["key"] == "Enter"
    assert result.status == "success"
    assert result.error_type == "none"
    assert "Enter" in result.message


@pytest.mark.asyncio
async def test_dispatch_wait(page):
    """Test that wait actions are routed to handle_wait."""
    await page.goto("data:text/html,<div>Test</div>")

    action = Action(
        action="wait",
        args=ActionArgs(seconds=0.1)
    )

    result = await dispatch_action(page, action)

    assert result.action == "wait"
    assert result.args["seconds"] == 0.1
    assert result.status == "success"
    assert result.error_type == "none"
    assert "0.1" in result.message


@pytest.mark.asyncio
async def test_dispatch_unknown_action(page):
    """Test that unknown actions are handled gracefully."""
    # Create an action with an invalid action type
    # We need to bypass Pydantic validation for this test
    action = Action.model_construct(
        action="invalid_action",
        args=ActionArgs()
    )

    result = await dispatch_action(page, action)

    assert result.status == "failure"
    assert result.error_type == "unknown"
    assert "Unknown action" in result.message or "invalid_action" in result.message
    assert result.execution_time_ms == 0


@pytest.mark.asyncio
async def test_dispatch_click_element_not_found(page):
    """Test dispatcher handles element_not_found errors from handlers."""
    await page.goto("data:text/html,<div>No buttons here</div>")

    action = Action(
        action="click",
        args=ActionArgs(role="button", name="NonExistent")
    )

    result = await dispatch_action(page, action)

    assert result.action == "click"
    assert result.status == "failure"
    assert result.error_type == "element_not_found"


@pytest.mark.asyncio
async def test_dispatch_navigate_blocked(page):
    """Test dispatcher handles navigation_blocked errors from handlers."""
    action = Action(
        action="navigate",
        args=ActionArgs(url="invalid://not-a-real-url")
    )

    result = await dispatch_action(page, action)

    assert result.action == "navigate"
    assert result.status == "failure"
    assert result.error_type == "navigation_blocked"


@pytest.mark.asyncio
async def test_dispatch_multiple_actions_sequentially(page):
    """Test that multiple actions can be dispatched sequentially."""
    # Navigate
    action1 = Action(
        action="navigate",
        args=ActionArgs(url="data:text/html,<input id='test-input' />")
    )
    result1 = await dispatch_action(page, action1)
    assert result1.status == "success"

    # Click to focus the input
    await page.click("#test-input")

    # Type
    action2 = Action(
        action="type",
        args=ActionArgs(text="test")
    )
    result2 = await dispatch_action(page, action2)
    assert result2.status == "success"

    # Verify input value
    value = await page.evaluate("document.querySelector('#test-input').value")
    assert value == "test"


@pytest.mark.asyncio
async def test_dispatch_execution_time_measured(page):
    """Test that execution time is properly measured for all actions."""
    await page.goto("data:text/html,<div>Test</div>")

    action = Action(
        action="wait",
        args=ActionArgs(seconds=0.1)
    )

    result = await dispatch_action(page, action)

    # Wait action should take at least 100ms
    assert result.execution_time_ms >= 100
    # But not too much longer (with 50ms tolerance for processing)
    assert result.execution_time_ms < 200
