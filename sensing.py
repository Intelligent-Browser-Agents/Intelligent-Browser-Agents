"""
Sensing actions for reading DOM content
"""

from typing import Optional, Dict, Any
from playwright.async_api import Page
from .models import ActionCommand
from .resolver import resolve_selector


async def extract_dom(page: Page, max_chars: int = 10000) -> str:
    """
    Extract the current DOM as HTML
    
    Args:
        page: Playwright page
        max_chars: Maximum characters to return
        
    Returns:
        HTML content
    """
    content = await page.content()
    if len(content) > max_chars:
        content = content[:max_chars] + "..."
    return content


async def get_element_text(
    page: Page,
    command: ActionCommand
) -> Optional[str]:
    """
    Get text content of an element
    
    Args:
        page: Playwright page
        command: Action command
        
    Returns:
        Element text or None
    """
    element = await resolve_selector(page, command.target, command.timeout_ms)
    
    if not element:
        return None
    
    try:
        text = await element.inner_text()
        return text.strip() if text else ""
    except:
        return None


async def get_element_attribute(
    page: Page,
    command: ActionCommand,
    attribute: str = "value"
) -> Optional[str]:
    """
    Get an attribute value from an element
    
    Args:
        page: Playwright page
        command: Action command
        attribute: Attribute name to get
        
    Returns:
        Attribute value or None
    """
    element = await resolve_selector(page, command.target, command.timeout_ms)
    
    if not element:
        return None
    
    try:
        # Use input_value as attribute name if provided
        attr_name = command.input_value or attribute
        value = await element.get_attribute(attr_name)
        return value
    except:
        return None


async def take_screenshot(
    page: Page,
    output_path: str = "/tmp/screenshot.png"
) -> str:
    """
    Take a full page screenshot
    
    Args:
        page: Playwright page
        output_path: Where to save the screenshot
        
    Returns:
        Path to saved screenshot
    """
    await page.screenshot(path=output_path, full_page=True)
    return output_path


async def get_element_details(
    page: Page,
    element
) -> Dict[str, Any]:
    """
    Get detailed information about an element
    
    Args:
        page: Playwright page
        element: Element locator
        
    Returns:
        Dictionary with element details
    """
    if not element:
        return {}
    
    try:
        details = await element.evaluate('''
            (el) => {
                return {
                    tagName: el.tagName.toLowerCase(),
                    id: el.id || null,
                    className: el.className || null,
                    role: el.getAttribute('role') || null,
                    type: el.type || null,
                    name: el.name || null,
                    value: el.value || null,
                    href: el.href || null,
                    textSample: (el.innerText || el.textContent || '').substring(0, 100),
                    isVisible: el.offsetParent !== null,
                    isEnabled: !el.disabled,
                    bounds: el.getBoundingClientRect()
                };
            }
        ''')
        return details
    except:
        return {}