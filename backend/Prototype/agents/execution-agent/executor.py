# Where Edwin would put the code for the execution agent. Can either rely on tools in utilities, or define a separate folder for tools.# === Execution agent - Edwin Villanueva ===

# === imports ===
import mock_orchestration # replace this with the real orchestration agent
import IG_DOM_Extraction  # replace with real dom extraction agent 
from ollama import chat, ChatResponse
from dotenv import load_dotenv
# ===============

load_dotenv()
# client = genai.Client()



#! step 1: Recieve Input from Orchestration Agent - 
# take input from the orchestration agent
# -----------------------------------------------
orchestration_output = mock_orchestration.main() # rewrite so that output is useful

#! step 2: Tool Selection - 
# based on input from orchestration agent, 
# first, request DOM elements from IG team. Then, select tools to use
# -----------------------------------------------


# select tools to call
# TODO: [ ] Make tool list for API to refer to
IG_TOOLS = [

    # DOM EXTRACTION
    {
        "name": "dom_extraction",
        "category": "extraction",
        "description": "Extract all data from a webpage to develop a plan for executing the user's prompt.",
        "used_when": "Page needs to be analyzed or refreshed",
        "outputs": ["function_metadata", "filtered_DOM_tree", "raw_DOM_tree", "page_screenshot", "errors"]
    },
    
    # LINKS SEARCHER
    {
        "name": "links_searcher",
        "category": "discovery",
        "description": "Take the user query, use serper.dev to get relevant links for the other tools to search the web, rank urls, and normalize output.",
        "used_when": "Searching for relevant pages to move into.",
        "outputs": ["results"] # 5+ relevant websites (ranked)
    },

    # DATA PROCESSING TOOL
        {
        "name": "data_processing_tool",
        "category": "processing",
        "description": "Evaluate browser agent task execution by comparing agent action summaries against the original prompt to determine task success and quality.",
        "used_when": "",
        "outputs": ["Task level confidence score"]
    },
]

# register the tools
tool_registry_text = "\n".join(
    f"- {tool['name']} ({tool['category']}: {tool['description']})"
    for tool in IG_TOOLS
)


#! step 3: extract DOM elements
DOM_elements = IG_DOM_Extraction.main() # rewirte for valid test output

#!==========================================ATTENTION===============================================!#
#!                                                                                                  !#
#! UPDATE THE "AVAILABLE TOOLS" SECTION WHEN WE FIGURE OUT EXACTLY WHAT TOOLS THIS PROGRAM WILL USE !#
#!                                                                                                  !#
#!==================================================================================================!#
# # system prompt template
execution_prompt = """
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

"""

###! GEMINI TEST
# # OpenAI API call to decide tools to call
# response = client.models.generate_content(
#     model="gemini-3-flash-preview",
#     contents = execution_prompt
# )

###! OLLAMA TEST
response: ChatResponse = chat(model="gpt-oss:120b-cloud", messages=[
  {
    'role': 'system',
    'content': execution_prompt,
  },
])

# TEST PRINT 
print(response.message.content)