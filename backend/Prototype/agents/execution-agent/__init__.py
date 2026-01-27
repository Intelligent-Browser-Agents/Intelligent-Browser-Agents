"""
Action Execution Agent

This module provides browser action execution capabilities for the intelligent browser agent.
It translates high-level plan steps into specific browser actions and executes them via Playwright.
"""

from .models import (
    ActionArgs,
    Action,
    ExecutionInput,
    ExecutionOutput,
)

__all__ = [
    "ActionArgs",
    "Action",
    "ExecutionInput",
    "ExecutionOutput",
]
