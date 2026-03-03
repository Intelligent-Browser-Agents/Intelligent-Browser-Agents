# Action Execution Tool - Usage Guide for BI Orchestration

## Overview

This tool **executes browser actions** you specify. You decide WHAT to do, we execute it.

**You provide:** Specific action (click, type, navigate, etc.)
**We execute:** The action using Playwright
**You receive:** Result with success/failure status

---

## Quick Start

### Import
```python
from backend.execution import dispatch_action, Action, ActionArgs
```

### Basic Usage
```python
# 1. You create the action
action = Action(
    action="click",
    args=ActionArgs(role="button", name="Search")
)

# 2. Call the tool
result = await dispatch_action(page, action)

# 3. Handle the result
if result.status == "success":
    print(f"✓ {result.message}")
else:
    print(f"✗ Error: {result.error_type} - {result.message}")
```

---

## API Reference

### Main Function

```python
await dispatch_action(page: Page, action: Action) -> ExecutionOutput
```

**Parameters:**
- `page`: Your Playwright page instance (you manage this)
- `action`: Action object specifying what to execute

**Returns:** `ExecutionOutput` with result details

---

## Creating Actions

### Action Object Structure

```python
Action(
    action="click",  # Action type (see list below)
    args=ActionArgs(...)  # Arguments for that action
)
```

### 7 Available Actions

#### 1. Navigate
```python
Action(
    action="navigate",
    args=ActionArgs(url="https://nike.com")
)
```

#### 2. Click
```python
Action(
    action="click",
    args=ActionArgs(
        role="button",  # ARIA role from DOM
        name="Search"   # Accessible name from DOM
    )
)
```

#### 3. Type
```python
Action(
    action="type",
    args=ActionArgs(text="Nike shoes")
)
```
*Note: Input must already be focused*

#### 4. Search
```python
Action(
    action="search",
    args=ActionArgs(text="running shoes")
)
```
*For search interfaces (Google, site search bars)*

#### 5. Scroll
```python
Action(
    action="scroll",
    args=ActionArgs(direction="down")  # or "up"
)
```

#### 6. Press Key
```python
Action(
    action="press_key",
    args=ActionArgs(key="Enter")  # or "Escape", "ArrowDown", etc.
)
```

#### 7. Wait
```python
Action(
    action="wait",
    args=ActionArgs(seconds=2.0)
)
```

---

## Understanding Results

### ExecutionOutput Structure

```python
ExecutionOutput(
    action="click",                    # What was executed
    args={"role": "button", "name": "Search"},  # With what arguments
    status="success",                  # "success" or "failure"
    error_type="none",                 # Error classification
    message="Clicked button 'Search'", # Human-readable message
    execution_time_ms=245              # Execution time
)
```

### Error Types

| Error Type | Meaning | What To Do |
|-----------|----------|------------|
| `none` | Success | Continue to next action |
| `element_not_found` | Element doesn't exist in DOM | Verify DOM, try scrolling, or adjust action |
| `ambiguous_step` | Action unclear or malformed | Check action arguments |
| `tool_limit` | Action impossible (file upload, CAPTCHA) | Use different approach |
| `navigation_blocked` | Network/CORS/404 error | Check URL validity |
| `unknown` | Unexpected error | Log error, retry or abort |

---

## Complete Example

```python
from backend.execution import dispatch_action, Action, ActionArgs
from playwright.async_api import async_playwright

async def orchestration_example():
    """Example of using the action execution tool."""

    # You manage the browser
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        # Your orchestration logic determines the sequence
        actions = [
            Action(action="navigate", args=ActionArgs(url="https://nike.com")),
            Action(action="click", args=ActionArgs(role="textbox", name="Search")),
            Action(action="type", args=ActionArgs(text="running shoes")),
            Action(action="press_key", args=ActionArgs(key="Enter")),
            Action(action="wait", args=ActionArgs(seconds=2)),
        ]

        # Execute each action
        for action in actions:
            result = await dispatch_action(page, action)

            if result.status == "failure":
                print(f"Action failed: {action.action}")
                print(f"Error: {result.error_type}")
                print(f"Message: {result.message}")

                # Your logic decides what to do
                if result.error_type == "element_not_found":
                    # Maybe try scrolling first?
                    scroll_action = Action(action="scroll", args=ActionArgs(direction="down"))
                    await dispatch_action(page, scroll_action)
                    # Retry original action
                    result = await dispatch_action(page, action)
                else:
                    # Abort on other errors
                    break
            else:
                print(f"✓ Completed: {action.action}")

        await browser.close()
```

