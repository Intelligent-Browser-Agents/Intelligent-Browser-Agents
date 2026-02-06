"""
Data models for Action Execution Agent.

This module defines the input/output contracts for the execution agent,
including action specifications, arguments, and execution results.
"""

from pydantic import BaseModel, Field
from typing import Literal, Optional, Dict, Any


class ActionArgs(BaseModel):
    """Arguments for browser actions."""

    url: Optional[str] = None
    role: Optional[str] = None
    name: Optional[str] = None
    text: Optional[str] = None
    direction: Optional[Literal["up", "down"]] = None
    key: Optional[str] = None
    seconds: Optional[float] = None


class Action(BaseModel):
    """Validated action specification from LLM translator."""

    action: Literal["navigate", "click", "type", "search", "scroll", "press_key", "wait"]
    args: ActionArgs


class ExecutionInput(BaseModel):
    """Input from orchestration agent to execution agent."""

    plan_step: str = Field(
        ...,
        description="High-level step to execute (e.g., 'Search for Nike shoes')"
    )
    dom_snapshot: Dict[str, Any] = Field(
        ...,
        description="DOM snapshot from IG DOM Extraction tool"
    )
    url: str = Field(
        ...,
        description="Current page URL"
    )
    main_goal: str = Field(
        ...,
        description="Overall task goal (context only)"
    )


class ExecutionOutput(BaseModel):
    """Output from execution agent to Data Processing Tool."""

    action: str = Field(
        ...,
        description="Action that was executed"
    )
    args: Dict[str, Any] = Field(
        ...,
        description="Arguments used for the action"
    )
    status: Literal["success", "failure"] = Field(
        ...,
        description="Whether the action succeeded or failed"
    )
    error_type: Literal[
        "none",
        "element_not_found",
        "ambiguous_step",
        "tool_limit",
        "navigation_blocked",
        "unknown"
    ] = Field(
        ...,
        description="Type of error if action failed"
    )
    message: str = Field(
        ...,
        description="Human-readable description of what happened"
    )
    execution_time_ms: int = Field(
        ...,
        description="Time taken to execute the action in milliseconds"
    )
