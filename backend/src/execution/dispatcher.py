"""
Action dispatcher for routing browser actions to appropriate handlers.

This module routes validated Action objects to their corresponding
Playwright handler functions based on the action type.g
"""

from playwright.async_api import Page
from .models import Action, ExecutionOutput
from .actions import (
    do_click,
    do_close_tab,
    do_fill,
    do_list_tabs,
    do_read_form,
    do_read_page,
    do_scroll_to,
    do_select_option,
    do_set_checkbox,
    do_switch_tab,
    do_upload_file,
    do_wait_for,
)
from .handlers import (
    handle_navigate,
    handle_click,
    handle_type,
    handle_search,
    handle_scroll,
    handle_press_key,
    handle_wait,
    handle_extract_content,
    handle_go_back,
)


async def dispatch_action(page: Page, action: Action, runtime: dict | None = None) -> ExecutionOutput:
    """
    Route action to appropriate handler based on action type.

    Args:
        page: Playwright page instance
        action: Validated action object containing action type and arguments
        runtime: Optional caller-owned runtime dict. switch_tab and close_tab
            change which page subsequent actions run against; when a runtime is
            given, the new page is written into runtime["page"]. Without one,
            a tab switch cannot outlive this call.

    Returns:
        ExecutionOutput with execution result, status, and timing information

    Examples:
        >>> action = Action(action="navigate", args=ActionArgs(url="https://google.com"))
        >>> result = await dispatch_action(page, action)
        >>> assert result.status == "success"

        >>> action = Action(action="click", args=ActionArgs(role="button", name="Search"))
        >>> result = await dispatch_action(page, action)
    """
    a = action.args

    # Tab switching changes which page subsequent actions run against, so those
    # handlers return (output, new_page) and are dispatched separately below.
    if action.action in ("switch_tab", "close_tab"):
        handler = do_switch_tab if action.action == "switch_tab" else do_close_tab
        output, new_page = await handler(page, a.index)
        if new_page is not None and runtime is not None:
            runtime["page"] = new_page
        return output

    handlers = {
        "navigate": lambda: handle_navigate(page, a.url),
        # Element-addressed actions. Each names its target and verifies its effect.
        "click": lambda: do_click(page, a.role, a.name, nth=a.nth),
        "fill": lambda: do_fill(page, a.role, a.name, a.text, nth=a.nth, clear=True if a.clear is None else a.clear),
        # role defaults to combobox for parity with the tool-mode schema
        # (SelectOptionInput); without it a role-less JSON call dies on
        # invalid_role while the identical tool call works.
        "select_option": lambda: do_select_option(page, a.role or "combobox", a.name, value=a.value, label=a.label, nth=a.nth),
        "set_checkbox": lambda: do_set_checkbox(page, a.role, a.name, checked=True if a.checked is None else a.checked, nth=a.nth),
        "upload_file": lambda: do_upload_file(page, a.role, a.name, file_path=a.document_id or a.value, nth=a.nth),
        "scroll_to": lambda: do_scroll_to(page, a.role, a.name, nth=a.nth),
        "wait_for": lambda: do_wait_for(
            page,
            role=a.role,
            name=a.name,
            url_contains=a.url_contains,
            text_contains=a.text_contains,
            seconds=a.seconds if a.seconds and a.seconds > 0 else 10.0,
        ),
        "read_form": lambda: do_read_form(page),
        "read_page": lambda: do_read_page(page, section=a.section or 1),
        "list_tabs": lambda: do_list_tabs(page),
        # Legacy, target-free. Kept for compatibility; prefer fill/wait_for.
        "type": lambda: handle_type(page, a.text),
        "search": lambda: handle_search(page, a.text),
        "scroll": lambda: handle_scroll(page, a.direction),
        "press_key": lambda: handle_press_key(page, a.key),
        "wait": lambda: handle_wait(page, a.seconds),
        "extract_content": lambda: handle_extract_content(page, max_chars=a.max_chars or 15000),
        "go_back": lambda: handle_go_back(page),
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
