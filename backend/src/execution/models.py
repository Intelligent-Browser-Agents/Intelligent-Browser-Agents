"""
Data models for Action Execution Agent.

This module defines the input/output contracts for the execution agent,
including action specifications, arguments, and execution results.
"""

from pydantic import BaseModel, Field, AliasChoices, ConfigDict
from typing import Literal, Optional, Dict, Any


class ActionArgs(BaseModel):
    """Arguments for browser actions (execution dispatch layer).

    Mirrors schema.ExecutionArgs with stricter validation (extra="forbid").
    schema.ExecutionArgs is the LLM-facing output schema (lenient);
    this class is used by the internal execution dispatcher.
    """
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    url: Optional[str] = None
    role: Optional[str] = None
    name: Optional[str] = None
    text: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("text", "query"),
        serialization_alias="text",
    )
    direction: Optional[Literal["up", "down"]] = None
    key: Optional[str] = None
    seconds: Optional[float] = None
    max_chars: Optional[int] = 15000

    # Disambiguator for a role/name pair that matches more than one element.
    # Without it the only options were "take the first match" (a coin flip
    # decided by DOM order) or fail, so duplicate labels were unaddressable.
    nth: Optional[int] = None

    # set_checkbox / select_option / upload_file
    checked: Optional[bool] = None
    value: Optional[str] = None
    label: Optional[str] = None
    document_id: Optional[str] = None

    # wait_for
    url_contains: Optional[str] = None
    text_contains: Optional[str] = None

    # switch_tab
    index: Optional[int] = None

    # fill
    clear: Optional[bool] = True
    press_enter: Optional[bool] = None

    # read_page
    section: Optional[int] = None


ACTION_NAMES = (
    "navigate",
    "click",
    "fill",
    "type",
    "select_option",
    "set_checkbox",
    "upload_file",
    "search",
    "scroll",
    "scroll_to",
    "press_key",
    "wait",
    "wait_for",
    "extract_content",
    "read_form",
    "read_page",
    "list_tabs",
    "switch_tab",
    "close_tab",
    "go_back",
)


class Action(BaseModel):
    """Validated action specification from LLM translator."""

    action: Literal[
        "navigate",
        "click",
        "fill",
        "type",
        "select_option",
        "set_checkbox",
        "upload_file",
        "search",
        "scroll",
        "scroll_to",
        "press_key",
        "wait",
        "wait_for",
        "extract_content",
        "read_form",
        "read_page",
        "list_tabs",
        "switch_tab",
        "close_tab",
        "go_back",
    ]
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
        # A role/name pair matched several elements. Distinct from not-found: the
        # target exists, the request just was not specific enough.
        "ambiguous_target",
        "invalid_role",
        # The action ran but the post-condition check disagreed, e.g. fill() wrote
        # a value that did not stick because the field was readonly or masked.
        "verification_failed",
        "not_interactable",
        "timeout",
        # A 4xx/5xx response. navigate used to report these as success because
        # page.goto does not raise on HTTP errors.
        "http_error",
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
    extracted_text: Optional[str] = Field(
        default=None,
        description="When action is extract_content, the main text extracted from the page"
    )
    verified: bool = Field(
        default=False,
        description=(
            "True when the handler confirmed the effect by reading state back "
            "(field value, checked state, selected option, URL or DOM change). "
            "A handler that cannot confirm its own effect reports False rather "
            "than letting the verifier infer success from a bare 'success'."
        ),
    )
