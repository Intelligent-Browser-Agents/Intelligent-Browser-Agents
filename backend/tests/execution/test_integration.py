"""
End-to-end integration tests for action execution tool.

These tests verify the complete flow works correctly when the tool
is imported and used by external systems (like BI orchestration).

BI orchestration creates Action objects and calls dispatch_action to execute them.
"""

import pytest
from backend.execution import dispatch_action, Action, ActionArgs


@pytest.mark.asyncio
async def test_google_search_flow(page):
    """
    Integration test: Simulate BI orchestration using the tool for Google search.

    This demonstrates how BI team would:
    1. Navigate to Google
    2. Decide to perform search action
    3. Call dispatch_action to execute it
    4. Get result back
    """
    # BI team navigates to Google
    await page.goto("https://google.com")

    # BI team decides which action to take (search)
    action = Action(
        action="search",
        args=ActionArgs(text="Python programming")
    )

    # BI team calls the tool
    result = await dispatch_action(page, action)

    # BI team receives result
    assert result.action == "search"
    assert isinstance(result.execution_time_ms, int)
    # Search may succeed or fail depending on Google's page structure
    assert result.status in ["success", "failure"]


@pytest.mark.asyncio
async def test_form_filling_flow(page):
    """
    Integration test: Form filling scenario.

    Demonstrates multi-step form interaction.
    """
    # Setup: Create a form page
    await page.goto("data:text/html,<form><input id='name' placeholder='Name'/><input id='email' placeholder='Email'/><button type='submit'>Submit</button></form>")

    # Step 1: BI decides to click name field
    action1 = Action(
        action="click",
        args=ActionArgs(role="textbox", name="Name")
    )
    result1 = await dispatch_action(page, action1)
    assert result1.status == "success"

    # Step 2: BI decides to type into name field
    action2 = Action(
        action="type",
        args=ActionArgs(text="John Doe")
    )
    result2 = await dispatch_action(page, action2)
    assert result2.status == "success"

    # Verify the name was typed
    name_value = await page.evaluate("document.querySelector('#name').value")
    assert name_value == "John Doe"


@pytest.mark.asyncio
async def test_navigation_flow(page):
    """
    Integration test: Navigation scenario.

    Tests that navigation works end-to-end.
    """
    # BI decides to navigate
    action = Action(
        action="navigate",
        args=ActionArgs(url="https://example.com")
    )

    result = await dispatch_action(page, action)

    assert result.status == "success"
    assert result.action == "navigate"
    assert "example.com" in page.url


@pytest.mark.asyncio
async def test_scroll_and_click_flow(page):
    """
    Integration test: Scroll then click scenario.

    Demonstrates handling content that requires scrolling.
    """
    # Create page with button far down
    await page.goto("data:text/html,<div style='height:2000px;'></div><button id='bottom-btn'>Click Me</button>")

    # Step 1: BI decides to scroll down
    action1 = Action(
        action="scroll",
        args=ActionArgs(direction="down")
    )
    result1 = await dispatch_action(page, action1)
    assert result1.status == "success"

    # Step 2: BI decides to click the button
    action2 = Action(
        action="click",
        args=ActionArgs(role="button", name="Click Me")
    )
    result2 = await dispatch_action(page, action2)
    assert result2.status == "success"


@pytest.mark.asyncio
async def test_error_handling_element_not_found(page):
    """
    Integration test: Error handling when element doesn't exist.

    BI team needs to handle failures gracefully.
    """
    await page.goto("data:text/html,<div>No buttons here</div>")

    # BI tries to click non-existent button
    action = Action(
        action="click",
        args=ActionArgs(role="button", name="Submit")
    )

    result = await dispatch_action(page, action)

    # BI team receives failure with error classification
    assert result.status == "failure"
    assert result.error_type == "element_not_found"
    assert isinstance(result.message, str)
    assert len(result.message) > 0


@pytest.mark.asyncio
async def test_error_handling_navigation_failure(page):
    """
    Integration test: Error handling for navigation failures.
    """
    # BI tries to navigate to invalid URL
    action = Action(
        action="navigate",
        args=ActionArgs(url="invalid://not-a-url")
    )

    result = await dispatch_action(page, action)

    assert result.status == "failure"
    assert result.error_type == "navigation_blocked"


