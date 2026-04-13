"""
Unit tests for verification evaluator.

Tests evaluate() for success, all failure error types, dict input,
plan_step, uncertainty, action-specific fixes, and edge cases.
"""

import pytest
from backend.execution.models import ExecutionOutput
from backend.verification.evaluator import evaluate
from backend.verification.models import (
    ERROR_TYPE_CONFIDENCE,
    ERROR_TYPE_FIXES,
)


def make_output(
    *,
    action: str = "click",
    args: dict = None,
    status: str = "failure",
    error_type: str = "element_not_found",
    message: str = "Could not find element",
    execution_time_ms: int = 100,
) -> ExecutionOutput:
    """Build ExecutionOutput with defaults; override only what the test needs."""
    return ExecutionOutput(
        action=action,
        args=args or {},
        status=status,
        error_type=error_type,
        message=message,
        execution_time_ms=execution_time_ms,
    )


# --- 1. Success ---


def test_evaluate_success():
    """Success: status=success, error_type=none -> confidence 1.0, empty problem/fix, no uncertainty."""
    output = make_output(status="success", error_type="none", message="Clicked button")
    result = evaluate(output, "Find Nike shoes", "Click the search button")
    assert result.confidence_score == 1.0
    assert result.problem == ""
    assert result.fix == ""
    assert result.uncertainty is None


# --- 2. Failure per error type ---


@pytest.mark.parametrize(
    "error_type,expected_confidence",
    [
        ("element_not_found", 0.3),
        ("ambiguous_step", 0.4),
        ("tool_limit", 0.5),
        ("navigation_blocked", 0.2),
        ("unknown", 0.1),
    ],
)
def test_evaluate_failure_per_error_type(error_type, expected_confidence):
    """Failure with each error type: correct confidence, non-empty problem and fix."""
    output = make_output(
        status="failure",
        error_type=error_type,
        message="Something went wrong",
    )
    result = evaluate(output, "Main goal", None)
    assert result.confidence_score == expected_confidence
    assert result.confidence_score == ERROR_TYPE_CONFIDENCE[error_type]
    assert result.problem != ""
    assert result.fix != ""


# --- 3. Edge: success but error_type != "none" ---


def test_evaluate_success_but_error_type_not_none():
    """Edge: status=success with error_type != none -> confidence 0.8, non-empty problem/fix."""
    output = make_output(
        status="success",
        error_type="element_not_found",
        message="Strange state",
    )
    result = evaluate(output, "Goal", None)
    assert result.confidence_score == 0.8
    assert result.problem != ""
    assert result.fix != ""


# --- 4. Dict input ---


def test_evaluate_dict_input_success():
    """Dict input for success produces same result as ExecutionOutput."""
    output_obj = make_output(status="success", error_type="none", message="Done")
    output_dict = {
        "action": output_obj.action,
        "args": output_obj.args,
        "status": output_obj.status,
        "error_type": output_obj.error_type,
        "message": output_obj.message,
        "execution_time_ms": output_obj.execution_time_ms,
    }
    result_obj = evaluate(output_obj, "Goal", None)
    result_dict = evaluate(output_dict, "Goal", None)
    assert result_dict.confidence_score == result_obj.confidence_score
    assert result_dict.problem == result_obj.problem
    assert result_dict.fix == result_obj.fix
    assert result_dict.uncertainty == result_obj.uncertainty


def test_evaluate_dict_input_failure():
    """Dict input for failure produces same result as ExecutionOutput."""
    output_obj = make_output(
        status="failure",
        error_type="navigation_blocked",
        message="Blocked",
    )
    output_dict = {
        "action": output_obj.action,
        "args": output_obj.args,
        "status": output_obj.status,
        "error_type": output_obj.error_type,
        "message": output_obj.message,
        "execution_time_ms": output_obj.execution_time_ms,
    }
    result_obj = evaluate(output_obj, "Goal", None)
    result_dict = evaluate(output_dict, "Goal", None)
    assert result_dict.confidence_score == result_obj.confidence_score
    assert result_dict.problem == result_obj.problem
    assert result_dict.fix == result_obj.fix


# --- 5. plan_step present ---


