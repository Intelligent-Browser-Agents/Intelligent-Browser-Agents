"""
Schema definitions for all agents.
These Pydantic models define the structured output format for each agent,
aligned with the prompts in the prompts/ directory.
"""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field, AliasChoices, model_validator
from typing import Any, List, Optional, Literal, Union
from urllib.parse import urlparse

# =============================================================================
# ORCHESTRATION LAYER
# Aligned with: prompts/orchestration.prompt.md
# =============================================================================

class OrchestratorPlan(BaseModel):
    """
    Schema for the Orchestration Agent's plan output.
    Converts user requests into ordered high-level subtasks.
    """
    needs_clarification: bool = Field(
        description="True if essential information is missing and clarification is needed before planning."
    )
    clarifying_questions: List[str] = Field(
        default_factory=list,
        description="1-3 targeted questions to ask if clarification is needed. Empty if needs_clarification is false."
    )
    goal: str = Field(
        description="One-sentence clarified browsing goal based on the user's request."
    )
    steps: List[str] = Field(
        default_factory=list,
        description="Ordered list of 3-8 high-level steps to achieve the goal. Empty if needs_clarification is true."
    )


class OrchestratorDecision(BaseModel):
    """
    Schema for the Orchestration Agent's reasoning-and-action output.
    Used after each execution/verification to decide: advance, retry, or plan_complete.
    """
    reasoning: str = Field(
        default="",
        description="1-3 sentences explaining why this action was chosen.",
        validation_alias=AliasChoices("reasoning", "Reasoning", "reason", "explanation", "rationale"),
    )
    action: Literal["advance", "retry", "plan_complete"] = Field(
        default="retry",
        description="Next action: advance to next step, retry current step, or mark plan complete.",
        validation_alias=AliasChoices("action", "Action", "next_action"),
    )
    task_refinement: Optional[str] = Field(
        default=None,
        description="When action is retry: optional narrower instruction for the executor (same plan step). "
        "Use to focus on one sub-goal (e.g. fill subject only). Omit or null when not needed.",
        validation_alias=AliasChoices("task_refinement", "taskRefinement", "current_task_override"),
    )


# =============================================================================
# EXECUTION LAYER
# Aligned with: prompts/execution.prompt.md
# =============================================================================

class ExecutionArgs(BaseModel):
    """Arguments for browser actions."""
    url: Optional[str] = Field(default=None, description="URL for navigation actions.")
    role: Optional[str] = Field(default=None, description="ARIA role for element targeting.")
    name: Optional[str] = Field(default=None, description="Accessible name for element targeting.")
    text: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("text", "query"),
        serialization_alias="text",
        description="Text to type or search query.",
    )
    direction: Optional[Literal["up", "down"]] = Field(default=None, description="Scroll direction.")
    key: Optional[str] = Field(default=None, description="Key to press (e.g., 'Enter', 'Escape').")
    seconds: Optional[float] = Field(default=None, description="Duration for wait actions.")
    max_chars: Optional[int] = Field(default=15000, description="Max characters for extract_content.")


class ExecutionResult(BaseModel):
    action: Literal["navigate", "click", "type", "search", "scroll", "press_key", "wait", "extract_content"]
    args: ExecutionArgs
    status: Literal["success", "failure"]
    error_type: Literal[
        "none", "element_not_found", "ambiguous_step",
        "tool_limit", "navigation_blocked", "unknown"
    ] = "none"
    message: str

    @model_validator(mode="after")
    def validate_action_requirements(self):
        required = {
            "navigate": ["url"],
            "click": ["role", "name"],
            "type": ["text"],
            "search": ["text"],
            "scroll": ["direction"],
            "press_key": ["key"],
            "wait": ["seconds"],
            "extract_content": [],
        }

        if self.status == "success":
            missing = []
            for key in required[self.action]:
                v = getattr(self.args, key, None)
                if v is None or (isinstance(v, str) and not v.strip()):
                    missing.append(key)
            if missing:
                raise ValueError(
                    f"status='success' requires non-empty args for action='{self.action}': {missing}"
                )

            if self.action == "navigate":
                raw_url = (self.args.url or "").strip()
                parsed = urlparse(raw_url)
                if (
                    any(char.isspace() for char in raw_url)
                    or parsed.scheme not in ("http", "https")
                    or not parsed.netloc
                ):
                    raise ValueError(
                        "status='success' for action='navigate' requires a valid absolute http(s) URL without spaces"
                    )

            if self.action == "wait" and (self.args.seconds is None or self.args.seconds <= 0):
                raise ValueError("status='success' for action='wait' requires args.seconds > 0")
        else:
            if self.error_type == "none":
                raise ValueError("status='failure' cannot use error_type='none'")
        return self


class LastExecutionEvent(BaseModel):
    """Structured record of the last executor action (control plane; avoid parsing reasoning_log)."""

    action: str = ""
    args: dict = Field(default_factory=dict)
    status: str = "unknown"
    error_type: Optional[str] = None
    message: str = ""
    extracted_content_present: bool = False


class StepIntent(str, Enum):
    """High-level intent for the current plan step (derived once per step)."""

    retrieve_info = "retrieve_info"
    navigate = "navigate"
    authenticate = "authenticate"
    compose = "compose"
    interact = "interact"
    finalize = "finalize"


