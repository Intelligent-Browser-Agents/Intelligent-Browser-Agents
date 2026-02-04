"""
Verification Evaluator for Browser Automation.

This module provides the main evaluation function that takes an ExecutionOutput
and returns a VerificationResult with confidence_score, problem, and fix.

The evaluator uses rule-based logic to map execution status and error types
to confidence scores and suggested fixes. It can be extended with LLM-based
evaluation for more nuanced assessments.
"""

from typing import Optional, Union, Dict, Any

from backend.execution.models import ExecutionOutput
from .models import (
    VerificationResult,
    ERROR_TYPE_CONFIDENCE,
    ERROR_TYPE_FIXES,
)


def evaluate(
    execution_output: Union[ExecutionOutput, Dict[str, Any]],
    main_goal: str,
    plan_step: Optional[str] = None
) -> VerificationResult:
    """
    Evaluate an execution result and return confidence, problem, and fix.
    
    This is the main entry point for the verification system. Orchestration
    calls this after each execution step to determine success or failure.
    
    Args:
        execution_output: The result from execution (ExecutionOutput or dict).
                         Contains: action, args, status, error_type, message, execution_time_ms
        main_goal: The user's original goal/prompt (for context)
        plan_step: The specific plan step that was executed (optional, for context)
    
    Returns:
        VerificationResult with:
        - confidence_score: float (0.0-1.0), >0.9 means success
        - problem: str describing what went wrong (empty if success)
        - fix: str with suggested fix (empty if success)
        - uncertainty: Optional[str] for user-facing message (stretch goal)
    
    Example:
        >>> from backend.execution.models import ExecutionOutput
        >>> from backend.verification import evaluate
        >>> 
        >>> # Success case
        >>> output = ExecutionOutput(
        ...     action="click",
        ...     args={"role": "button", "name": "Search"},
        ...     status="success",
        ...     error_type="none",
        ...     message="Clicked button 'Search'",
        ...     execution_time_ms=150
        ... )
        >>> result = evaluate(output, "Find Nike shoes", "Click the search button")
        >>> result.confidence_score  # 1.0
        >>> result.problem  # ""
        >>> 
        >>> # Failure case
        >>> output = ExecutionOutput(
        ...     action="click",
        ...     args={"role": "button", "name": "Submit"},
        ...     status="failure",
        ...     error_type="element_not_found",
        ...     message="Could not find button 'Submit'",
        ...     execution_time_ms=3000
        ... )
        >>> result = evaluate(output, "Submit the form", "Click Submit button")
        >>> result.confidence_score  # 0.3
        >>> result.problem  # "Could not find button 'Submit'"
        >>> result.fix  # "Try scrolling..."
    """
    # Convert dict to ExecutionOutput if needed
    if isinstance(execution_output, dict):
        output = ExecutionOutput(**execution_output)
    else:
        output = execution_output
    
    # Extract key fields
    status = output.status
    error_type = output.error_type
    message = output.message
    action = output.action
    
    # Determine confidence score based on status and error type
    if status == "success" and error_type == "none":
        confidence_score = 1.0
    elif status == "success":
        # Success but with some error type (shouldn't happen, but handle it)
        confidence_score = 0.8
    else:
        # Failure - use error type mapping
        confidence_score = ERROR_TYPE_CONFIDENCE.get(error_type, 0.1)
    
    # Determine problem description
    if status == "success" and error_type == "none":
        problem = ""
    else:
        # Build problem description from error type and message
        problem = _build_problem_description(action, error_type, message, plan_step)
    
    # Determine suggested fix
    if status == "success" and error_type == "none":
        fix = ""
    else:
        # Get fix from mapping, customize based on context
        fix = _build_fix_suggestion(action, error_type, message, plan_step)
    
    # Build uncertainty message for stretch goal (optional)
    uncertainty = None
    if 0.4 <= confidence_score <= 0.7:
        uncertainty = _build_uncertainty_message(action, error_type, message)
    
    return VerificationResult(
        confidence_score=confidence_score,
        problem=problem,
        fix=fix,
        uncertainty=uncertainty
    )


def _build_problem_description(
    action: str,
    error_type: str,
    message: str,
    plan_step: Optional[str]
) -> str:
    """
    Build a human-readable problem description.
    
    Combines error type context with the execution message.
    """
    # Use the execution message as the primary description
    if message:
        base_problem = message
    else:
        # Fallback descriptions based on error type
        error_descriptions = {
            "element_not_found": f"Could not find the target element for {action}",
            "ambiguous_step": f"The {action} action was unclear or incomplete",
            "tool_limit": f"The {action} action is not supported or cannot be performed",
            "navigation_blocked": f"Navigation was blocked or failed",
            "unknown": f"An unknown error occurred during {action}",
        }
        base_problem = error_descriptions.get(error_type, f"Failed to execute {action}")
    
    # Add plan step context if available
    if plan_step:
        return f"{base_problem} (while trying to: {plan_step})"
    
    return base_problem


def _build_fix_suggestion(
    action: str,
    error_type: str,
    message: str,
    plan_step: Optional[str]
) -> str:
    """
    Build a suggested fix based on error type and context.
    
    Returns a fix suggestion that Fallback can use to retry.
    """
    # Get base fix from mapping
    base_fix = ERROR_TYPE_FIXES.get(error_type, "Review the error and retry")
    
    # Customize fix based on action type
    action_specific_fixes = {
        ("click", "element_not_found"): "Scroll the page to bring the element into view, or verify the button/link name matches exactly",
        ("type", "element_not_found"): "Click the input field first to focus it, then retry typing",
        ("navigate", "navigation_blocked"): "Verify the URL is correct and the page is accessible, or try searching for the site instead",
        ("search", "element_not_found"): "Navigate to a search page first, or try clicking the search box before searching",
        ("scroll", "tool_limit"): "The page may not be scrollable, try clicking on the content area first",
    }
    
    specific_fix = action_specific_fixes.get((action, error_type))
    if specific_fix:
        return specific_fix
    
    return base_fix


def _build_uncertainty_message(
    action: str,
    error_type: str,
    message: str
) -> str:
    """
    Build an uncertainty message for the user (stretch goal).
    
    Used when confidence is in the uncertain range (0.4-0.7).
    """
    uncertainty_messages = {
        "element_not_found": "I had trouble finding the element on the page. Would you like me to try a different approach?",
        "ambiguous_step": "I'm not sure exactly what action to take here. Could you provide more details?",
        "tool_limit": "This action may not be possible with current capabilities. Would you like to try something else?",
        "navigation_blocked": "I couldn't access the page. Would you like me to try a different URL?",
    }
    
    return uncertainty_messages.get(
        error_type,
        "I encountered an issue and may need your help to continue."
    )
