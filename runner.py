"""
Main action runner
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import asyncio
from typing import Dict, Any, List
from models import ActionCommand, ActionResult, Timings, Evidence, Details
from browser import browser_manager
from metrics import Timer
from evidence import evidence_capture
from errors import map_exception_to_error
from resolver import get_selector_string
import actions
import sensing


async def run_action(command: ActionCommand) -> ActionResult:
    """
    Execute an action command and return the result
    
    Args:
        command: Action command to execute
        
    Returns:
        Action result with status, evidence, and details
    """
    timer = Timer()
    result = ActionResult(
        trace_id=command.trace_id,
        status="failure",
        action_type=command.action_type,
        session_id=command.session_id
    )
    
    page = None
    element = None
    
    try:
        # Get or create page for session
        with timer.measure("resolve"):
            page = await browser_manager.get_or_create_page(command.session_id)
        
        # Execute the action
        with timer.measure("interact"):
            if command.action_type == "navigate_to_url":
                url = command.input_value or ""
                success = await actions.navigate_to_url(page, url, command.timeout_ms)
                if success:
                    result.status = "success"
                    result.details.navigated_url = page.url
                else:
                    raise Exception("Navigation failed")
            
            elif command.action_type == "click_element":
                element, success = await actions.click_element(page, command)
                if success:
                    result.status = "success"
                else:
                    raise Exception("Click failed")
            
            elif command.action_type == "double_click_element":
                element, success = await actions.double_click_element(page, command)
                if success:
                    result.status = "success"
                else:
                    raise Exception("Double click failed")
            
            elif command.action_type == "type_input":
                element, success = await actions.type_input(page, command)
                if success:
                    result.status = "success"
                else:
                    raise Exception("Type input failed")
            
            elif command.action_type == "press_key":
                success = await actions.press_key(page, command)
                if success:
                    result.status = "success"
                else:
                    raise Exception("Key press failed")
            
            elif command.action_type == "hover_over":
                element, success = await actions.hover_over(page, command)
                if success:
                    result.status = "success"
                else:
                    raise Exception("Hover failed")
            
            elif command.action_type == "scroll":
                success = await actions.scroll_page(page, command.scroll)
                if success:
                    result.status = "success"
                else:
                    raise Exception("Scroll failed")
            
            elif command.action_type == "scroll_to":
                element, success = await actions.scroll_to_element(page, command)
                if success:
                    result.status = "success"
                else:
                    raise Exception("Scroll to element failed")
            
            elif command.action_type == "upload_file":
                element, success = await actions.upload_file(page, command)
                if success:
                    result.status = "success"
                else:
                    raise Exception("File upload failed")
            
            elif command.action_type == "drag_and_drop":
                success = await actions.drag_and_drop(page, command)
                if success:
                    result.status = "success"
                else:
                    raise Exception("Drag and drop failed")
            
            elif command.action_type == "go_back":
                success = await actions.go_back(page)
                if success:
                    result.status = "success"
                else:
                    raise Exception("Go back failed")
            
            elif command.action_type == "go_forward":
                success = await actions.go_forward(page)
                if success:
                    result.status = "success"
                else:
                    raise Exception("Go forward failed")
            
            elif command.action_type == "reload_page":
                success = await actions.reload_page(page)
                if success:
                    result.status = "success"
                else:
                    raise Exception("Reload failed")
            
            elif command.action_type == "close_tab":
                await browser_manager.close_tab(command.session_id)
                result.status = "success"
            
            elif command.action_type == "switch_tab":
                tab_index = int(command.input_value or "0")
                page = await browser_manager.switch_tab(command.session_id, tab_index)
                result.status = "success"
            
            elif command.action_type == "extract_dom":
                dom_content = await sensing.extract_dom(page, command.dom_snippet_chars)
                result.status = "success"
                result.evidence.visible_text = dom_content[:500] + "..." if len(dom_content) > 500 else dom_content
            
            elif command.action_type == "get_element_text":
                text = await sensing.get_element_text(page, command)
                if text is not None:
                    result.status = "success"
                    result.evidence.visible_text = text
                else:
                    raise Exception("Could not get element text")
            
            elif command.action_type == "get_element_attribute":
                attr_value = await sensing.get_element_attribute(page, command)
                if attr_value is not None:
                    result.status = "success"
                    result.evidence.visible_text = attr_value
                else:
                    raise Exception("Could not get element attribute")
            
            elif command.action_type == "take_screenshot":
                screenshot_path = await evidence_capture.capture_screenshot(
                    page, command.trace_id, None, False
                )
                if screenshot_path:
                    result.status = "success"
                    result.evidence.screenshot_path = screenshot_path
                else:
                    raise Exception("Screenshot failed")
            
            elif command.action_type == "search_and_click":
                # Composite action: search for element and click it
                element = await resolve_selector_with_fallback(page, command)
                if element:
                    await element.click(timeout=command.timeout_ms)
                    result.status = "success"
                else:
                    raise Exception("Element not found for search and click")
            
            elif command.action_type == "fill_out_form":
                # Composite action: fill multiple form fields
                success = await fill_form_fields(page, command)
                if success:
                    result.status = "success"
                else:
                    raise Exception("Form fill failed")
            
            else:
                raise NotImplementedError(f"Unsupported action: {command.action_type}")
        
        # Capture evidence if successful
        if result.status == "success":
            with timer.measure("post_capture"):
                # Capture screenshot
                if command.screenshot.enabled:
                    screenshot_path = await evidence_capture.capture_screenshot(
                        page,
                        command.trace_id,
                        element,
                        command.screenshot.clip_to_element
                    )
                    result.evidence.screenshot_path = screenshot_path
                
                # Capture DOM snippet
                dom_path, context_selector = await evidence_capture.capture_dom_snippet(
                    page,
                    command.trace_id,
                    element,
                    command.dom_snippet_chars
                )
                result.evidence.dom_snippet_path = dom_path
                result.evidence.dom_context_selector = context_selector
                
                # Get element details if applicable
                if element:
                    element_details = await sensing.get_element_details(page, element)
                    result.details.element_role = element_details.get('role')
                    result.details.element_text_sample = element_details.get('textSample')
                    result.details.element_final_selector = context_selector
    
    except Exception as e:
        # Capture evidence for failure
        if page:
            with timer.measure("post_capture"):
                # Always capture full page screenshot on failure
                screenshot_path = await evidence_capture.capture_screenshot(
                    page, command.trace_id, None, False
                )
                result.evidence.screenshot_path = screenshot_path
                
                # Capture current DOM state
                dom_path, _ = await evidence_capture.capture_dom_snippet(
                    page, command.trace_id, None, command.dom_snippet_chars
                )
                result.evidence.dom_snippet_path = dom_path
        
        # Map exception to error
        result.error = map_exception_to_error(e, get_selector_string(command.target))
        result.status = "failure"
    
    # Set timings
    result.timings_ms = Timings(
        resolve=timer.get_timing("resolve"),
        interact=timer.get_timing("interact"),
        post_capture=timer.get_timing("post_capture")
    )
    
    return result


async def resolve_selector_with_fallback(page, command):
    """Helper to resolve selector with role_or_text fallback"""
    from .resolver import resolve_selector
    element = await resolve_selector(page, command.target, command.timeout_ms)
    return element


async def fill_form_fields(page, command) -> bool:
    """Helper to fill multiple form fields"""
    # This is a simplified version - in real implementation would parse
    # command.metadata for field mappings
    if not command.metadata or "fields" not in command.metadata:
        return False
    
    fields = command.metadata.get("fields", [])
    for field in fields:
        target = command.target.model_copy()
        target.selector = field.get("selector")
        target.selector_type = field.get("selector_type", "css")
        
        temp_command = command.model_copy()
        temp_command.target = target
        temp_command.input_value = field.get("value", "")
        
        element, success = await actions.type_input(page, temp_command)
        if not success:
            return False
    
    return True


# Synchronous wrapper for convenience
def run_action_sync(command: ActionCommand) -> ActionResult:
    """Synchronous wrapper for run_action"""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(run_action(command))