# Action Execution: Technical Implementation

## Scope Clarification

**What Action Execution Does:**
- Provides a tool that receives plan steps from BI's orchestration system
- Translates high-level plan steps into specific browser actions
- Executes actions via Playwright
- Returns structured execution results

**What Action Execution Does NOT Do:**
- Does NOT manage the browser (BI team provides the Page instance)
- Does NOT call DOM extraction (BI team provides DOM snapshot)
- Does NOT call Data Processing Tool (BI team handles verification)
- Does NOT orchestrate multi-step plans (BI team's orchestration handles this)

**Integration Model:**
BI team's orchestration → calls `execute_step()` → returns `ExecutionOutput`

## Technology Stack

### Core Technologies
- **Python 3.13**: Runtime environment
- **Playwright 1.55.0**: Browser automation framework
- **OpenAI API / Ollama**: LLM inference for plan step translation
- **AsyncIO**: Asynchronous execution model
- **Pydantic 2.12.0**: Data validation and schema enforcement

### Supporting Libraries
- **python-dotenv**: Environment variable management
- **pytest**: Testing framework
- **pytest-asyncio**: Async test support

## Architecture

### Execution Flow

```
┌─────────────────────────────────────────────────┐
│  1. Receive Inputs from BI Orchestration        │
│     • ExecutionInput with plan_step             │
│     • DOM snapshot (from IG team)               │
│     • Page instance (managed by BI)             │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│  2. Translate Plan Step → Action (LLM)          │
│     • Build prompt with DOM context             │
│     • Model: gpt-4o-mini or Ollama              │
│     • Output: JSON action specification         │
│     • Validation: Pydantic schema               │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│  3. Dispatch Action to Handler                  │
│     • Route based on action type                │
│     • Pass to appropriate handler               │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│  4. Execute Browser Action                      │
│     • Execute via Playwright API                │
│     • Measure execution time                    │
│     • Capture any errors                        │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│  5. Return ExecutionOutput to BI                │
│     • Status: success or failure                │
│     • Error type classification                 │
│     • Execution timing                          │
│     • Human-readable message                    │
└─────────────────────────────────────────────────┘
```

## Implementation Details

### 1. Main Entry Point Function

**File**: `backend/execution/executor.py`

**Signature**:
```python
async def execute_step(
    input_data: ExecutionInput,
    page: playwright.async_api.Page,
    translator: ActionTranslator
) -> ExecutionOutput:
    """
    Execute a single plan step using browser automation.

    This is the main entry point called by BI team's orchestration.

    Args:
        input_data: ExecutionInput containing:
            - plan_step: High-level step from orchestrator
            - dom_snapshot: DOM from IG team
            - url: Current page URL
            - main_goal: Overall task objective (context)
        page: Playwright page instance (managed by BI team)
        translator: ActionTranslator instance (with LLM client)

    Returns:
        ExecutionOutput with execution result and metadata
    """
```

**Implementation**:
```python
async def execute_step(input_data, page, translator):
    """Execute one plan step."""
    try:
        # Step 1: Translate high-level step to specific action (using LLM)
        action = await translator.translate(
            plan_step=input_data.plan_step,
            dom_snapshot=input_data.dom_snapshot,
            url=input_data.url,
            main_goal=input_data.main_goal
        )

        # Step 2: Dispatch action to handler and execute
        result = await dispatch_action(page, action)

        return result

    except Exception as e:
        # Handle unexpected errors
        return ExecutionOutput(
            action="unknown",
            args={},
            status="failure",
            error_type="unknown",
            message=f"Execution failed: {str(e)}",
            execution_time_ms=0
        )
```

### 2. Action Handlers

**File**: `backend/3-Execution/execution_agent.py`

Each browser action has a dedicated handler:

#### Navigate
```python
async def handle_navigate(page: Page, url: str) -> dict:
    """
    Navigate to a URL.

    Args:
        page: Playwright page instance
        url: Target URL

    Returns:
        Execution result
    """
    try:
        await page.goto(url, timeout=10000)
        return {
            "status": "success",
            "error_type": "none",
            "message": f"Navigated to {url}"
        }
    except Exception as e:
        return {
            "status": "failure",
            "error_type": "navigation_blocked",
            "message": f"Failed to navigate: {str(e)}"
        }
```

#### Click
```python
async def handle_click(page: Page, role: str, name: str) -> dict:
    """
    Click a DOM element identified by ARIA role and name.

    Args:
        page: Playwright page instance
        role: ARIA role (button, link, textbox, etc.)
        name: Accessible name or label

    Returns:
        Execution result
    """
    try:
        # Preferred: explicit role + name
        if role and name:
            await page.get_by_role(role, name=name).click(timeout=3000)
            return {
                "status": "success",
                "error_type": "none",
                "message": f"Clicked {role} '{name}'"
            }

        # Fallback: try role alone
        if role:
            await page.get_by_role(role).click(timeout=3000)
            return {
                "status": "success",
                "error_type": "none",
                "message": f"Clicked {role}"
            }

        # Fallback: try visible text
        if name:
            await page.get_by_text(name).click(timeout=3000)
            return {
                "status": "success",
                "error_type": "none",
                "message": f"Clicked element with text '{name}'"
            }

    except Exception as e:
        return {
            "status": "failure",
            "error_type": "element_not_found",
            "message": f"Could not click element: {str(e)}"
        }
```

#### Type
```python
async def handle_type(page: Page, text: str) -> dict:
    """
    Type text into focused input field.

    Args:
        page: Playwright page instance
        text: Text to type

    Returns:
        Execution result
    """
    try:
        await page.keyboard.type(text)
        return {
            "status": "success",
            "error_type": "none",
            "message": f"Typed '{text}'"
        }
    except Exception as e:
        return {
            "status": "failure",
            "error_type": "tool_limit",
            "message": f"Failed to type: {str(e)}"
        }
```

#### Search
```python
async def handle_search(page: Page, query: str) -> dict:
    """
    Execute search query on Google or similar search interface.

    Args:
        page: Playwright page instance
        query: Search query

    Returns:
        Execution result
    """
    try:
        # Try Google search box
        search_box = page.get_by_role("combobox", name="Search")
        await search_box.click()
        await search_box.fill(query)
        await page.keyboard.press("Enter")

        return {
            "status": "success",
            "error_type": "none",
            "message": f"Searched for '{query}'"
        }
    except Exception:
        # Fallback: type and press enter
        try:
            await page.keyboard.type(query)
            await page.keyboard.press("Enter")
            return {
                "status": "success",
                "error_type": "none",
                "message": f"Searched for '{query}' (fallback)"
            }
        except Exception as e:
            return {
                "status": "failure",
                "error_type": "element_not_found",
                "message": f"Failed to search: {str(e)}"
            }
```

#### Scroll
```python
async def handle_scroll(page: Page, direction: str) -> dict:
    """
    Scroll page up or down.

    Args:
        page: Playwright page instance
        direction: "up" or "down"

    Returns:
        Execution result
    """
    try:
        delta = 800 if direction.lower() == "down" else -800
        await page.mouse.wheel(0, delta)

        return {
            "status": "success",
            "error_type": "none",
            "message": f"Scrolled {direction}"
        }
    except Exception as e:
        return {
            "status": "failure",
            "error_type": "tool_limit",
            "message": f"Failed to scroll: {str(e)}"
        }
```

#### Press Key
```python
async def handle_press_key(page: Page, key: str) -> dict:
    """
    Press a keyboard key.

    Args:
        page: Playwright page instance
        key: Key name (e.g., "Enter", "Escape", "ArrowDown")

    Returns:
        Execution result
    """
    try:
        await page.keyboard.press(key)
        return {
            "status": "success",
            "error_type": "none",
            "message": f"Pressed '{key}'"
        }
    except Exception as e:
        return {
            "status": "failure",
            "error_type": "tool_limit",
            "message": f"Failed to press key: {str(e)}"
        }
```

#### Wait
```python
async def handle_wait(page: Page, seconds: float) -> dict:
    """
    Wait for specified duration.

    Args:
        page: Playwright page instance
        seconds: Duration in seconds

    Returns:
        Execution result
    """
    try:
        await asyncio.sleep(seconds)
        return {
            "status": "success",
            "error_type": "none",
            "message": f"Waited {seconds}s"
        }
    except Exception as e:
        return {
            "status": "failure",
            "error_type": "tool_limit",
            "message": f"Failed to wait: {str(e)}"
        }
```

### 3. Action Router

```python
async def execute_action(page: Page, action: Action) -> dict:
    """
    Route action to appropriate handler.

    Args:
        page: Playwright page instance
        action: Validated action object

    Returns:
        Execution result
    """
    handlers = {
        "navigate": lambda: handle_navigate(page, action.args.url),
        "click": lambda: handle_click(page, action.args.role, action.args.name),
        "type": lambda: handle_type(page, action.args.text),
        "search": lambda: handle_search(page, action.args.text),
        "scroll": lambda: handle_scroll(page, action.args.direction),
        "press_key": lambda: handle_press_key(page, action.args.key),
        "wait": lambda: handle_wait(page, action.args.seconds)
    }

    handler = handlers.get(action.action)

    if not handler:
        return {
            "status": "failure",
            "error_type": "unknown",
            "message": f"Unknown action: {action.action}"
        }

    return await handler()
```

### 4. Data Models

**File**: `backend/3-Execution/models.py` (to be created)

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal

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
    """Validated action specification."""
    action: Literal["navigate", "click", "type", "search", "scroll", "press_key", "wait"]
    args: ActionArgs
    status: Literal["success", "failure"] = "success"
    error_type: Literal["none", "element_not_found", "ambiguous_step", "tool_limit", "navigation_blocked", "unknown"] = "none"
    message: str

class ExecutionInput(BaseModel):
    """Input to execution agent."""
    main_goal: str
    plan_step: str
    dom_snapshot: dict
    url: str
    allowed_tools: list[str] = [
        "navigate", "click", "type", "search",
        "scroll", "press_key", "wait"
    ]

class ExecutionOutput(BaseModel):
    """Output from execution agent."""
    action: str
    args: dict
    status: Literal["success", "failure"]
    error_type: str
    message: str
    execution_time_ms: int
```

### 5. LLM Prompt Template

**File**: `backend/3-Execution/prompts.py` (to be created)

```python
EXECUTION_PROMPT_TEMPLATE = """
# Component: Execution Agent Prompt

## Purpose
Execute exactly **one** plan step produced by the Orchestration Agent using the allowed browser tools and the current browser state.

## Role Specification
You are the **Execution Agent** for a browser automation system.
Your scope is **local execution only**:
- You receive **one** plan step.
- You choose **one** tool call to move that step forward.
- You do not evaluate the overall plan or final goal correctness.

## Inputs
You will be given:
- MAIN_GOAL: the overall clarified goal (read-only context)
- PLAN_STEP: a single high-level step to accomplish
- DOM_SNAPSHOT: an accessibility/DOM snapshot of the current page
- URL: the current page URL
- ALLOWED_TOOLS: the tool list you may choose from

## Behavioral Boundaries

### You MUST NOT
- Create, reorder, or revise the plan
- Ask the user questions or request additional context
- Perform multi-step strategies in a single response
- Validate whether the overall task is complete
- Format a user-facing response

### You MUST
- Execute **one** plan step **incrementally**
- Choose **exactly one** tool call per output
- Base any click targets ONLY on elements present in DOM_SNAPSHOT
- Return a structured result indicating success/failure for this action attempt

## Tool Selection Rules
- If PLAN_STEP implies moving to a website and URL is known, use `navigate(url)`.
- If PLAN_STEP implies searching and you are on Google (or search UI exists), use `search(query)`.
- If PLAN_STEP implies interacting with a page element, use `click` with an ARIA role + accessible name from DOM_SNAPSHOT.
- Use `type(text)` only when an input is already focused (or when the plan step clearly indicates typing into a field you can target first in a later action).
- Use `scroll(down|up)` when the target is likely off-screen.
- Use `wait(seconds)` only for brief page loading or transitions when no better action is available.
- Use `press_key(key)` for simple submissions/escapes when appropriate.

## Error Handling Strategy
- Do **not** retry.
- Do **not** propose alternatives.
- If you cannot make progress due to missing elements, ambiguity, or tool limitations, return a structured failure explaining why.
- Control will pass to verification/fallback upstream.

## Output Format
You MUST output **one JSON object** and nothing else.

```json
{
  "action": "<navigate|click|type|search|scroll|press_key|wait>",
  "args": {
    "url": "<string or null>",
    "role": "<string or null>",
    "name": "<string or null>",
    "text": "<string or null>",
    "direction": "<up|down|null>",
    "key": "<string or null>",
    "seconds": "<number or null>"
  },
  "status": "<success|failure>",
  "error_type": "<none|element_not_found|ambiguous_step|tool_limit|navigation_blocked|unknown>",
  "message": "<one concise sentence describing what you did or why you failed>"
}
```
"""

def build_execution_prompt(plan_step: str, dom_snapshot: dict, url: str, main_goal: str) -> str:
    """
    Build execution prompt with context.

    Args:
        plan_step: Current step to execute
        dom_snapshot: Page accessibility tree
        url: Current URL
        main_goal: Overall task goal

    Returns:
        Formatted prompt string
    """
    dom_json = json.dumps(dom_snapshot, indent=2)

    return f"""
MAIN_GOAL: {main_goal}
PLAN_STEP: {plan_step}
URL: {url}

DOM_SNAPSHOT:
{dom_json}

Select and execute the appropriate action.
"""
```

## Error Handling

### Error Type Classification

| Error Type | Description | Example |
|------------|-------------|---------|
| `element_not_found` | Target element does not exist in DOM | Clicking non-existent button |
| `ambiguous_step` | Plan step is unclear or underspecified | "Do something with the page" |
| `tool_limit` | Action is outside tool capabilities | Uploading files, handling captchas |
| `navigation_blocked` | Network error or blocked navigation | CORS, timeout, 404 |
| `unknown` | Unexpected error | Playwright crash, system error |

### Error Response Format

```python
{
    "status": "failure",
    "error_type": "element_not_found",
    "message": "Could not find button with role='button' and name='Submit' in DOM snapshot",
    "action": "click",
    "args": {
        "role": "button",
        "name": "Submit"
    }
}
```

## Configuration

### Environment Variables

```bash
# .env file
OPENAI_API_KEY=sk-...
MODEL_NAME=gpt-4o-mini
PLAYWRIGHT_TIMEOUT=10000
EXECUTION_TIMEOUT=30000
```

### Configuration File

**File**: `backend/configs/execution_config.yaml`

```yaml
execution:
  model: gpt-4o-mini
  temperature: 0.0
  max_tokens: 500
  timeout_ms: 30000

playwright:
  browser: chromium
  headless: false
  timeout_ms: 10000
  viewport:
    width: 1280
    height: 720

action_timeouts:
  navigate: 10000
  click: 3000
  type: 2000
  search: 5000
  scroll: 1000
  press_key: 1000
  wait: 60000
```

## Testing Strategy

### Unit Tests

```python
# tests/test_execution_agent.py
import pytest
from execution_agent import execute_action, Action, ActionArgs

@pytest.mark.asyncio
async def test_navigate_success(mock_page):
    """Test successful navigation."""
    action = Action(
        action="navigate",
        args=ActionArgs(url="https://google.com")
    )

    result = await execute_action(mock_page, action)

    assert result["status"] == "success"
    assert result["error_type"] == "none"
    assert "google.com" in result["message"]

@pytest.mark.asyncio
async def test_click_element_not_found(mock_page):
    """Test click when element doesn't exist."""
    action = Action(
        action="click",
        args=ActionArgs(role="button", name="NonExistent")
    )

    result = await execute_action(mock_page, action)

    assert result["status"] == "failure"
    assert result["error_type"] == "element_not_found"
```

### Integration Tests

```python
# tests/test_integration.py
@pytest.mark.asyncio
async def test_google_search_flow(browser):
    """Test complete search flow."""
    page = await browser.new_page()
    await page.goto("https://google.com")

    # Step 1: Extract DOM
    dom_snapshot = await page.accessibility.snapshot()

    # Step 2: Execute search
    result = await execute_step(
        plan_step="Search for 'Python programming'",
        dom_snapshot=dom_snapshot,
        url=page.url,
        main_goal="Find Python tutorials",
        page=page
    )

    assert result["status"] == "success"
    assert result["action"] == "search"
```

## Performance Considerations

### Optimization Strategies

1. **DOM Snapshot Compression**
   - Only include interactive elements
   - Filter out non-visible nodes
   - Compress JSON representation

2. **LLM Call Optimization**
   - Cache model responses for repeated steps
   - Use faster models (gpt-4o-mini instead of gpt-4)
   - Implement request batching where possible

3. **Playwright Performance**
   - Reuse browser contexts
   - Disable unnecessary features (images, CSS)
   - Use browser pooling for parallel execution

4. **Timeout Tuning**
   - Adaptive timeouts based on action type
   - Network condition detection
   - Graceful degradation on slow connections

### Metrics

```python
class ExecutionMetrics:
    """Performance and reliability metrics."""

    total_executions: int
    successful_executions: int
    failed_executions: int
    avg_execution_time_ms: float
    avg_llm_inference_time_ms: float
    avg_browser_action_time_ms: float

    error_distribution: dict[str, int]  # error_type -> count
    action_distribution: dict[str, int]  # action -> count
```

## Deployment Considerations

### Dependencies
- Python 3.13+
- Playwright browsers installed (`playwright install chromium`)
- OpenAI API access or local Ollama instance
- Sufficient memory for browser instances (min 2GB per instance)

### Scalability
- Horizontal: Multiple execution agents with browser pooling
- Vertical: Increase browser instances per agent
- Model serving: Dedicated inference servers for LLM calls

### Monitoring
- Execution success rate
- Action latency distribution
- Error rate by type
- LLM inference time
- Browser memory usage
