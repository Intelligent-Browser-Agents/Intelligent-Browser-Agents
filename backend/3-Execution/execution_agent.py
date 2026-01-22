# === Execution agent - Edwin Villanueva ===

# --- input ---
# - orchestration agent plan #? + IG (DOM extractiion) output)
# -------------

# --- output ---
# - 
# --------------

# === imports ===
import mock_orchestration # replace this with the real orchestration agent
import IG_DOM_Extraction  # replace with real dom extraction agent 
from openai import OpenAI
from dotenv import load_dotenv
# ===============

load_dotenv()
client = OpenAI()



# step 1: Recieve Input from Orchestration Agent - 
# take input from the orchestration agent
# -----------------------------------------------
orchestration_output = mock_orchestration.main() # rewrite so that output is useful

# step 2: Tool Selection - 
# based on input from orchestration agent, 
# first, request DOM elements from IG team. Then, select tools to use
# -----------------------------------------------

# extract DOM elements
DOM_elements = IG_DOM_Extraction.main() # rewirte for valid test output

# select tools to call
# TODO: [ ] Make tool list for API to refer to
IG_TOOLS = [
    {
        "name": "SearchOrchestrator",
        "category": "discovery",
        "description": "Searches the web to identify the most relevant target URL",
        "used_when": "Target URL is unknown or ambiguous",
        "outputs": ["ranked_urls"]
    },
    {
        "name": "DOMExtraction",
        "category": "extraction",
        "description": "Loads a webpage and retrieves raw DOM and page metadata",
        "used_when": "Page needs to be analyzed or refreshed",
        "outputs": ["dom_snapshot", "page_metadata"]
    },
    {
        "name": "DOMUnderstandingAgent",
        "category": "understanding",
        "description": "Analyzes DOM to identify semantic elements (buttons, forms, inputs)",
        "used_when": "Need to locate interactive or meaningful elements",
        "outputs": ["interactive_elements", "form_fields"]
    },
    {
        "name": "IdentifyClickButton",
        "category": "action",
        "description": "Clicks a specific interactive DOM element",
        "used_when": "Navigation or submission is required",
        "outputs": ["post_action_url"]
    },
    {
        "name": "InputText",
        "category": "action",
        "description": "Types text into a form field",
        "used_when": "Form fields require user input",
        "outputs": ["field_confirmation"]
    },
    {
        "name": "DataProcessingModule",
        "category": "verification",
        "description": "Extracts and validates answers from the page",
        "used_when": "Need to confirm task completion",
        "outputs": ["answer", "confidence"]
    }
]

# register the tools
tool_registry_text = "\n".join(
    f"- {tool['name']} ({tool['category']}: {tool['description']})"
    for tool in IG_TOOLS
)

#!==========================================ATTENTION===============================================!#
#!                                                                                                  !#
#! UPDATE THE "AVAILABLE TOOLS" SECTION WHEN WE FIGURE OUT EXACTLY WHAT TOOLS THIS PROGRAM WILL USE !#
#!                                                                                                  !#
#!==================================================================================================!#
# # system prompt template
system_prompt_template = """
    You are the Execution Agent in an intelligent browser automation system.

    You MUST return only valid JSON. Do not include explanations outside JSON.


    Your responsibility:
    - Analyze the orchestration agent's plan for the current step
    - Analyze the Information Gathering (IG) logs collected so far
    - Decide which IG tool(s) should be called next to progress the task

    You do NOT execute tools.
    You ONLY select which tool(s) should be called.

    Available IG tools:
    {TOOL_REGISTRY}

    Decision rules:
    - Only select tools that help satisfy the current step's success criteria
    - Prefer understanding tools before action tools
    - Do not repeat tools unnecessarily
    - If no tool is needed, return an empty list

    Return your decision in valid JSON with the following format:

    {{
    "selected_tools": ["<tool_name>", "..."],
    "reasoning": "<short explanation>",
    "confidence": <float between 0 and 1>
    }}

    Orchestration Agent Input:
    {ORCHESTRATION_OUTPUT}

    IG Logs:
    {IG_LOGS}
"""

# system prompt (filling in blanks we left in prompt)
system_prompt = system_prompt_template.format(
    ORCHESTRATION_OUTPUT=orchestration_output,
    IG_LOGS = DOM_elements,
    TOOL_REGISTRY = tool_registry_text
)

# OpenAI API call to decide tools to call
response = client.responses.create(
    model="gpt-5.2",
    input = system_prompt
)


# TEST PRINT 
print(response.output_text)

