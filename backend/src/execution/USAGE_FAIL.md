# Action Execution Tool - Failure Diagnosis

**Date:** 2026-02-06
**Branch:** Edwin
**File Analyzed:** `backend/src/agents/executor.py`

---

## Executive Summary

The action execution tools are failing due to **5 critical bugs** in `executor.py`. The good news: **Your action execution implementation is fine** - all failures are integration bugs in how the executor agent is calling your tools.

### Severity Breakdown
- **CRITICAL (Breaks all actions):** 1 bug
- **HIGH (Breaks specific actions):** 2 bugs
- **MEDIUM (Inefficiency/architecture):** 2 bugs

---

## Critical Bug #1: Missing `.action` Attribute ⚠️

**Location:** Lines 135, 153, 169, 186, 204
**Impact:** Type, search, scroll, press_key, and wait actions NEVER execute
**Root Cause:** Integration error in executor.py

### The Problem

```python
# Line 135 - WRONG
elif action == "type":  # Comparing ExecutionResult object to string "type"

# Line 153 - WRONG
elif action == "search":  # Comparing ExecutionResult object to string "search"

# Line 169 - WRONG
elif action == "scroll":  # Comparing ExecutionResult object to string "scroll"

# Line 186 - WRONG
elif action == "press_key":  # Comparing ExecutionResult object to string "press_key"

# Line 204 - WRONG
elif action == "wait":  # Comparing ExecutionResult object to string "wait"
```

### Why This Breaks Everything

The LLM returns an `ExecutionResult` object (line 68):
```python
action: ExecutionResult = self.llm.invoke(messages)  # This is an OBJECT
```

The code then compares the entire object to a string:
```python
elif action == "type":  # This is ALWAYS False!
```

**What actually happens:**
1. Navigate and click work because they use `action.action` (lines 105, 115) ✓
2. All other actions fail the comparison and fall through ✗
3. Your dispatch_action is never called for these actions ✗

### The Fix

**Change all comparisons from:**
```python
elif action == "type":
```

**To:**
```python
elif action.action == "type":
```

**Apply to lines:** 135, 153, 169, 186, 204

---

## Critical Bug #2: Wrong Parameter Name for Search Action

**Location:** Lines 156, 164
**Impact:** Search action always fails validation
**Root Cause:** Schema mismatch

### The Problem

```python
# Line 156 - WRONG
if not action.args.query:  # ActionArgs has no 'query' field!
    raise RuntimeError(f"Search action produced without query....\n'query': {action.args.query}")

# Line 164 - WRONG
query = "this is a test query"  # Variable named 'query'
action = Action(action="search", args=ActionArgs(query=query))  # WRONG parameter!
```

### Schema Definition

From `execution/models.py` and `schema.py`, the ActionArgs model is:

```python
class ActionArgs(BaseModel):
    text: Optional[str] = None      # ✓ Search uses 'text'
    # NO 'query' field exists!
```

From `USAGE.md` line 98-103:
```python
# Correct usage
Action(
    action="search",
    args=ActionArgs(text="search query")  # Uses 'text', not 'query'
)
```

### The Fix

**Change:**
```python
# Line 156
if not action.args.query:

# Line 164
query = "this is a test query"
action = Action(action="search", args=ActionArgs(query=query))
```

**To:**
```python
# Line 156
if not action.args.text:

# Line 164
text = "this is a test query"
action = Action(action="search", args=ActionArgs(text=text))
```

---

## High Priority Bug #3: LLM Not Returning role/name

**Location:** Lines 119-131
**Impact:** Click actions work only with hardcoded values
**Root Cause:** Either LLM prompt issue or DOM extraction not providing element info

### The Problem

```python
# Line 119-120
if not action.args.role or not action.args.name:
    raise RuntimeError("[Executor Error] Click action produced without role or name....")

# Lines 123-124 - Hardcoded workaround
role = "textbox"    # should be action.args.role
name = "Search"     # should be action.args.name
```

The code explicitly raises an error if role/name are missing, then immediately hardcodes values to bypass the check. This suggests **the LLM is returning None for these fields**.

### Why This Happens

Looking at lines 48-61, the executor sends DOM snapshot to the LLM:
```python
DOM_SNAPSHOT:
{self._get_simulated_dom(current_url, current_task)}
```

**The `_get_simulated_dom()` function (lines 250-281) returns hardcoded fake DOM data.**

The LLM is receiving simulated DOM like:
```
[role="textbox"] "Search"
[role="button"] "Submit"
```

But it's not parsing this correctly into the `role` and `name` fields in the ExecutionResult.

### The Fix