def infer_step_intent(task: str) -> str:
    """Classify plan step text into a StepIntent value (best-effort heuristic)."""
    text = (task or "").lower()
    if any(
        k in text
        for k in (
            "login",
            "log in",
            "sign in",
            "sign-in",
            "authenticate",
            "mfa",
            "2fa",
            "password",
            "otp",
            "two-factor",
        )
    ):
        return StepIntent.authenticate.value
    if any(
        k in text
        for k in (
            "compose",
            "draft",
            "new email",
            "write email",
            "email message",
            "mail message",
        )
    ) or ("email" in text and "draft" in text):
        return StepIntent.compose.value
    if any(k in text for k in ("navigate", "go to ", "open ", "visit ", "go to the", "open the")):
        return StepIntent.navigate.value
    if any(
        k in text
        for k in (
            "submit",
            "finalize",
            "confirm",
            "complete checkout",
            "place order",
            "send the email",
            "send email",
        )
    ):
        return StepIntent.finalize.value
    if any(k in text for k in ("click", "select ", "choose ", "press ", "check the box")):
        return StepIntent.interact.value
    if any(
        k in text
        for k in (
            "extract",
            "read ",
            "find ",
            "look up",
            "gather",
            "collect",
            "search for",
            "get the",
        )
    ):
        return StepIntent.retrieve_info.value
    return StepIntent.retrieve_info.value


def last_execution_event_to_executor_log(event: Union[dict[str, Any], LastExecutionEvent]) -> str:
    """Build multiline executor log text matching legacy format (for deprecated log-based parsers)."""
    if isinstance(event, LastExecutionEvent):
        d = event.model_dump()
    else:
        d = dict(event or {})
    action = (d.get("action") or "unknown").strip()
    raw_args = d.get("args")
    args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
    parts: list[str] = []
    for k, v in sorted(args.items()):
        if v is not None and str(v).strip() != "":
            parts.append(f"{k}={v}")
    args_str = ", ".join(parts)
    status = (d.get("status") or "unknown").strip()
    msg = (d.get("message") or "").strip()
    err = d.get("error_type")
    err_s = "none" if err is None else str(err).strip()
    return (
        f"[Executor] Action: {action}\n"
        f"[Executor] Args: {args_str}\n"
        f"[Executor] Status: {status}\n"
        f"[Executor] Message: {msg}\n"
        f"[Executor] Error Type: {err_s}"
    )


# =============================================================================
# VERIFICATION LAYER
# Aligned with: prompts/verification.prompt.md
# =============================================================================

class VerificationResult(BaseModel):
    """
    Schema for the Verification Agent's output.
    Evaluates whether the execution satisfied the plan step.
    """
    verdict: Literal["success", "failure"] = Field(
        description="Whether the action successfully completed the step."
    )
    step_complete: bool = Field(
        description="True if the current plan step is fully satisfied."
    )
    goal_complete: bool = Field(
        description="True if the overall goal has been achieved."
    )
    error_type: Literal[
        "none",
        "execution_failure",
        "mismatch",
        "blocked",
        "insufficient_evidence",
        "unexpected_state"
    ] = Field(
        default="none",
        description="Type of error if verdict is failure."
    )
    message: str = Field(
        description="One concise sentence explaining the verdict."
    )
    handoff: Literal["orchestration", "fallback"] = Field(
        description="Which agent should handle the next step."
    )


# =============================================================================
# FALLBACK LAYER
# Aligned with: prompts/fallback.prompt.md
# =============================================================================

class FallbackStrategy(BaseModel):
    """
    Schema for the Fallback Agent's recovery output.
    Diagnoses failures and proposes revised instructions.
    """
    update_type: Literal["revise_step", "insert_step_before", "request_context", "request_human_action", "abort"] = Field(
        description="The type of plan modification needed."
    )
    diagnosis: str = Field(
        description="One short sentence describing the failure cause."
    )
    proposed_step: Optional[str] = Field(
        default=None,
        description="A single revised high-level step if update_type is 'revise_step'."
    )
    insert_step: Optional[str] = Field(
        default=None,
        description="A prerequisite step to insert before the failed step if update_type is 'insert_step_before'."
    )
    requested_context: List[str] = Field(
        default_factory=list,
        description="Specific pieces of missing information needed if update_type is 'request_context'."
    )
    message_to_orchestration: str = Field(
        description="One concise instruction describing what to change next."
    )


# =============================================================================
# INTERACTION LAYER
# Aligned with: prompts/interaction.prompt.md
# =============================================================================

class InteractionResponse(BaseModel):
    """
    Schema for the Interaction Agent's user-facing output.
    Formats internal results into clear user responses.
    """
    type: Literal["finish", "request"] = Field(
        description="'finish' for completed tasks, 'request' for clarification needed."
    )
    message: str = Field(
        description="Clean, user-facing summary or clarification request."
    )
    data: Optional[str] = Field(
        default=None,
        description="Final result or summary data if type is 'finish'."
    )
    requested_fields: List[str] = Field(
        default_factory=list,
        description="Specific missing information needed if type is 'request'."
    )


# =============================================================================
# INTERACTION SUPPORT
# =============================================================================

class HumanInterrupt(BaseModel):
    """Schema for when the agent needs to pause and ask the user for help."""
    interrupt_type: Literal[
        "AUTH_BLOCK",
        "CLARIFY_INTENT",
        "TECHNICAL_RECOVERY",
        "SAFETY_CHECK",
        "STATUS_SYNC"
    ] = Field(description="The category of the interruption.")

    internal_reasoning: str = Field(description="CoT: Why are we stopping?")
    user_facing_question: str = Field(description="The elevated prose to show the user.")
    suggested_options: Optional[List[str]] = Field(
        default=None,
        description="Pre-defined buttons for the user to click."
    )
