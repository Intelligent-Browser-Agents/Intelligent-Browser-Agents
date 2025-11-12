# IG Action Execution Module

A minimal browser action execution library using Playwright for Python. This module takes structured action commands, executes them in a real browser, and returns structured results with evidence.

## Features

- **No planning or reasoning** - Just executes actions and reports outcomes
- **Evidence capture** - Screenshots and DOM snippets for every action
- **Strict scope** - Single attempt per action, no retries beyond readiness checks
- **Typed interfaces** - Pydantic models for inputs and outputs
- **Session management** - One browser profile per session ID

## Installation

```bash
# Install the package
pip install -e .

# Install Playwright browsers
playwright install chromium
```

## Quick Start

```python
from ig_action_exec import ActionCommand, Target, run_action

# Navigate to a URL
nav_command = ActionCommand(
    trace_id="trace_001",
    session_id="session_001",
    action_type="navigate_to_url",
    input_value="https://example.com"
)
result = await run_action(nav_command)

# Click an element
click_command = ActionCommand(
    trace_id="trace_002",
    session_id="session_001",
    action_type="click_element",
    target=Target(
        selector="#submit-button",
        selector_type="css"
    )
)
result = await run_action(click_command)

# Check result
if result.status == "success":
    print(f"Action completed: {result.evidence.screenshot_path}")
else:
    print(f"Action failed: {result.error.message}")
```

## Supported Actions

### Navigation
- `navigate_to_url` - Open a URL
- `go_back` - Navigate back in history
- `go_forward` - Navigate forward  
- `reload_page` - Reload current page
- `close_tab` - Close current tab
- `switch_tab` - Switch to tab by index

### Interaction
- `click_element` - Click on element
- `double_click_element` - Double click
- `type_input` - Type text into input
- `press_key` - Press keyboard key
- `hover_over` - Hover over element
- `scroll` - Scroll page
- `scroll_to` - Scroll to element
- `upload_file` - Upload file to input
- `drag_and_drop` - Drag and drop

### Sensing (Read-only)
- `extract_dom` - Get page HTML
- `get_element_text` - Get element text
- `get_element_attribute` - Get attribute value
- `take_screenshot` - Capture screenshot

### Composite Helpers
- `search_and_click` - Find and click element
- `fill_out_form` - Fill multiple form fields

## Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test
pytest tests/test_primitives.py::test_click_button -v
```

## Running the Demo

```bash
python demo.py
```

This will execute three sequential actions on a local test page and display the results.

## Action Command Schema

```python
{
  "trace_id": "unique_id",
  "session_id": "session_id",
  "action_type": "click_element",
  "target": {
    "selector": "#button",
    "selector_type": "css",
    "selector_strategy": "strict"
  },
  "timeout_ms": 8000,
  "screenshot": {
    "enabled": true,
    "clip_to_element": true
  },
  "dom_snippet_chars": 4000
}
```

## Action Result Schema

```python
{
  "trace_id": "unique_id",
  "status": "success",
  "action_type": "click_element",
  "session_id": "session_id",
  "timings_ms": {
    "resolve": 45,
    "interact": 120,
    "post_capture": 200
  },
  "evidence": {
    "screenshot_path": "/tmp/ig_evidence/trace_001.png",
    "dom_snippet_path": "/tmp/ig_evidence/trace_001_dom.html",
    "visible_text": "Button clicked"
  },
  "error": null
}
```

## Error Codes

- `timeout` - Action timed out
- `element_not_found` - Element not found
- `not_interactable` - Element not interactable
- `detached` - Element detached from DOM
- `navigation_failed` - Page navigation failed
- `upload_failed` - File upload failed
- `unsupported_action` - Action type not supported
- `bad_command` - Invalid command format
- `internal` - Internal error

## License

MIT