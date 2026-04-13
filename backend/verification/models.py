"""
Data models for Verification System.

This module defines the input/output contracts for the verification system,
which evaluates execution results and returns confidence scores, problems, and fixes.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, Literal

# Import ExecutionOutput from execution module for type hints
# Use forward reference to avoid circular imports if needed
from backend.execution.models import ExecutionOutput


class EvaluationResult(BaseModel):
    """
    Output from the rule-based verification evaluator to orchestration.

    Orchestration uses these fields to decide:
    - confidence_score > 0.9 -> success, continue to next step
    - confidence_score <= 0.9 -> failure, pass problem/fix to Fallback

    Not to be confused with schema.VerificationResult which is the
    LLM-based verifier's output used inside the LangGraph workflow.
    """

    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence that the execution achieved the intended outcome (0.0-1.0)"
    )
    problem: str = Field(
        ...,
        description="Description of what went wrong; empty string if no problem"
    )
    fix: str = Field(
        ...,
        description="Suggested fix for the problem; empty string if no problem"
    )
    uncertainty: Optional[str] = Field(
        default=None,
        description="Optional message for user when outcome is uncertain (stretch goal)"
    )


class VerificationInput(BaseModel):
    """
    Input to the verification system from orchestration.
    
    Contains the execution result plus context needed to evaluate
    how well the execution matched the intended goal/step.
    """

    execution_output: Dict[str, Any] = Field(
        ...,
        description="The ExecutionOutput from the execution step (as dict for flexibility)"
    )
    main_goal: str = Field(
        ...,
        description="The user's original goal/prompt"
    )
    plan_step: Optional[str] = Field(
        default=None,
        description="The specific plan step that was being executed"
    )


# Error type to confidence mapping
# Used by the evaluator to assign confidence scores based on error types
ERROR_TYPE_CONFIDENCE: Dict[str, float] = {
    "none": 1.0,                  # Success
    "element_not_found": 0.3,     # Element missing - likely needs scroll or different selector
    "ambiguous_step": 0.4,        # Step unclear - needs clarification
    "tool_limit": 0.5,            # Tool can't do this - might need different approach
    "navigation_blocked": 0.2,    # Network/URL issue - serious problem
    "unknown": 0.1,               # Unknown error - very low confidence
}


# Error type to suggested fix mapping
# Provides default fixes for common error types
ERROR_TYPE_FIXES: Dict[str, str] = {
    "none": "",
    "element_not_found": "Try scrolling the page to find the element, or verify the element selector/name is correct",
    "ambiguous_step": "Clarify the plan step with more specific instructions or target element details",
    "tool_limit": "Consider using a different action or breaking this step into smaller sub-steps",
    "navigation_blocked": "Check the URL is valid and accessible, or try an alternative URL",
    "unknown": "Review the error message and consider retrying or using an alternative approach",
}