---

## Integration Pattern

### Your Orchestration Responsibilities

1. **Browser Management**
   - Create/manage browser instance
   - Create/manage page instances
   - Navigate to initial pages
   - Clean up resources

2. **Action Selection**
   - Analyze DOM (from IG team)
   - Decide which action to take
   - Create Action objects
   - Determine action sequence

3. **Error Handling**
   - Check result.status
   - Handle failures based on error_type
   - Implement retry logic
   - Log for monitoring

### Our Tool Responsibilities

1. **Action Execution**
   - Execute the specific action you provide
   - Use Playwright API correctly
   - Measure execution time
   - Return structured result

---

## Best Practices

### 1. Use ARIA Roles from DOM
```python
# ✓ Good: Use actual ARIA roles and names from DOM
Action(action="click", args=ActionArgs(role="button", name="Submit"))

# ✗ Bad: Guessing roles/names
Action(action="click", args=ActionArgs(role="div", name="submit-btn"))
```

### 2. Handle All Error Types
```python
result = await dispatch_action(page, action)

if result.status == "failure":
    if result.error_type == "element_not_found":
        # Element missing - maybe scroll or wait
        pass
    elif result.error_type == "navigation_blocked":
        # Bad URL or network issue
        pass
    elif result.error_type == "tool_limit":
        # Action not possible - find alternative
        pass
    # ... handle other types
```

### 3. Track Execution Time
```python
result = await dispatch_action(page, action)
print(f"Action took {result.execution_time_ms}ms")

if result.execution_time_ms > 5000:
    # Action was slow, maybe page is loading
    pass
```

### 4. Focus Elements Before Typing
```python
# First click to focus
click_result = await dispatch_action(
    page,
    Action(action="click", args=ActionArgs(role="textbox", name="Search"))
)

# Then type
if click_result.status == "success":
    type_result = await dispatch_action(
        page,
        Action(action="type", args=ActionArgs(text="query"))
    )
```

---

## Action Arguments Reference

### Navigate
```python
ActionArgs(url="https://example.com")  # Required
```

### Click
```python
ActionArgs(
    role="button",  # Optional but recommended
    name="Submit"   # Optional but recommended
)
# At least one (role or name) should be provided
```

### Type
```python
ActionArgs(text="text to type")  # Required
```

### Search
```python
ActionArgs(text="search query")  # Required
```

### Scroll
```python
ActionArgs(direction="down")  # Required: "up" or "down"
```

### Press Key
```python
ActionArgs(key="Enter")  # Required: key name
# Examples: "Enter", "Escape", "Tab", "ArrowDown", "Space"
```

### Wait
```python
ActionArgs(seconds=2.0)  # Required: float
```

---

## Troubleshooting

### Element Not Found Errors
**Cause:** Element doesn't exist or wrong role/name
**Solution:**
- Verify DOM extraction includes element
- Check ARIA role and accessible name
- Try scrolling first
- Wait for page to load

### Navigation Blocked
**Cause:** Invalid URL, network issue, CORS
**Solution:**
- Verify URL is valid and accessible
- Check network connection
- Ensure page allows navigation

### Action Takes Too Long
**Cause:** Page loading, slow network
**Solution:**
- Check execution_time_ms in result
- Wait before retrying
- Verify page responsiveness

---

## Integration Checklist

- [ ] Import: `from backend.execution import dispatch_action, Action, ActionArgs`
- [ ] Create and manage your browser/page instances
- [ ] Get DOM from IG team's extraction tool
- [ ] Analyze DOM to decide actions
- [ ] Create Action objects with correct arguments
- [ ] Call `dispatch_action(page, action)`
- [ ] Check `result.status` for success/failure
- [ ] Handle errors based on `result.error_type`
- [ ] Log execution times for monitoring
- [ ] Clean up browser resources when done

---

## Questions?

**What if I need to do something not in the 7 actions?**
The 7 actions cover most web automation needs. If you need something specific, discuss with the Action Execution team.

**Who decides the sequence of actions?**
You do! Your orchestration system determines the order and which actions to execute.

**What if an action fails?**
Check `result.error_type` and decide: retry, adjust action, or abort. Your orchestration controls error handling.

**Do you manage the browser?**
No, you create and manage the browser and page instances. We just use the page you provide.