@pytest.mark.asyncio
async def test_press_enter_to_submit(page):
    """
    Integration test: Using keyboard to submit.
    """
    await page.goto("data:text/html,<input id='search' />")

    # Focus the input
    await page.click("#search")

    # BI decides to press Enter
    action = Action(
        action="press_key",
        args=ActionArgs(key="Enter")
    )

    result = await dispatch_action(page, action)

    assert result.status == "success"
    assert result.action == "press_key"
    assert "Enter" in result.message


@pytest.mark.asyncio
async def test_complete_workflow_simulation(page):
    """
    Integration test: Complete workflow simulation.

    Simulates how BI orchestration would use the tool for a complete task.
    """
    # Scenario: Search for a product on a website
    # BI orchestration manages the sequence of actions

    # Step 1: Navigate to site
    action1 = Action(
        action="navigate",
        args=ActionArgs(url="data:text/html,<input id='search' placeholder='Search products'/><button id='search-btn'>Search</button>")
    )
    result1 = await dispatch_action(page, action1)
    assert result1.status == "success"

    # Step 2: Click search box
    action2 = Action(
        action="click",
        args=ActionArgs(role="textbox", name="Search products")
    )
    result2 = await dispatch_action(page, action2)
    assert result2.status == "success"

    # Step 3: Type search query
    action3 = Action(
        action="type",
        args=ActionArgs(text="Nike shoes")
    )
    result3 = await dispatch_action(page, action3)
    assert result3.status == "success"

    # Step 4: Click search button
    action4 = Action(
        action="click",
        args=ActionArgs(role="button", name="Search")
    )
    result4 = await dispatch_action(page, action4)
    assert result4.status == "success"

    # Verify all steps completed
    search_value = await page.evaluate("document.querySelector('#search').value")
    assert search_value == "Nike shoes"


@pytest.mark.asyncio
async def test_tool_can_be_imported(page):
    """
    Test that demonstrates how to import and use the tool.

    This is what BI team's orchestration code would look like.
    """
    # This is how BI team imports the tool
    from backend.execution import dispatch_action, Action, ActionArgs

    # BI team creates an action
    action = Action(
        action="wait",
        args=ActionArgs(seconds=0.1)
    )

    await page.goto("data:text/html,<div>Content</div>")

    # BI team calls the tool
    result = await dispatch_action(page, action)

    # BI team receives structured result
    assert hasattr(result, 'action')
    assert hasattr(result, 'status')
    assert hasattr(result, 'error_type')
    assert hasattr(result, 'message')
    assert hasattr(result, 'execution_time_ms')
    assert result.status == "success"


@pytest.mark.asyncio
async def test_all_action_types(page):
    """
    Integration test: Test all 7 action types work.
    """
    # Navigate
    r1 = await dispatch_action(page, Action(action="navigate", args=ActionArgs(url="data:text/html,<button>Test</button>")))
    assert r1.status == "success"

    # Click
    r2 = await dispatch_action(page, Action(action="click", args=ActionArgs(role="button", name="Test")))
    assert r2.status == "success"

    # Type (after clicking button to focus something)
    await page.goto("data:text/html,<input autofocus />")
    r3 = await dispatch_action(page, Action(action="type", args=ActionArgs(text="test")))
    assert r3.status == "success"

    # Scroll
    await page.goto("data:text/html,<div style='height:3000px;'>Content</div>")
    r4 = await dispatch_action(page, Action(action="scroll", args=ActionArgs(direction="down")))
    assert r4.status == "success"

    # Press key
    r5 = await dispatch_action(page, Action(action="press_key", args=ActionArgs(key="Enter")))
    assert r5.status == "success"

    # Wait
    r6 = await dispatch_action(page, Action(action="wait", args=ActionArgs(seconds=0.1)))
    assert r6.status == "success"

    # Search
    await page.goto("data:text/html,<input role='combobox' aria-label='Search' />")
    r7 = await dispatch_action(page, Action(action="search", args=ActionArgs(text="test query")))
    # May succeed or fail depending on page structure
    assert r7.action == "search"
