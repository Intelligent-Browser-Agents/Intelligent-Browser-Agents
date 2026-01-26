# Action Execution: Integration Plan

## Scope Clarification

**What Action Execution Does:**
- Receives plan step from orchestration (e.g., "Search for Nike shoes")
- Receives DOM snapshot from Information Gathering
- Translates plan step into specific browser action (e.g., `search("Nike shoes")`)
- Executes action via Playwright
- Reports result to Data Processing Tool for validation

**What Action Execution Does NOT Do:**
- Does NOT create multi-step plans (orchestration's job)
- Does NOT decide what the next step should be (orchestration's job)
- Does NOT retry or implement fallback strategies (fallback agent's job)

**LLM Usage Note**: LLM is used ONLY to translate a high-level step like "Search for Python" into a specific action like `{"action": "search", "text": "Python"}` with proper DOM element targeting. It does NOT generate plans.

---

## Repository Structure
```
backend/
├── execution/
│   ├── __init__.py
│   ├── models.py           # Data models
│   ├── handlers.py         # Playwright action handlers
│   ├── dispatcher.py       # Action routing
│   ├── translator.py       # LLM step → action translator
│   └── reporter.py         # Report to Data Processing Tool
└── tests/execution/
    ├── test_handlers.py
    ├── test_dispatcher.py
    └── test_integration.py
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
    """Input from orchestration agent"""
    plan_step: str              # e.g., "Search for Nike shoes"
    dom_snapshot: dict          # From IG DOM extraction
    url: str
    main_goal: str              # Context only

class ExecutionOutput(BaseModel):
    """Output to Data Processing Tool"""
    action: str
    args: dict
    status: Literal["success", "failure"]
    error_type: Literal["none", "element_not_found", "ambiguous_step", "tool_limit", "navigation_blocked", "unknown"]
    message: str
    execution_time_ms: int
```

**Tests**: Model validation

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

**Tests**: E2E with mock LLM and real Playwright browser

---

## PR #6: Data Processing Tool Reporter

**Core Logic**: Report execution results to IG Data Processing Tool

**Files**:
```
+ backend/execution/reporter.py
+ backend/tests/execution/test_reporter.py
```

**Implementation**:
```python
# backend/execution/reporter.py
from .models import ExecutionOutput

class DataProcessingReporter:
    """Report execution results to Data Processing Tool"""

    async def report_execution(
        self,
        result: ExecutionOutput,
        original_prompt: str,
        action_summary: str
    ) -> dict:
        """
        Send execution result to Data Processing Tool.

        Args:
            result: Execution output
            original_prompt: User's original task request
            action_summary: Summary of actions taken

        Returns:
            Data Processing Tool response with:
            - task_level_confidence_score
            - identified_failure_points
            - proposed_corrective_fix
        """

        # Format for Data Processing Tool
        report = {
            "agent_execution_summary": {
                "action": result.action,
                "args": result.args,
                "status": result.status,
                "error_type": result.error_type,
                "message": result.message,
                "execution_time_ms": result.execution_time_ms
            },
            "original_user_prompt": original_prompt,
            "action_summary": action_summary
        }

        # TODO: Replace with actual IG Data Processing Tool API call
        # For now, return mock response
        response = await self._call_data_processing_tool(report)

        return response

    async def _call_data_processing_tool(self, report: dict) -> dict:
        """Call IG Data Processing Tool API"""
        # Integration with IG team's Data Processing Tool
        # Replace with actual API call
        pass
```

**Tests**: Mock Data Processing Tool API

---

## PR #7: Orchestration Interface

**Core Logic**: Receive plan steps from orchestration agent

**Files**:
```
+ backend/execution/orchestration_interface.py
+ backend/tests/execution/test_orchestration_interface.py
```

**Implementation**:
```python
# backend/execution/orchestration_interface.py
from .models import ExecutionInput

class OrchestrationInterface:
    """Interface to receive plan steps from orchestration agent"""

    def parse_orchestration_output(self, orchestrator_data: dict) -> ExecutionInput:
        """
        Convert orchestration agent output to ExecutionInput.

        Orchestration provides:
        - main_goal: Overall task goal
        - current_step: Single step to execute
        - dom_snapshot: From IG DOM extraction
        - url: Current page URL
        """
        return ExecutionInput(
            main_goal=orchestrator_data["main_goal"],
            plan_step=orchestrator_data["current_step"],
            dom_snapshot=orchestrator_data["dom_snapshot"],
            url=orchestrator_data["url"]
        )
```

**Tests**: Parse various orchestrator output formats

---

## PR #8: DOM Extraction Interface

**Core Logic**: Get DOM snapshots from IG DOM Extraction tool

**Files**:
```
+ backend/execution/dom_interface.py
+ backend/tests/execution/test_dom_interface.py
```

**Implementation**:
```python
# backend/execution/dom_interface.py
from typing import Dict, Any

class DOMInterface:
    """Interface to IG DOM Extraction tool"""

    async def get_dom_snapshot(self, page) -> Dict[str, Any]:
        """
        Request DOM snapshot from IG DOM Extraction tool.

        Returns:
            {
                "function_metadata": {...},
                "filtered_DOM_tree": {...},
                "raw_DOM_tree": {...},
                "page_screenshot": "base64...",
                "errors": [...]
            }
        """
        # TODO: Replace with actual IG DOM Extraction API call
        # For now, use Playwright accessibility tree as fallback
        snapshot = await page.accessibility.snapshot(
            root=None,
            interesting_only=True
        )
        return snapshot
```

**Tests**: Mock IG DOM Extraction API

---

## PR #9: End-to-End Integration

**Core Logic**: Test full pipeline with all components

**Files**:
```
+ backend/tests/integration/test_full_pipeline.py
```

**Test Flow**:
```python
# Test: Google search flow
async def test_google_search_flow():
    # 1. Setup
    browser = await playwright.chromium.launch()
    page = await browser.new_page()
    await page.goto("https://google.com")

    # 2. Mock orchestration input
    orchestrator_data = {
        "main_goal": "Find Python tutorials",
        "current_step": "Search for 'Python programming'",
        "dom_snapshot": await dom_interface.get_dom_snapshot(page),
        "url": page.url
    }

    # 3. Execute
    input_data = orchestration_interface.parse_orchestration_output(orchestrator_data)
    result = await execute_step(input_data, page, translator)

    # 4. Report to Data Processing Tool
    dp_response = await reporter.report_execution(
        result=result,
        original_prompt="Find Python tutorials",
        action_summary="Searched for 'Python programming' on Google"
    )

    # 5. Assert
    assert result.status == "success"
    assert result.action == "search"
    assert dp_response["task_level_confidence_score"] > 0.8
```

**Tests**: Complete user flows, error scenarios, integration validation


---

## Integration Points Summary

| Component | Owner | Interface |
|-----------|-------|-----------|
| **Orchestration Agent** | Browser Interaction | Sends plan steps → Action Execution |
| **DOM Extraction** | Information Gathering | Provides DOM snapshots → Action Execution |
| **Data Processing Tool** | Information Gathering | Receives execution results ← Action Execution |
| **Playwright Browser** | Shared | Managed by Action Execution |

---

## Definition of Done (Each PR)

- [ ] Core logic implemented
- [ ] Unit tests passing (90%+ coverage)
- [ ] Integration tests passing (if applicable)
- [ ] Code reviewed by 1+ team member
- [ ] PR merged to main

---

## Notes

**Scope Reminder**: Action Execution is a pure executor. It does NOT:
- Create plans (orchestration does this)
- Decide next steps (orchestration does this)
- Retry failures (fallback agent does this)
- Validate task completion (verification agent does this)

**LLM Clarification**: LLM is used ONLY to translate high-level plan steps into specific actions with DOM element targeting. It is NOT used for planning or strategy.
