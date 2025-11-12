"""
Selector resolution utilities
"""

from typing import Optional, List
from playwright.async_api import Page, Locator, FrameLocator
from .models import Target, DragTarget


async def resolve_selector(
    page: Page,
    target: Target,
    timeout: int = 8000
) -> Optional[Locator]:
    """
    Resolve a selector to a Playwright Locator
    
    Args:
        page: Playwright page instance
        target: Target specification
        timeout: Timeout in milliseconds
        
    Returns:
        Locator or None if not found
    """
    # Navigate to frames if specified
    frame_context = await navigate_to_frame(page, target.frame_path)
    
    # Determine the base context (page or frame)
    context = frame_context if frame_context else page
    
    locator = None
    
    # Handle different selector strategies
    if target.selector_strategy == "role_or_text" and not target.selector:
        # Try role first, then text
        if target.role_hint:
            try:
                locator = context.get_by_role(target.role_hint)
                if await locator.count() > 0:
                    return locator.first
            except:
                pass
        
        if target.text_hint:
            try:
                locator = context.get_by_text(target.text_hint)
                if await locator.count() > 0:
                    return locator.first
            except:
                pass
        
        return None
    
    # Standard selector resolution
    if not target.selector:
        return None
    
    if target.selector_type == "css":
        locator = context.locator(target.selector)
    elif target.selector_type == "xpath":
        locator = context.locator(f"xpath={target.selector}")
    elif target.selector_type == "role":
        locator = context.get_by_role(target.selector)
    elif target.selector_type == "text":
        locator = context.get_by_text(target.selector)
    else:
        return None
    
    # Check if element exists
    try:
        if await locator.count() > 0:
            return locator.first
    except:
        pass
    
    return None


async def resolve_drag_selector(
    page: Page,
    drag_target: DragTarget,
    timeout: int = 8000
) -> Optional[Locator]:
    """
    Resolve a drag target selector
    
    Args:
        page: Playwright page instance
        drag_target: Drag target specification
        timeout: Timeout in milliseconds
        
    Returns:
        Locator or None if not found
    """
    if drag_target.selector_type == "css":
        locator = page.locator(drag_target.selector)
    elif drag_target.selector_type == "xpath":
        locator = page.locator(f"xpath={drag_target.selector}")
    elif drag_target.selector_type == "role":
        locator = page.get_by_role(drag_target.selector)
    elif drag_target.selector_type == "text":
        locator = page.get_by_text(drag_target.selector)
    else:
        return None
    
    try:
        if await locator.count() > 0:
            return locator.first
    except:
        pass
    
    return None


async def navigate_to_frame(
    page: Page,
    frame_path: Optional[List[str]]
) -> Optional[FrameLocator]:
    """
    Navigate to a nested frame
    
    Args:
        page: Playwright page instance
        frame_path: List of frame names/selectors to navigate
        
    Returns:
        FrameLocator for the target frame or None
    """
    if not frame_path:
        return None
    
    current_frame = None
    for frame_selector in frame_path:
        if current_frame is None:
            current_frame = page.frame_locator(frame_selector)
        else:
            current_frame = current_frame.frame_locator(frame_selector)
    
    return current_frame


def get_selector_string(target: Target) -> str:
    """Get a string representation of the selector for logging"""
    if target.selector:
        return f"{target.selector_type}:{target.selector}"
    elif target.selector_strategy == "role_or_text":
        return f"role:{target.role_hint} or text:{target.text_hint}"
    else:
        return "no selector"