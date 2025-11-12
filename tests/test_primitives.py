"""
Tests for primitive actions
"""

import pytest
import asyncio
from pathlib import Path
import sys

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from actions import ActionCommand
from models import Target
from runner import run_action
from browser import browser_manager


@pytest.fixture
async def setup_teardown():
    """Setup and teardown for tests"""
    yield
    await browser_manager.cleanup()


@pytest.fixture
def test_page_url():
    """Get the test page URL"""
    test_file = Path(__file__).parent / "fixtures" / "test_page.html"
    return f"file://{test_file.absolute()}"


@pytest.mark.asyncio
async def test_click_button(setup_teardown, test_page_url):
    """Test clicking a visible button"""
    # Navigate to test page
    nav_command = ActionCommand(
        trace_id="test_nav_001",
        session_id="test_session",
        action_type="navigate_to_url",
        input_value=test_page_url
    )
    nav_result = await run_action(nav_command)
    assert nav_result.status == "success"
    
    # Click the button
    click_command = ActionCommand(
        trace_id="test_click_001",
        session_id="test_session",
        action_type="click_element",
        target=Target(
            selector="#test-button",
            selector_type="css"
        )
    )
    result = await run_action(click_command)
    
    assert result.status == "success"
    assert result.evidence.screenshot_path is not None
    assert result.evidence.dom_snippet_path is not None
    
    # Verify the click result
    get_text_command = ActionCommand(
        trace_id="test_text_001",
        session_id="test_session",
        action_type="get_element_text",
        target=Target(
            selector="#click-result",
            selector_type="css"
        )
    )
    text_result = await run_action(get_text_command)
    assert "Button clicked successfully!" in text_result.evidence.visible_text


@pytest.mark.asyncio
async def test_type_input(setup_teardown, test_page_url):
    """Test typing into a text field"""
    # Navigate
    nav_command = ActionCommand(
        trace_id="test_nav_002",
        session_id="test_session",
        action_type="navigate_to_url",
        input_value=test_page_url
    )
    await run_action(nav_command)
    
    # Type into input
    type_command = ActionCommand(
        trace_id="test_type_001",
        session_id="test_session",
        action_type="type_input",
        target=Target(
            selector="#name-input",
            selector_type="css"
        ),
        input_value="John Doe"
    )
    result = await run_action(type_command)
    
    assert result.status == "success"
    
    # Verify the input value
    get_attr_command = ActionCommand(
        trace_id="test_attr_001",
        session_id="test_session",
        action_type="get_element_attribute",
        target=Target(
            selector="#name-input",
            selector_type="css"
        ),
        input_value="value"
    )
    attr_result = await run_action(get_attr_command)
    assert attr_result.evidence.visible_text == "John Doe"


@pytest.mark.asyncio  
async def test_scroll_to_element(setup_teardown, test_page_url):
    """Test scrolling to an off-viewport element"""
    # Navigate
    nav_command = ActionCommand(
        trace_id="test_nav_003",
        session_id="test_session",
        action_type="navigate_to_url",
        input_value=test_page_url
    )
    await run_action(nav_command)
    
    # Scroll to bottom button
    scroll_command = ActionCommand(
        trace_id="test_scroll_001",
        session_id="test_session",
        action_type="scroll_to",
        target=Target(
            selector="#scroll-button",
            selector_type="css"
        )
    )
    result = await run_action(scroll_command)
    
    assert result.status == "success"
    
    # Click the button to verify it's in view
    click_command = ActionCommand(
        trace_id="test_click_002",
        session_id="test_session",
        action_type="click_element",
        target=Target(
            selector="#scroll-button",
            selector_type="css"
        )
    )
    click_result = await run_action(click_command)
    assert click_result.status == "success"


@pytest.mark.asyncio
async def test_element_not_found(setup_teardown, test_page_url):
    """Test failure case when element is not found"""
    # Navigate
    nav_command = ActionCommand(
        trace_id="test_nav_004",
        session_id="test_session",
        action_type="navigate_to_url",
        input_value=test_page_url
    )
    await run_action(nav_command)
    
    # Try to click non-existent element
    click_command = ActionCommand(
        trace_id="test_click_fail_001",
        session_id="test_session",
        action_type="click_element",
        target=Target(
            selector="#non-existent-element",
            selector_type="css"
        ),
        timeout_ms=1000
    )
    result = await run_action(click_command)
    
    assert result.status == "failure"
    assert result.error is not None
    assert result.error.code in ["element_not_found", "timeout"]
    assert result.evidence.screenshot_path is not None  # Should capture failure screenshot


@pytest.mark.asyncio
async def test_role_or_text_strategy(setup_teardown, test_page_url):
    """Test selector_strategy=role_or_text"""
    # Navigate
    nav_command = ActionCommand(
        trace_id="test_nav_005",
        session_id="test_session",
        action_type="navigate_to_url",
        input_value=test_page_url
    )
    await run_action(nav_command)
    
    # Click using role hint
    click_command = ActionCommand(
        trace_id="test_click_role_001",
        session_id="test_session",
        action_type="click_element",
        target=Target(
            selector=None,
            selector_strategy="role_or_text",
            role_hint="button",
            text_hint="Submit"
        )
    )
    result = await run_action(click_command)
    
    assert result.status == "success"


@pytest.mark.asyncio
async def test_disabled_element(setup_teardown, test_page_url):
    """Test failure when trying to interact with disabled element"""
    # Navigate  
    nav_command = ActionCommand(
        trace_id="test_nav_006",
        session_id="test_session",
        action_type="navigate_to_url",
        input_value=test_page_url
    )
    await run_action(nav_command)
    
    # Try to click disabled button
    click_command = ActionCommand(
        trace_id="test_click_disabled_001",
        session_id="test_session",
        action_type="click_element",
        target=Target(
            selector="button[disabled]",
            selector_type="css"
        )
    )
    result = await run_action(click_command)
    
    assert result.status == "failure"
    assert result.error is not None
    assert result.error.code == "not_interactable"