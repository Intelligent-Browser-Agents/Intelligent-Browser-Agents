from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, PositiveFloat, RootModel, field_validator


class Evidence(BaseModel):
    screenshot_path: Optional[str] = Field(
        default=None, description="Filesystem path to the captured screenshot evidence."
    )
    dom_snapshot: Optional[str] = Field(
        default=None,
        description="Raw HTML or a persisted reference pointing to the DOM snapshot collected after the action.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Human-readable description of the evidence or contextual remarks.",
    )


class OutputPayload(BaseModel):
    data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured information returned by the tool (keys are tool-specific).",
    )


class Metadata(BaseModel):
    execution_time_ms: Optional[PositiveFloat] = Field(
        default=None,
        description="Latency for the action in milliseconds.",
    )
    memory_usage_mb: Optional[PositiveFloat] = Field(
        default=None,
        description="Approximate memory consumed while handling the action.",
    )
    agent: Optional[str] = Field(
        default=None,
        description="Identifier for the agent that produced this log entry.",
    )
    extra: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata fields captured for diagnostics.",
    )


class LogActionResult(BaseModel):
    tool_name: str = Field(..., min_length=1, description="Name of the tool that produced the result.")
    task_id: UUID = Field(..., description="Unique identifier for the task in the orchestration pipeline.")
    trace_id: UUID = Field(..., description="Trace identifier linking this log to a specific execution step.")
    status: Literal["success", "fail", "error"] = Field(
        ..., description="Outcome of the tool execution."
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp (UTC) for when the result was recorded.",
    )
    confidence_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence score assigned to the result (0.0-1.0).",
    )
    message: Optional[str] = Field(
        default=None,
        description="Short summary or error message describing the result.",
    )
    evidence: Evidence = Field(
        default_factory=Evidence, description="Supporting evidence for the action result."
    )
    output: OutputPayload = Field(
        default_factory=OutputPayload,
        description="Structured output payload from the tool.",
    )
    metadata: Metadata = Field(
        default_factory=Metadata,
        description="Operational metadata describing the execution context.",
    )

    @field_validator("tool_name")
    @classmethod
    def strip_tool_name(cls, value: str) -> str:
        return value.strip()


class LogRecord(LogActionResult):
    id: UUID = Field(default_factory=uuid4, description="Unique identifier for the log record.")
    received_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp marking when the logging service accepted the record.",
    )


class LogRecordCollection(RootModel):
    root: Dict[UUID, LogRecord]

