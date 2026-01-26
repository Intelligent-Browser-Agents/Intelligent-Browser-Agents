# Action Execution Step

## Project Overview

**Intelligent Browser Agents** is an autonomous web automation system that transforms natural language instructions into executable browser actions. The system enables users to delegate repetitive web tasks through an AI-powered agent that understands intent, plans execution strategies, and performs interactions within a live browser session.

The system operates through a multi-agent pipeline:
1. User provides natural language task description
2. Orchestration agent generates high-level execution plan
3. Information gathering tools extract page state (DOM, metadata)
4. Action execution translates plan steps into browser interactions
5. Verification confirms task completion
6. Fallback handles failures and recovery

## Action Execution: Scope and Responsibility

### Core Responsibility

The **Action Execution** component serves as the **executor layer** between high-level planning and low-level browser automation. Its singular focus is to translate a single plan step into a concrete browser action.

### What Action Execution Does

**Input Processing**
- Receives one plan step from the orchestration agent
- Receives current DOM snapshot from DOM extraction tools
- Receives current browser context (URL, page state)

**Tool Selection**
- Analyzes plan step against available browser tools
- Selects the most appropriate action: `navigate`, `click`, `type`, `search`, `scroll`, `press_key`, `wait`
- Determines precise target elements using ARIA roles and accessible names from DOM

**Execution**
- Executes exactly one browser action per invocation
- Interfaces with Playwright automation framework
- Returns structured execution result (success/failure with context)

**Error Signaling**
- Reports element-not-found errors
- Reports ambiguous target errors
- Reports tool limitation errors
- Delegates retry logic to upstream components

### What Action Execution Does NOT Do

**Scope Boundaries**
- Does not create, modify, or reorder plans
- Does not evaluate overall task completion
- Does not implement retry or fallback strategies
- Does not interact with users directly
- Does not perform multi-step reasoning
- Does not validate high-level goal correctness
- Does not make decisions about alternative approaches

The action execution layer is intentionally stateless and atomic. It executes commands, reports results, and defers all strategic decision-making to the orchestration layer.

## Architectural Position

```
┌─────────────────────────────────────────────────────┐
│                   User Input                        │
│            "Find Nike shoes on sale"                │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│              Orchestration Agent                    │
│  • Generates execution plan                         │
│  • Breaks goal into steps                           │
│  • Coordinates agent workflow                       │
└────────────────────┬────────────────────────────────┘
                     │
          ┌──────────┴──────────┐
          │                     │
          ▼                     ▼
┌──────────────────┐   ┌──────────────────┐
│  DOM Extraction  │   │ Links Searcher   │
│  • Page snapshot │   │ • URL discovery  │
│  • Element tree  │   │ • Ranking        │
└────────┬─────────┘   └────────┬─────────┘
         │                      │
         └──────────┬───────────┘
                    │
                    ▼
         ┌─────────────────────┐
         │ ACTION EXECUTION    │  ◄── Focus Component
         │ • Tool selection    │
         │ • Browser actions   │
         │ • Result reporting  │
         └──────────┬──────────┘
                    │
                    ▼
         ┌─────────────────────┐
         │  Verification Agent │
         │  • Success check    │
         │  • State validation │
         └──────────┬──────────┘
                    │
         ┌──────────┴──────────┐
         │                     │
         ▼                     ▼
    ┌─────────┐         ┌──────────┐
    │ Success │         │ Fallback │
    └─────────┘         │  Agent   │
                        └──────────┘
```

## Interface Contracts

### Input Schema
```python
{
  "main_goal": str,           # Overall task objective (context only)
  "plan_step": str,           # Single high-level step to execute
  "dom_snapshot": dict,       # Accessibility tree of current page
  "url": str,                 # Current page URL
  "allowed_tools": list       # Available browser actions
}
```

### Output Schema
```python
{
  "action": str,              # Tool name: navigate|click|type|search|scroll|press_key|wait
  "args": {
    "url": str | None,        # For navigate
    "role": str | None,       # ARIA role for click
    "name": str | None,       # Accessible name for click
    "text": str | None,       # Input text for type
    "direction": str | None,  # up|down for scroll
    "key": str | None,        # Key name for press_key
    "seconds": int | None     # Duration for wait
  },
  "status": str,              # success|failure
  "error_type": str,          # none|element_not_found|ambiguous_step|tool_limit|navigation_blocked|unknown
  "message": str              # Human-readable result description
}
```

## Tool Inventory

| Tool | Purpose | Triggers | Arguments |
|------|---------|----------|-----------|
| `navigate(url)` | Load a specific URL | Plan mentions "go to", "open", "visit" + known URL | `url: str` |
| `click(role, name)` | Interact with DOM element | Plan mentions "click", "select", "press button" | `role: str, name: str` |
| `type(text)` | Input text into focused field | Plan mentions "type", "enter", "fill" | `text: str` |
| `search(query)` | Execute search on Google or search UI | Plan mentions "search for", "look up" | `query: str` |
| `scroll(direction)` | Scroll page up or down | Target element likely off-screen | `direction: "up" \| "down"` |
| `press_key(key)` | Press keyboard key | Submission, escape, navigation | `key: str` (e.g., "Enter", "Escape") |
| `wait(seconds)` | Pause execution | Page loading, transitions | `seconds: int` |

## Design Principles

1. **Single Responsibility**: Execute one action per invocation
2. **Fail Fast**: Report errors immediately without retry logic
3. **DOM Grounding**: Only target elements present in current DOM snapshot
4. **Stateless Execution**: No memory of previous actions or future plans
5. **Structured Results**: Always return machine-readable JSON output
6. **Separation of Concerns**: Planning, execution, and verification are independent layers

## Success Criteria

The action execution component is successful when:
- It correctly interprets 95%+ of plan steps into appropriate tools
- It grounds all element interactions in actual DOM elements
- It executes actions within 2 seconds on average
- It returns structured results parseable by verification layer
- It does not hallucinate selectors or elements
- It delegates strategic decisions to orchestration layer

## Integration Points

**Upstream Dependencies**
- Orchestration agent provides plan steps
- DOM extraction provides page snapshots
- Links searcher provides target URLs

**Downstream Consumers**
- Verification agent validates execution results
- Fallback agent handles reported failures
- Orchestration agent adjusts plan based on results

**External Systems**
- Playwright browser automation framework
- Browser instances (Chromium/Firefox/WebKit)
- Page DOM and accessibility tree

## Risks and Limitations

**Risks**
- DOM snapshots may become stale between extraction and execution
- Elements may not be interactable even if present in DOM
- Ambiguous plan steps may result in incorrect tool selection
- Dynamic content may require waits not specified in plan

**Limitations**
- Cannot handle multi-step compound actions
- Cannot perform visual reasoning (relies on DOM/accessibility tree)
- Cannot adapt strategy if initial action fails
- Cannot validate high-level goal achievement
- No built-in retry or error recovery

**Mitigation Strategies**
- Upstream agents ensure DOM freshness
- Verification layer detects execution failures
- Fallback layer implements recovery strategies
- Orchestration layer adjusts plans based on feedback
