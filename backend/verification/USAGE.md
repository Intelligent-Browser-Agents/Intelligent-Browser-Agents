# Verification Evaluator Usage

## Overview

The verification system evaluates execution results and returns confidence scores, problem descriptions, and suggested fixes. Use this after each execution step to determine success or failure.

## Main Function

### `evaluate(execution_output, main_goal, plan_step=None)`

**Purpose:** Evaluate an execution result and determine if it achieved the intended outcome.

**Parameters:**
- `execution_output` (ExecutionOutput | dict): Result from execution containing action, status, error_type, message, and execution_time_ms
- `main_goal` (str): User's original goal/prompt for context
- `plan_step` (str, optional): Specific plan step being executed for context

**Returns:** `VerificationResult` containing:
- `confidence_score` (float): 0.0-1.0, where >0.9 indicates success
- `problem` (str): Description of what went wrong (empty if successful)
- `fix` (str): Suggested fix (empty if successful)
- `uncertainty` (str | None): User-facing message when confidence is 0.4-0.7

## When to Call

Call `evaluate()` after **every** execution step, before proceeding to the next action.

### Decision Flow
```
Execute action → evaluate() → Check confidence_score
├─ >0.9: Success → Continue to next step
└─ ≤0.9: Failure → Pass problem/fix to Fallback for retry
```

## Usage Examples

### Success Case

```python
from backend.execution.models import ExecutionOutput
from backend.verification.evaluator import evaluate

output = ExecutionOutput(
    action="click",
    args={"role": "button", "name": "Search"},
    status="success",
    error_type="none",
    message="Clicked button 'Search'",
    execution_time_ms=150
)

result = evaluate(
    execution_output=output,
    main_goal="Find Nike shoes",
    plan_step="Click the search button"
)

# result.confidence_score = 1.0
# result.problem = ""
# result.fix = ""
```

### Failure Case - Element Not Found

```python
output = ExecutionOutput(
    action="click",
    args={"role": "button", "name": "Submit"},
    status="failure",
    error_type="element_not_found",
    message="Could not find button 'Submit'",
    execution_time_ms=3000
)

result = evaluate(
    execution_output=output,
    main_goal="Submit the form",
    plan_step="Click Submit button"
)

# result.confidence_score = 0.3
# result.problem = "Could not find button 'Submit' (while trying to: Click Submit button)"
# result.fix = "Scroll the page to bring the element into view, or verify the button/link name matches exactly"
```

### Failure Case - Navigation Blocked

```python
output = ExecutionOutput(
    action="navigate",
    args={"url": "https://example.com"},
    status="failure",
    error_type="navigation_blocked",
    message="Failed to navigate: Connection timeout",
    execution_time_ms=5000
)

result = evaluate(
    execution_output=output,
    main_goal="Access the example website",
    plan_step="Navigate to example.com"
)

# result.confidence_score = 0.2
# result.problem = "Failed to navigate: Connection timeout (while trying to: Navigate to example.com)"
# result.fix = "Verify the URL is correct and the page is accessible, or try an alternative URL"
```

### Using Dict Instead of ExecutionOutput

```python
output_dict = {
    "action": "type",
    "args": {"role": "textbox", "name": "Email", "value": "user@example.com"},
    "status": "success",
    "error_type": "none",
    "message": "Typed into textbox 'Email'",
    "execution_time_ms": 200
}

result = evaluate(
    execution_output=output_dict,
    main_goal="Fill out registration form",
    plan_step="Enter email address"
)

# result.confidence_score = 1.0
```

## Error Types and Confidence Scores

| Error Type | Confidence Score | Meaning |
|------------|-----------------|---------|
| `none` | 1.0 | Success |
| `element_not_found` | 0.3 | Element missing, likely needs scroll or different selector |
| `ambiguous_step` | 0.4 | Step unclear, needs clarification |
| `tool_limit` | 0.5 | Tool can't perform action, needs different approach |
| `navigation_blocked` | 0.2 | Network/URL issue |
| `unknown` | 0.1 | Unknown error |

## Suggested Fixes by Error Type

### `element_not_found`
- **Generic:** "Try scrolling the page to find the element, or verify the element selector/name is correct"
- **Click:** "Scroll the page to bring the element into view, or verify the button/link name matches exactly"
- **Type:** "Click the input field first to focus it, then retry typing"
- **Search:** "Navigate to a search page first, or try clicking the search box before searching"

### `ambiguous_step`
"Clarify the plan step with more specific instructions or target element details"

### `tool_limit`
- **Generic:** "Consider using a different action or breaking this step into smaller sub-steps"
- **Scroll:** "The page may not be scrollable, try clicking on the content area first"

### `navigation_blocked`
- **Navigate:** "Verify the URL is correct and the page is accessible, or try searching for the site instead"
- **Generic:** "Check the URL is valid and accessible, or try an alternative URL"

### `unknown`
"Review the error message and consider retrying or using an alternative approach"

## Integration with Orchestration

```python
# In orchestration loop
for step in plan_steps:
    # Execute the step
    execution_output = executor.execute(step)
    
    # Verify the result
    verification = evaluate(
        execution_output=execution_output,
        main_goal=user_goal,
        plan_step=step.description
    )
    
    # Decision based on confidence
    if verification.confidence_score > 0.9:
        # Success - continue to next step
        continue
    else:
        # Failure - invoke Fallback
        fallback_result = fallback.handle_failure(
            problem=verification.problem,
            suggested_fix=verification.fix,
            original_step=step
        )
        
        # Use fallback_result for retry or alternative approach
```

## Uncertainty Messages

When `confidence_score` is between 0.4-0.7, the `uncertainty` field contains a user-facing message:

| Error Type | Uncertainty Message |
|------------|-------------------|
| `element_not_found` | "I had trouble finding the element on the page. Would you like me to try a different approach?" |
| `ambiguous_step` | "I'm not sure exactly what action to take here. Could you provide more details?" |
| `tool_limit` | "This action may not be possible with current capabilities. Would you like to try something else?" |
| `navigation_blocked` | "I couldn't access the page. Would you like me to try a different URL?" |
| Other | "I encountered an issue and may need your help to continue." |

Use this field to prompt user input when the agent is uncertain about how to proceed.

## Models Reference

### VerificationResult
```python
class VerificationResult(BaseModel):
    confidence_score: float  # 0.0-1.0
    problem: str             # Empty if success
    fix: str                 # Empty if success
    uncertainty: Optional[str]  # Set when 0.4 <= confidence <= 0.7
```

### ExecutionOutput
```python
class ExecutionOutput(BaseModel):
    action: str              # e.g., "click", "type", "navigate"
    args: Dict[str, Any]     # Action arguments
    status: str              # "success" or "failure"
    error_type: str          # "none", "element_not_found", etc.
    message: str             # Human-readable result message
    execution_time_ms: int   # Execution duration
```