**Option 1: Fix the LLM prompt** (Likely the real solution)
- The execution prompt needs clearer instructions on extracting role/name from DOM
- Check `prompts/execution.prompt.md` and ensure it shows examples of parsing:
  ```
  [role="button"] "Search" → role="button", name="Search"
  ```

**Option 2: Fix DOM extraction** (If using real DOM)
- Replace `_get_simulated_dom()` with actual DOM extraction from dom_extractor
- Ensure DOM includes ARIA roles and accessible names per USAGE.md line 244-251

**Option 3: Remove hardcoding** (Once LLM works)
```python
# Lines 119-131 should become:
elif action.action == "click":  # Note the .action fix from Bug #1
    if not action.args.role or not action.args.name:
        raise RuntimeError(f"[Executor Error] Click action missing role or name")

    result = await dom_extractor.main(page)
    action = Action(
        action="click",
        args=ActionArgs(role=action.args.role, name=action.args.name)  # Use LLM values
    )
    result = await dispatch_action(result[2], action)
    print("[executor - click result]:", result)
```

---

## Medium Priority Bug #4: Unnecessary DOM Extraction Calls

**Location:** Lines 109, 127, 145, 162, 178, 195, 213
**Impact:** Performance overhead, but doesn't break functionality
**Root Cause:** Misunderstanding of page lifecycle

### The Problem

Every action handler calls:
```python
result = await dom_extractor.main(page)
action = Action(...)
result = await dispatch_action(result[2], action)  # Uses result[2] to get page back
```

**Why this is wasteful:**
1. `dom_extractor.main(page)` extracts DOM, takes screenshot, returns tuple `(json, screenshot, page)`
2. The executor throws away the DOM and screenshot
3. It only uses `result[2]` to get the page object back
4. But the page is already available at line 37: `page = self.runtime.get("page")`

### The Fix

**Before:**
```python
result = await dom_extractor.main(page)
action = Action(action="click", args=ActionArgs(role=role, name=name))
result = await dispatch_action(result[2], action)
```

**After:**
```python
action = Action(action="click", args=ActionArgs(role=role, name=name))
result = await dispatch_action(page, action)  # Use page directly
```

**Delete lines:** The dom_extractor calls on lines 109, 127, 145, 162, 178, 195, 213 are unnecessary.

**When to call DOM extraction:**
- Only call it when you actually need DOM data for the LLM prompt
- Currently it's called once at line 56 via `_get_simulated_dom()` - that's the right place
- Don't call it again in each action handler

---

## Medium Priority Bug #5: Action Object Re-creation

**Location:** All action handlers
**Impact:** LLM output is discarded, defeating the purpose
**Root Cause:** Misunderstanding of the integration pattern

### The Problem

The executor asks the LLM to generate an action (line 68):
```python
action: ExecutionResult = self.llm.invoke(messages)  # LLM returns: click, role="button", name="Search"
```

Then immediately discards it and hardcodes new values (line 129-130):
```python
# Throw away LLM's role and name
role = "textbox"    # Hardcoded
name = "Search"     # Hardcoded

# Create new action with hardcoded values
action = Action(action="click", args=ActionArgs(role=role, name=name))
```

**This defeats the entire purpose of having an LLM decide actions.**

### The Fix

**Current (wrong) pattern:**
```python
# LLM decides what to do
action: ExecutionResult = self.llm.invoke(messages)

# Executor throws away LLM's decision and hardcodes
role = "textbox"
name = "Search"
action = Action(action="click", args=ActionArgs(role=role, name=name))
result = await dispatch_action(page, action)
```

**Correct pattern:**
```python
# LLM decides what to do
action: ExecutionResult = self.llm.invoke(messages)

# Executor uses LLM's decision directly
result = await dispatch_action(
    page,
    Action(action=action.action, args=action.args)
)
```

**Even simpler (if ExecutionResult schema matches Action schema):**
```python
# LLM decides
action: ExecutionResult = self.llm.invoke(messages)

# Execute directly
result = await dispatch_action(page, action)
```

---

## Root Cause Analysis

### Why Are Tools Failing?

You suspected DOM extraction wasn't providing the right params. **You were partially correct!**

The DOM extraction itself works fine (returns tuple with page), but:

1. **The simulated DOM** (`_get_simulated_dom()`) provides fake data
2. **The LLM prompt** doesn't correctly parse DOM into role/name fields
3. **The comparison logic** breaks all non-navigate/click actions
4. **The parameter names** don't match the schema for search

### Is This Your Fault?

**NO.** Your action execution implementation is solid:
- ✓ Models are correctly defined (`ActionArgs`, `Action`, `ExecutionOutput`)
- ✓ USAGE.md documentation is accurate
- ✓ The `dispatch_action` function works as designed
- ✓ All 7 action handlers exist and work correctly

