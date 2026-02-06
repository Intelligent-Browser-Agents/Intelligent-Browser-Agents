# DOM Extraction - ARIA Format Update

**Date:** 2026-02-06
**Purpose:** Enable seamless integration with Action Execution Tool

---

## What Changed

DOM extraction now returns **ARIA-formatted** interactive elements instead of raw HTML data.

### Before (Old Format)
```json
{
  "tag": "input",
  "text": "",
  "attributes": {
    "type": "text",
    "aria-label": "Search",
    "class": "search-box"
  }
}
```

### After (New Format)
```json
{
  "role": "textbox",
  "name": "Search",
  "tag": "input",
  "attributes": {
    "type": "text",
    "aria-label": "Search",
    "class": "search-box"
  }
}
```

**Key Changes:**
- Added `role` field (ARIA role)
- Added `name` field (ARIA accessible name)
- Kept `tag` and `attributes` for debugging/reference

---

## How ARIA Extraction Works

### ARIA Role Inference

The role is determined by this priority:

1. **Explicit ARIA role** (`role="button"`)
2. **Inferred from HTML tag + type**

| HTML | Role |
|------|------|
| `<button>` | `button` |
| `<a>` | `link` |
| `<input type="text">` | `textbox` |
| `<input type="search">` | `searchbox` |
| `<input type="checkbox">` | `checkbox` |
| `<input type="submit">` | `button` |
| `<textarea>` | `textbox` |
| `<select>` | `combobox` |

### ARIA Name Extraction

The accessible name is extracted by this priority:

1. `aria-label` attribute
2. Element text content
3. `placeholder` attribute
4. `title` attribute
5. `value` attribute
6. `alt` attribute (for images)
7. `name` attribute (last resort)

### Examples

#### Example 1: Google Search Box
```html
<input type="text" aria-label="Search" name="q" placeholder="Search Google">
```

**Extracted ARIA:**
```json
{
  "role": "textbox",
  "name": "Search"
}
```

#### Example 2: Submit Button
```html
<button type="submit" class="btn-primary">Sign In</button>
```

**Extracted ARIA:**
```json
{
  "role": "button",
  "name": "Sign In"
}
```

#### Example 3: Navigation Link
```html
<a href="/home">Home</a>
```

**Extracted ARIA:**
```json
{
  "role": "link",
  "name": "Home"
}
```

#### Example 4: Input with Placeholder
```html
<input type="email" placeholder="Enter your email">
```

**Extracted ARIA:**
```json
{
  "role": "textbox",
  "name": "Enter your email"
}
```

---

## How to Use in Executor

### Step 1: Get DOM with ARIA Data

```python
from informationGathering.dom_extractor import dom_extractor

# Get DOM data
result = await dom_extractor.main(page)
dom_json = json.loads(result[0])

# Or if using retrieve_interactive_elements:
elements_json = retrieve_interactive_elements(result[0])
elements_data = json.loads(elements_json)

interactive_elements = elements_data['interactive_elements']
```

### Step 2: Format DOM for LLM

```python
# Build clean ARIA-formatted DOM snapshot for LLM prompt
dom_snapshot = []
for elem in interactive_elements:
    dom_snapshot.append(f"[role=\"{elem['role']}\"] \"{elem['name']}\"")

dom_text = "\n".join(dom_snapshot)
```

**Example output:**
```
[role="textbox"] "Search"
[role="button"] "Submit"
[role="link"] "Home"
[role="link"] "Sign In"
```

### Step 3: Send to LLM with Clear Instructions

```python
context = f"""
PLAN_STEP: {current_task}

DOM_SNAPSHOT:
{dom_text}

Instructions:
- Match the plan step to an element in the DOM
- Return the EXACT role and name from the DOM
- Do not modify or guess - use exact values shown above

Example:
Plan: "Click the search box"
DOM: [role="textbox"] "Search"
Output: role="textbox", name="Search"
"""
```

### Step 4: LLM Returns Role/Name

The LLM should return:
```python
ExecutionResult(
    action="click",
    args=ExecutionArgs(
        role="textbox",
        name="Search"
    ),
    status="success",
    message="Clicking textbox 'Search'"
)
```

### Step 5: Call Action Execution Tool

```python
from execution import Action, ActionArgs, dispatch_action

# Use LLM's output directly
action = Action(
    action=llm_result.action,
    args=ActionArgs(
        role=llm_result.args.role,
        name=llm_result.args.name
    )
)

# Execute the action
result = await dispatch_action(page, action)
```

---

## Complete Integration Example

