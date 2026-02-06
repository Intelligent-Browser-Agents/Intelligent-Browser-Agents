"""
Action Execution Tool for Browser Automation.

This tool executes specific browser actions provided by BI orchestration.
BI team decides WHAT actions to take, this tool executes them.

Main entry point:
- dispatch_action: Execute a specific browser action

Components:
- models: Data models for actions and results
- handlers: Playwright action implementations
- dispatcher: Routes actions to handlers

Example usage:
    >>> from backend.execution import dispatch_action, Action, ActionArgs
    >>>
    >>> # BI orchestration creates the action
    >>> action = Action(
    ...     action="click",
    ...     args=ActionArgs(role="button", name="Search")
    ... )
    >>>
    >>> # Call the tool to execute it
    >>> result = await dispatch_action(page, action)
    >>>
    >>> # Handle the result
    >>> if result.status == "success":
    ...     # Continue to next action
    ... else:
    ...     # Handle failure based on error_type
"""

from .models import (
    Action,
    ActionArgs,
    ExecutionOutput
)
from .dispatcher import dispatch_action

__all__ = [
    # Main entry point
    "dispatch_action",

    # Data models
    "Action",
    "ActionArgs",
    "ExecutionOutput"
]