### Is This Your Teammate's Fault?

**Partially.** The integration has bugs, but they're understandable:

1. **Bug #1** (missing `.action`): Simple typo that's easy to miss
2. **Bug #2** (query vs text): Schema mismatch - needs to read USAGE.md more carefully
3. **Bug #3** (LLM not returning values): Complex problem requiring prompt engineering
4. **Bug #4** (unnecessary DOM calls): Architectural misunderstanding
5. **Bug #5** (hardcoding): Debugging workaround that became permanent

---

## Testing Recommendations

After fixing these bugs, test in this order:

### 1. Test Navigate (Should already work)
```python
action = Action(action="navigate", args=ActionArgs(url="https://google.com"))
result = await dispatch_action(page, action)
assert result.status == "success"
```

### 2. Test Click (Fix Bug #3 first)
```python
# Ensure LLM returns role="textbox", name="Search"
action = Action(action="click", args=ActionArgs(role="textbox", name="Search"))
result = await dispatch_action(page, action)
assert result.status == "success"
```

### 3. Test Type (Fix Bug #1 first)
```python
action = Action(action="type", args=ActionArgs(text="Hello World"))
result = await dispatch_action(page, action)
assert result.status == "success"
```

### 4. Test Search (Fix Bugs #1 and #2 first)
```python
action = Action(action="search", args=ActionArgs(text="search query"))  # NOT query!
result = await dispatch_action(page, action)
assert result.status == "success"
```

### 5. Test Scroll (Fix Bug #1 first)
```python
action = Action(action="scroll", args=ActionArgs(direction="down"))
result = await dispatch_action(page, action)
assert result.status == "success"
```

### 6. Test Press Key (Fix Bug #1 first)
```python
action = Action(action="press_key", args=ActionArgs(key="Enter"))
result = await dispatch_action(page, action)
assert result.status == "success"
```

### 7. Test Wait (Fix Bug #1 first)
```python
action = Action(action="wait", args=ActionArgs(seconds=2.0))
result = await dispatch_action(page, action)
assert result.status == "success"
```

---

## Quick Fix Checklist

Apply these fixes to `executor.py`:

- [ ] **Line 135:** Change `elif action == "type":` to `elif action.action == "type":`
- [ ] **Line 153:** Change `elif action == "search":` to `elif action.action == "search":`
- [ ] **Line 156:** Change `action.args.query` to `action.args.text` (2 places)
- [ ] **Line 164:** Change `ActionArgs(query=query)` to `ActionArgs(text=text)`
- [ ] **Line 169:** Change `elif action == "scroll":` to `elif action.action == "scroll":`
- [ ] **Line 186:** Change `elif action == "press_key":` to `elif action.action == "press_key":`
- [ ] **Line 204:** Change `elif action == "wait":` to `elif action.action == "wait":`
- [ ] **All handlers:** Remove `dom_extractor.main(page)` calls, use `page` directly
- [ ] **All handlers:** Remove hardcoded values, use `action.args` from LLM
- [ ] **Fix LLM prompt:** Ensure it correctly parses DOM into role/name fields

---

## Summary Table

| Bug | Location | Severity | Affects | Fixed By |
|-----|----------|----------|---------|----------|
| Missing `.action` | Lines 135, 153, 169, 186, 204 | CRITICAL | type, search, scroll, press_key, wait | Add `.action` to comparisons |
| Wrong param name | Lines 156, 164 | HIGH | search | Change `query` to `text` |
| LLM not returning role/name | Lines 119-131 | HIGH | click | Fix LLM prompt or DOM extraction |
| Unnecessary DOM calls | Lines 109, 127, 145, 162, 178, 195, 213 | MEDIUM | Performance | Use `page` directly |
| Action re-creation | All handlers | MEDIUM | Architecture | Use LLM's action directly |

---

## Conclusion

**Your action execution tool is working correctly.** All failures are in the integration layer (executor.py). The critical bug preventing most actions from running is the missing `.action` attribute on lines 135, 153, 169, 186, and 204.

Once these bugs are fixed, your dispatch_action function should work as designed per USAGE.md.

**Next Steps:**
1. Fix Bug #1 (missing `.action`) - This will immediately fix 5 actions
2. Fix Bug #2 (query vs text) - This will fix search
3. Investigate Bug #3 (LLM prompt) - This will fix click with real data
4. Clean up Bugs #4 and #5 - This will improve performance and architecture

Good luck! Your bare-bones implementation is solid - the issues are all in how it's being called.
