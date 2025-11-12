"""
Primitive browser actions
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from typing import Optional, Tuple
from playwright.async_api import Page, Locator
from models import ActionCommand, ScrollConfig
from resolver import resolve_selector, resolve_drag_selector
from errors import ActionExecutionError


async def click_element(
    page: Page,
    command: ActionCommand
) -> Tuple[Optional[Locator], bool]:
    """
    Click an element
    
    Args:
        page: Playwright page
        command: Action command
        
    Returns:
        Tuple of (element, success)
    """
    element = await resolve_selector(page, command.target, command.timeout_ms)
    
    if not element:
        return None, False
    
    try:
        # Readiness checks
        await element.wait_for(state="attached", timeout=command.timeout_ms)
        await element.wait_for(state="visible", timeout=command.timeout_ms)
        await element.wait_for(state="stable", timeout=command.timeout_ms)
        
        # Check if enabled
        is_enabled = await element.is_enabled()
        if not is_enabled:
            raise ActionExecutionError(
                "not_interactable",
                "Element is not enabled",
                command.target.selector
            )
        
        # Click
        await element.click(timeout=command.timeout_ms)
        return element, True
        
    except Exception as e:
        if isinstance(e, ActionExecutionError):
            raise
        return element, False


async def double_click_element(
    page: Page,
    command: ActionCommand
) -> Tuple[Optional[Locator], bool]:
    """Double click an element"""
    element = await resolve_selector(page, command.target, command.timeout_ms)
    
    if not element:
        return None, False
    
    try:
        await element.wait_for(state="visible", timeout=command.timeout_ms)
        await element.wait_for(state="stable", timeout=command.timeout_ms)
        
        if not await element.is_enabled():
            raise ActionExecutionError(
                "not_interactable",
                "Element is not enabled",
                command.target.selector
            )
        
        await element.dblclick(timeout=command.timeout_ms)
        return element, True
        
    except Exception as e:
        if isinstance(e, ActionExecutionError):
            raise
        return element, False


async def type_input(
    page: Page,
    command: ActionCommand
) -> Tuple[Optional[Locator], bool]:
    """Type text into an input element"""
    element = await resolve_selector(page, command.target, command.timeout_ms)
    
    if not element:
        return None, False
    
    try:
        await element.wait_for(state="visible", timeout=command.timeout_ms)
        await element.wait_for(state="stable", timeout=command.timeout_ms)
        
        if not await element.is_enabled():
            raise ActionExecutionError(
                "not_interactable",
                "Element is not enabled",
                command.target.selector
            )
        
        # Clear and type
        await element.fill(command.input_value or "", timeout=command.timeout_ms)
        return element, True
        
    except Exception as e:
        if isinstance(e, ActionExecutionError):
            raise
        return element, False


async def press_key(
    page: Page,
    command: ActionCommand
) -> bool:
    """Press a keyboard key"""
    try:
        key = command.key or "Enter"
        await page.keyboard.press(key)
        return True
    except:
        return False


async def hover_over(
    page: Page,
    command: ActionCommand
) -> Tuple[Optional[Locator], bool]:
    """Hover over an element"""
    element = await resolve_selector(page, command.target, command.timeout_ms)
    
    if not element:
        return None, False
    
    try:
        await element.wait_for(state="visible", timeout=command.timeout_ms)
        await element.hover(timeout=command.timeout_ms)
        return element, True
    except:
        return element, False


async def scroll_page(
    page: Page,
    scroll_config: Optional[ScrollConfig]
) -> bool:
    """Scroll the page"""
    if not scroll_config:
        scroll_config = ScrollConfig()
    
    try:
        direction = scroll_config.direction
        amount = scroll_config.amount
        
        if direction == "down":
            await page.mouse.wheel(0, amount)
        elif direction == "up":
            await page.mouse.wheel(0, -amount)
        elif direction == "right":
            await page.mouse.wheel(amount, 0)
        elif direction == "left":
            await page.mouse.wheel(-amount, 0)
        
        # Wait for scroll to complete
        await page.wait_for_timeout(100)
        return True
        
    except:
        return False


async def scroll_to_element(
    page: Page,
    command: ActionCommand
) -> Tuple[Optional[Locator], bool]:
    """Scroll to an element"""
    element = await resolve_selector(page, command.target, command.timeout_ms)
    
    if not element:
        return None, False
    
    try:
        await element.scroll_into_view_if_needed(timeout=command.timeout_ms)
        return element, True
    except:
        return element, False


async def upload_file(
    page: Page,
    command: ActionCommand
) -> Tuple[Optional[Locator], bool]:
    """Upload a file to an input element"""
    element = await resolve_selector(page, command.target, command.timeout_ms)
    
    if not element:
        return None, False
    
    if not command.upload_path:
        raise ActionExecutionError(
            "bad_command",
            "No upload_path specified",
            command.target.selector
        )
    
    try:
        # Check if file exists
        from pathlib import Path
        if not Path(command.upload_path).exists():
            raise ActionExecutionError(
                "upload_failed",
                f"File not found: {command.upload_path}",
                command.target.selector
            )
        
        await element.set_input_files(command.upload_path)
        return element, True
        
    except Exception as e:
        if isinstance(e, ActionExecutionError):
            raise
        return element, False


async def drag_and_drop(
    page: Page,
    command: ActionCommand
) -> bool:
    """Perform drag and drop between two elements"""
    if not command.drag_source or not command.drop_target:
        raise ActionExecutionError(
            "bad_command",
            "drag_source and drop_target must be specified"
        )
    
    source = await resolve_drag_selector(page, command.drag_source, command.timeout_ms)
    target = await resolve_drag_selector(page, command.drop_target, command.timeout_ms)
    
    if not source:
        raise ActionExecutionError(
            "element_not_found",
            "Drag source not found",
            command.drag_source.selector
        )
    
    if not target:
        raise ActionExecutionError(
            "element_not_found",
            "Drop target not found",
            command.drop_target.selector
        )
    
    try:
        await source.drag_to(target, timeout=command.timeout_ms)
        return True
    except:
        return False


async def go_back(page: Page) -> bool:
    """Navigate back in history"""
    try:
        await page.go_back()
        return True
    except:
        return False


async def go_forward(page: Page) -> bool:
    """Navigate forward in history"""
    try:
        await page.go_forward()
        return True
    except:
        return False


async def reload_page(page: Page) -> bool:
    """Reload the current page"""
    try:
        await page.reload()
        return True
    except:
        return False


async def navigate_to_url(page: Page, url: str, timeout: int = 30000) -> bool:
    """Navigate to a URL"""
    try:
        response = await page.goto(url, timeout=timeout)
        return response.status < 400 if response else False
    except:
        return False