```python
import json
from informationGathering.dom_extractor import dom_extractor
from execution import Action, ActionArgs, dispatch_action

async def execute_plan_step(page, plan_step: str):
    """Execute a high-level plan step using ARIA-formatted DOM."""

    # Step 1: Get ARIA-formatted DOM
    dom_result = await dom_extractor.main(page)
    dom_data = json.loads(dom_result[0])

    # Step 2: Format DOM for LLM
    dom_snapshot = []
    for elem in dom_data.get('interactive_elements', []):
        dom_snapshot.append(f"[role=\"{elem['role']}\"] \"{elem['name']}\"")

    dom_text = "\n".join(dom_snapshot)

    # Step 3: Build LLM prompt
    prompt = f"""
    PLAN_STEP: {plan_step}

    DOM_SNAPSHOT:
    {dom_text}

    Match the plan step to an element and return its exact role and name.
    """

    # Step 4: Get LLM decision
    llm_result = llm.invoke(prompt)  # Returns ExecutionResult

    # Step 5: Execute action
    action = Action(
        action=llm_result.action,
        args=ActionArgs(
            role=llm_result.args.role,
            name=llm_result.args.name
        )
    )

    result = await dispatch_action(page, action)
    return result
```

---

## Benefits of ARIA Format

### 1. Clean Separation of Concerns
- **DOM Extraction:** Deterministic HTML → ARIA parsing (fast, reliable)
- **Executor LLM:** Reasoning about which element matches the plan (smart)
- **Action Execution:** Pure execution on specific elements (simple)

### 2. Performance
- ARIA parsing is deterministic code (milliseconds)
- LLM only used for decision-making, not parsing
- No wasted LLM calls on data transformation

### 3. Reliability
- Code-based parsing: 100% accurate
- LLM gets clean, structured data
- Reduces LLM hallucination on element names

### 4. Debugging
- Clear element identification
- ARIA roles/names match accessibility standards
- Easy to validate in browser DevTools

### 5. Reusability
- ARIA format useful beyond just action execution
- Can be used for accessibility testing
- Standard format across the industry

---

## Troubleshooting

### Element Has No Name
**Cause:** Element has no aria-label, text, placeholder, etc.
**Solution:** The `name` field will be empty string. LLM should be instructed to use partial matching or match by role only.

### Role is Generic (e.g., "div")
**Cause:** Non-semantic HTML without explicit ARIA
**Solution:** `infer_role_from_tag()` falls back to tag name. Consider adding more role inference rules for common patterns.

### Multiple Elements with Same Role/Name
**Cause:** Duplicate buttons, links, etc.
**Solution:** This is expected. LLM should select based on context. Future enhancement: add position/index to disambiguate.

### Missing onclick Elements
**Cause:** Element has onclick but not in common_interactive_tags
**Solution:** Already handled - onclick_elements loop catches these.

---

## Migration Checklist

For existing code using DOM extraction:

- [ ] Update executor to read `role` and `name` fields instead of parsing `tag` and `attributes`
- [ ] Update LLM prompts to show ARIA format examples
- [ ] Update LLM instructions to return exact role/name from DOM
- [ ] Remove any custom HTML→ARIA parsing code (now handled by DOM extraction)
- [ ] Test with various web pages to ensure ARIA extraction works correctly
- [ ] Update error handling to account for empty `name` fields

---

## API Reference

### New Functions

#### `infer_role_from_tag(tag: str, attrs: dict) -> str`
Infers ARIA role from HTML tag and attributes.

**Parameters:**
- `tag`: HTML tag name (e.g., 'button', 'input')
- `attrs`: Dictionary of HTML attributes

**Returns:** ARIA role string

#### `extract_aria_name(element, attrs: dict) -> str`
Extracts accessible name following ARIA naming priority.

**Parameters:**
- `element`: BeautifulSoup element
- `attrs`: Dictionary of HTML attributes

**Returns:** Accessible name string (empty if none found)

### Updated Return Format

#### `retrieve_interactive_elements(page_data: str) -> str`

**Returns JSON with structure:**
```json
{
  "tool_name": "retrieve_interactive_elements",
  "status": "success",
  "execution_time": 0.123,
  "memory_usage": 4096,
  "num_of_elements": 15,
  "interactive_elements": [
    {
      "url": "https://example.com",
      "title": "Example Page",
      "role": "button",
      "name": "Submit",
      "tag": "button",
      "attributes": {...}
    },
    ...
  ]
}
```

**Key changes:**
- Added `role` field to each element
- Added `name` field to each element
- Kept `tag` and `attributes` for backward compatibility

---

## Questions?

**Why keep tag and attributes if we have role and name?**
For debugging and future enhancements. You can remove them if you want a leaner format.

**What if ARIA name is ambiguous?**
Multiple elements can have the same role/name. LLM should use context from the plan step to select the right one.

**Can I customize the role inference?**
Yes! Modify `infer_role_from_tag()` to add custom rules for your specific web apps.

**Does this work with dynamic/JavaScript apps?**
Yes! Playwright renders JavaScript before extracting DOM, so ARIA extraction sees the fully rendered page.
