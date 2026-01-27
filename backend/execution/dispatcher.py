"""
Action dispatcher for routing browser actions to appropriate handlers.

This module routes validated Action objects to their corresponding
Playwright handler functions based on the action type.
"""

from playwright.async_api import Page
from .models import Action, ExecutionOutput
from .handlers import (
    handle_navigate,
    handle_click,
    handle_type,
    handle_search,
    handle_scroll,
    handle_press_key,
    handle_wait
)


async def dispatch_action(page: Page, action: Action) -> ExecutionOutput:
    """
    Route action to appropriate handler based on action type.

    Args:
        page: Playwright page instance
        action: Validated action object containing action type and arguments

    Returns:
        ExecutionOutput with execution result, status, and timing information

    Examples:
        >>> action = Action(action="navigate", args=ActionArgs(url="https://google.com"))
        >>> result = await dispatch_action(page, action)
        >>> assert result.status == "success"

        >>> action = Action(action="click", args=ActionArgs(role="button", name="Search"))
        >>> result = await dispatch_action(page, action)
    """
    # Define handler mapping
    handlers = {
        "navigate": lambda: handle_navigate(page, action.args.url),
        "click": lambda: handle_click(page, action.args.role, action.args.name),
        "type": lambda: handle_type(page, action.args.text),
        "search": lambda: handle_search(page, action.args.text),
        "scroll": lambda: handle_scroll(page, action.args.direction),
        "press_key": lambda: handle_press_key(page, action.args.key),
        "wait": lambda: handle_wait(page, action.args.seconds)
    }

    # Get handler for the action
    handler = handlers.get(action.action)

    # Handle unknown action types
    if not handler:
        return ExecutionOutput(
            action=action.action,
            args=action.args.model_dump(),
            status="failure",
            error_type="unknown",
            message=f"Unknown action type: {action.action}",
            execution_time_ms=0
        )

    # Execute the handler
    return await handler()
