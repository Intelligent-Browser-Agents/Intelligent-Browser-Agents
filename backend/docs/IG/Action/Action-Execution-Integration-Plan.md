# Action Execution: Integration Plan

## Scope Clarification

**What Action Execution Does:**
- Provides a **tool** that BI team's orchestration calls
- Receives ExecutionInput (plan step + DOM snapshot) from BI orchestration
- Translates plan step into specific browser action (e.g., "Search for Nike shoes" → `search("Nike shoes")`)
- Executes action via Playwright on browser managed by BI team
- Returns ExecutionOutput with result

**What Action Execution Does NOT Do:**
- Does NOT manage the browser (BI team provides Page instance)
- Does NOT call DOM extraction (BI team provides DOM snapshot)
- Does NOT call Data Processing Tool (BI team handles verification)
- Does NOT create multi-step plans (BI orchestration's job)
- Does NOT decide next steps (BI orchestration's job)
- Does NOT retry or implement fallback strategies (handled upstream)

**LLM Usage Note**: LLM is used ONLY to translate a high-level step like "Search for Nike shoes" into a specific action like `{"action": "search", "text": "Nike shoes"}` with proper DOM element targeting. It does NOT generate plans.

**Integration Model**:
```
BI Orchestration → execute_step(ExecutionInput, Page) → ExecutionOutput
```

---

## Repository Structure
```
backend/
├── execution/
│   ├── __init__.py         # Module exports
│   ├── models.py           # Data models (ExecutionInput/Output, Action)
│   ├── handlers.py         # Playwright action handlers
│   ├── dispatcher.py       # Action routing
│   ├── translator.py       # LLM step → action translator
│   └── executor.py         # Main entry point
└── tests/execution/
    ├── conftest.py         # Test fixtures
    ├── test_handlers.py    # Handler unit tests
    ├── test_dispatcher.py  # Dispatcher unit tests
    ├── test_translator.py  # Translator unit tests
    └── test_integration.py # End-to-end integration tests
```

---

## PR #1: Data Models

**Core Logic**: Define input/output contracts

**Files**:
```
+ backend/execution/__init__.py
+ backend/execution/models.py
```

**Implementation**:
```python
# backend/execution/models.py
from pydantic import BaseModel
from typing import Literal, Optional

class ActionArgs(BaseModel):
    url: Optional[str] = None
    role: Optional[str] = None
    name: Optional[str] = None
    text: Optional[str] = None
    direction: Optional[Literal["up", "down"]] = None
    key: Optional[str] = None
    seconds: Optional[float] = None

class Action(BaseModel):
    action: Literal["navigate", "click", "type", "search", "scroll", "press_key", "wait"]
    args: ActionArgs

class ExecutionInput(BaseModel):
    """Input from BI orchestration agent"""
    plan_step: str              # e.g., "Search for Nike shoes"
    dom_snapshot: dict          # From IG DOM extraction (provided by BI)
    url: str
    main_goal: str              # Context only

class ExecutionOutput(BaseModel):
    """Output returned to BI orchestration"""
    action: str
    args: dict
    status: Literal["success", "failure"]
    error_type: Literal["none", "element_not_found", "ambiguous_step", "tool_limit", "navigation_blocked", "unknown"]
    message: str
    execution_time_ms: int
```

**Tests**: Model validation

**Status**: ✅ Completed

---

## PR #2: Playwright Action Handlers

**Core Logic**: Implement 7 browser actions using Playwright

**Files**:
```
+ backend/execution/handlers.py
+ backend/tests/execution/test_handlers.py
```

**Implementation** (excerpt):
```python
# backend/execution/handlers.py
from playwright.async_api import Page
from .models import ExecutionOutput
import asyncio

async def handle_navigate(page: Page, url: str) -> ExecutionOutput:
    start = asyncio.get_event_loop().time()
    try:
        await page.goto(url, timeout=10000)
        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionOutput(
            action="navigate",
            args={"url": url},
            status="success",
            error_type="none",
            message=f"Navigated to {url}",
            execution_time_ms=elapsed
        )
    except Exception as e:
        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionOutput(
            action="navigate",
            args={"url": url},
            status="failure",
            error_type="navigation_blocked",
            message=str(e),
            execution_time_ms=elapsed
        )

async def handle_click(page: Page, role: str, name: str) -> ExecutionOutput:
    start = asyncio.get_event_loop().time()
    try:
        # Try role + name
        if role and name:
            await page.get_by_role(role, name=name).click(timeout=3000)
        # Try role only
        elif role:
            await page.get_by_role(role).click(timeout=3000)
        # Try text only
        elif name:
            await page.get_by_text(name).click(timeout=3000)

        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionOutput(
            action="click",
            args={"role": role, "name": name},
            status="success",
            error_type="none",
            message=f"Clicked {role} '{name}'",
            execution_time_ms=elapsed
        )
    except Exception as e:
        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionOutput(
            action="click",
            args={"role": role, "name": name},
            status="failure",
            error_type="element_not_found",
            message=str(e),
            execution_time_ms=elapsed
        )

async def handle_type(page: Page, text: str) -> ExecutionOutput:
    """Type text into focused input"""
    # Implementation...

async def handle_search(page: Page, query: str) -> ExecutionOutput:
    """Execute search on Google or search UI"""
    # Implementation...

async def handle_scroll(page: Page, direction: str) -> ExecutionOutput:
    """Scroll page up or down"""
    # Implementation...

async def handle_press_key(page: Page, key: str) -> ExecutionOutput:
    """Press keyboard key"""
    # Implementation...

async def handle_wait(page: Page, seconds: float) -> ExecutionOutput:
    """Wait for duration"""
    # Implementation...
```

**Tests**: Mock Playwright page, test each handler with success/failure cases

**Status**: ✅ Completed

---

## PR #3: Action Dispatcher

**Core Logic**: Route Action to correct handler

**Files**:
```
+ backend/execution/dispatcher.py
+ backend/tests/execution/test_dispatcher.py
```

**Implementation**:
```python
# backend/execution/dispatcher.py
from playwright.async_api import Page
from .models import Action, ExecutionOutput
from .handlers import *

async def dispatch_action(page: Page, action: Action) -> ExecutionOutput:
    """Route action to handler"""
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
        return ExecutionOutput(
            action=action.action,
            args=action.args.dict(),
            status="failure",
            error_type="unknown",
            message=f"Unknown action: {action.action}",
            execution_time_ms=0
        )

    return await handler()
```

**Tests**: Verify correct routing, handle unknown actions

**Status**: ✅ Completed

---

## PR #4: LLM Action Translator

**Core Logic**: Translate plan step → specific Action using LLM

**Why LLM?** Plan step is high-level ("Search for Nike shoes"). LLM translates to specific action (`{"action": "search", "text": "Nike shoes"}`) using DOM context to find correct elements.

**Files**:
```
+ backend/execution/translator.py
+ backend/tests/execution/test_translator.py
```

**Implementation**:
```python
# backend/execution/translator.py
import json
from openai import AsyncOpenAI
from .models import Action

TRANSLATOR_PROMPT = """
You are an action translator for browser automation.

Given:
- PLAN_STEP: High-level step to execute
- DOM_SNAPSHOT: Current page elements
- URL: Current page

Output ONE JSON action:
{
  "action": "navigate|click|type|search|scroll|press_key|wait",
  "args": {
    "url": "...",        // for navigate
    "role": "...",       // for click (ARIA role from DOM)
    "name": "...",       // for click (accessible name from DOM)
    "text": "...",       // for type/search
    "direction": "...",  // for scroll
    "key": "...",        // for press_key
    "seconds": 0         // for wait
  }
}

Rules:
- ONLY use elements present in DOM_SNAPSHOT
- Choose ONE action that moves the plan step forward
- Be specific with role/name for clicks
"""

class ActionTranslator:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def translate(
        self,
        plan_step: str,
        dom_snapshot: dict,
        url: str,
        main_goal: str
    ) -> Action:
        """Translate plan step to specific action"""

        dom_json = json.dumps(dom_snapshot, indent=2)

        prompt = f"""
MAIN_GOAL: {main_goal}
PLAN_STEP: {plan_step}
URL: {url}

DOM_SNAPSHOT:
{dom_json}

Translate the plan step into ONE specific action.
"""

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": TRANSLATOR_PROMPT},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )

        content = response.choices[0].message.content
        action_data = json.loads(content)

        return Action(**action_data)
```

**Tests**: Mock LLM responses, validate JSON output

---

## PR #5: Main Execution Flow

**Core Logic**: Orchestrate translation → dispatch → execute

**Files**:
```
+ backend/execution/executor.py
~ backend/execution/__init__.py
```

**Implementation**:
```python
# backend/execution/executor.py
from playwright.async_api import Page
from .models import ExecutionInput, ExecutionOutput
from .translator import ActionTranslator
from .dispatcher import dispatch_action
import asyncio

async def execute_step(
    input_data: ExecutionInput,
    page: Page,
    translator: ActionTranslator
) -> ExecutionOutput:
    """
    Execute a single plan step.

    Flow:
    1. Translate plan step → Action (using LLM + DOM)
    2. Dispatch Action → handler
    3. Execute via Playwright
    4. Return result
    """
    start = asyncio.get_event_loop().time()

    try:
        # Step 1: Translate high-level step to specific action
        action = await translator.translate(
            plan_step=input_data.plan_step,
            dom_snapshot=input_data.dom_snapshot,
            url=input_data.url,
            main_goal=input_data.main_goal
        )

        # Step 2: Execute action
        result = await dispatch_action(page, action)

        return result

    except Exception as e:
        elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
        return ExecutionOutput(
            action="unknown",
            args={},
            status="failure",
            error_type="unknown",
            message=f"Execution failed: {str(e)}",
            execution_time_ms=elapsed
        )
```

**Tests**: Integration tests with mock LLM and real Playwright browser

---

## PR #6: Integration Tests

**Core Logic**: Test the complete execute_step() flow end-to-end

**Files**:
```
+ backend/tests/execution/test_integration.py
```

**Implementation**:
```python
# backend/tests/execution/test_integration.py
import pytest
from backend.execution import execute_step, ExecutionInput
from backend.execution.translator import ActionTranslator

@pytest.mark.asyncio
async def test_google_search_integration(page):
    """Test complete flow: translate → dispatch → execute"""
    # Setup
    await page.goto("https://google.com")
    dom_snapshot = await page.accessibility.snapshot()

    # Create input
    input_data = ExecutionInput(
        plan_step="Search for 'Python programming'",
        dom_snapshot=dom_snapshot,
        url=page.url,
        main_goal="Find Python tutorials"
    )

    # Create translator
    translator = ActionTranslator(api_key="test-key", model="gpt-4o-mini")

    # Execute
    result = await execute_step(input_data, page, translator)

    # Verify
    assert result.status == "success"
    assert result.action == "search"
    assert "Python programming" in result.message

@pytest.mark.asyncio
async def test_navigate_and_click_integration(page):
    """Test sequential actions work correctly"""
    # Navigate
    input1 = ExecutionInput(
        plan_step="Go to example.com",
        dom_snapshot={},
        url="",
        main_goal="Test navigation"
    )
    result1 = await execute_step(input1, page, translator)
    assert result1.status == "success"

    # Click
    dom_snapshot = await page.accessibility.snapshot()
    input2 = ExecutionInput(
        plan_step="Click the 'More information' link",
        dom_snapshot=dom_snapshot,
        url=page.url,
        main_goal="Test clicking"
    )
    result2 = await execute_step(input2, page, translator)
    assert result2.action == "click"

@pytest.mark.asyncio
async def test_error_handling_integration(page):
    """Test error handling in complete flow"""
    input_data = ExecutionInput(
        plan_step="Click a button that doesn't exist",
        dom_snapshot={},
        url="data:text/html,<div>No buttons</div>",
        main_goal="Test error handling"
    )

    result = await execute_step(input_data, page, translator)
    assert result.status == "failure"
    assert result.error_type in ["element_not_found", "ambiguous_step"]
```

**Tests**: Full flow with real browser, mock LLM responses

---

## Integration Points Summary

| Component | Owner | Interface |
|-----------|-------|-----------|
| **BI Orchestration** | Browser Interaction | Calls `execute_step(ExecutionInput, Page)` → Action Execution |
| **DOM Extraction** | Information Gathering | Provides DOM snapshots → BI Orchestration → Action Execution |
| **Data Processing Tool** | Information Gathering | Receives ExecutionOutput ← BI Orchestration |
| **Playwright Browser** | Browser Interaction | BI manages browser, provides Page instance to Action Execution |

**Key Point**: Action Execution is a **tool** called by BI's orchestration. It does not directly interface with IG's DOM Extraction or Data Processing Tool.

---

## Definition of Done (Each PR)

- [x] **PR-1**: Data Models ✅ Completed
- [x] **PR-2**: Action Handlers ✅ Completed
- [x] **PR-3**: Action Dispatcher ✅ Completed
- [ ] **PR-4**: LLM Action Translator (In Progress)
- [ ] **PR-5**: Main Entry Point
- [ ] **PR-6**: Integration Tests

**Per-PR Checklist**:
- [ ] Core logic implemented
- [ ] Unit tests passing (90%+ coverage)
- [ ] Integration tests passing (if applicable)
- [ ] Code reviewed by 1+ team member
- [ ] Documentation updated
- [ ] PR merged to main

---

## Notes

**Scope Reminder**: Action Execution provides a **tool** for BI's orchestration. It does NOT:
- Manage the browser (BI provides Page instance)
- Call DOM extraction (BI provides DOM snapshot)
- Call Data Processing Tool (BI handles verification)
- Create multi-step plans (BI orchestration does this)
- Decide next steps (BI orchestration does this)
- Retry failures (handled by BI orchestration or fallback agents)

**LLM Clarification**: LLM is used ONLY to translate high-level plan steps into specific actions with DOM element targeting. It is NOT used for planning or strategy.

**API Surface**: The tool exports a single function:
```python
async def execute_step(
    input_data: ExecutionInput,
    page: Page,
    translator: ActionTranslator
) -> ExecutionOutput
```