def test_evaluate_plan_step_present():
    """Failure with plan_step: problem ends with (while trying to: ...)."""
    output = make_output(
        status="failure",
        error_type="element_not_found",
        message="Could not find button 'Submit'",
    )
    plan_step = "Click the Submit button"
    result = evaluate(output, "Submit the form", plan_step=plan_step)
    assert result.problem.endswith("(while trying to: Click the Submit button)")


# --- 6. Uncertainty (confidence in 0.4--0.7) ---


def test_evaluate_uncertainty_ambiguous_step():
    """Failure with ambiguous_step (confidence 0.4): uncertainty is set and contains expected phrasing."""
    output = make_output(
        status="failure",
        error_type="ambiguous_step",
        message="Step unclear",
    )
    result = evaluate(output, "Goal", None)
    assert result.uncertainty is not None
    assert "Could you provide more details?" in result.uncertainty


def test_evaluate_uncertainty_tool_limit():
    """Failure with tool_limit (confidence 0.5): uncertainty is set."""
    output = make_output(
        status="failure",
        error_type="tool_limit",
        message="Tool cannot do this",
    )
    result = evaluate(output, "Goal", None)
    assert result.uncertainty is not None
    assert "try something else" in result.uncertainty or "capabilities" in result.uncertainty


# --- 7. Action-specific fixes ---


def test_evaluate_action_specific_fix_click_element_not_found():
    """(click, element_not_found) -> click-specific fix."""
    output = make_output(
        action="click",
        status="failure",
        error_type="element_not_found",
        message="Not found",
    )
    result = evaluate(output, "Goal", None)
    expected = "Scroll the page to bring the element into view, or verify the button/link name matches exactly"
    assert result.fix == expected


def test_evaluate_action_specific_fix_type_element_not_found():
    """(type, element_not_found) -> type-specific fix."""
    output = make_output(
        action="type",
        status="failure",
        error_type="element_not_found",
        message="Not found",
    )
    result = evaluate(output, "Goal", None)
    expected = "Click the input field first to focus it, then retry typing"
    assert result.fix == expected


def test_evaluate_action_specific_fix_navigate_navigation_blocked():
    """(navigate, navigation_blocked) -> navigate-specific fix."""
    output = make_output(
        action="navigate",
        status="failure",
        error_type="navigation_blocked",
        message="Blocked",
    )
    result = evaluate(output, "Goal", None)
    expected = "Verify the URL is correct and the page is accessible, or try searching for the site instead"
    assert result.fix == expected


def test_evaluate_action_specific_fix_search_element_not_found():
    """(search, element_not_found) -> search-specific fix."""
    output = make_output(
        action="search",
        status="failure",
        error_type="element_not_found",
        message="Not found",
    )
    result = evaluate(output, "Goal", None)
    expected = "Navigate to a search page first, or try clicking the search box before searching"
    assert result.fix == expected


def test_evaluate_action_specific_fix_scroll_tool_limit():
    """(scroll, tool_limit) -> scroll-specific fix."""
    output = make_output(
        action="scroll",
        status="failure",
        error_type="tool_limit",
        message="Cannot scroll",
    )
    result = evaluate(output, "Goal", None)
    expected = "The page may not be scrollable, try clicking on the content area first"
    assert result.fix == expected


# --- 8. Empty message (fallback problem text) ---


def test_evaluate_empty_message_uses_fallback_problem():
    """Failure with message='': problem uses fallback error description."""
    output = make_output(
        status="failure",
        error_type="element_not_found",
        message="",
    )
    result = evaluate(output, "Goal", None)
    assert "Could not find the target element" in result.problem
    assert "click" in result.problem  # action is "click" by default


def test_evaluate_empty_message_with_plan_step_includes_plan_step():
    """Failure with message='' and plan_step: problem includes plan_step."""
    output = make_output(
        status="failure",
        error_type="element_not_found",
        message="",
    )
    result = evaluate(output, "Goal", plan_step="Click the button")
    assert result.problem.endswith("(while trying to: Click the button)")


# --- 9. Unknown error_type ---


def test_evaluate_unknown_error_type():
    """Failure with error_type not in ERROR_TYPE_CONFIDENCE -> confidence 0.1, generic fix."""
    output = ExecutionOutput.model_construct(
        action="click",
        args={},
        status="failure",
        error_type="typo_error",
        message="Something went wrong",
        execution_time_ms=100,
    )
    result = evaluate(output, "Goal", None)
    assert result.confidence_score == 0.1
    assert result.fix == "Review the error and retry"
