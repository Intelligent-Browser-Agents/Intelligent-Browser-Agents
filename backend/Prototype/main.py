from langgraph.graph import StateGraph, END
from agents.orchestrator import Orchestrator
from agents.verifier import Verifier
from agents.fallback import Fallback
from agents.interaction import InteractionAgent
from state import ProjectState
from google import genai
import asyncio
from playwright.async_api import async_playwright, Browser, Error as PlaywrightError
import json
from agents.executor import Executor
from informationGathering.DOMExtractionUnderstanding import DOMExtractionUnderstanding
from execution import Action, dispatch_action, ActionArgs

async def main():
    print("before ")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)


        # todo: make this work in execution agent file.
        result = await DOMExtractionUnderstanding.main(browser)
        action = Action(action="navigate", args=ActionArgs(url="https://nike.com"))
        result = await dispatch_action(result[2], action)
        print(result)
        


# client = genai.Client()

asyncio.run(main())


# # helper to grab text from the md files in the prompts folder
# def read_markdown_file(file_path): 
#     try: 
#         with open(file_path, 'r', encoding='utf-8') as f: 
#             markdown_text = f.read()
#         return markdown_text
#     except FileNotFoundError:
#         return f"Error: {file_path} was not found."

# # prompts
# orchestration_prompt = read_markdown_file('backend\\prototype\\prompts\\orchestration.prompt.md')
# execution_prompt = read_markdown_file('backend\\prototype\\prompts\\execution.prompt.md')
# verification_prompt = read_markdown_file('backend\\prototype\prompts\\verification.prompt.md')
# fallback_prompt = read_markdown_file('backend\\prototype\\prompts\\fallback.prompt.md')
# interaction_prompt = read_markdown_file('backend\\prototype\\prompts\\interaction.prompt.md')
# # === prompts end ===

# # TODO: Add human-in-the-loop. Make sure to finish current first.
# # todo: grab user input from frontend
# user_input = "example text"

# # Initialize the graph
# workflow = StateGraph(ProjectState)

# # Add nodes
# workflow.add_node("orchestrator", Orchestrator())
# workflow.add_node("execution", Executor())
# workflow.add_node("verification", Verifier())
# workflow.add_node("fallback", Fallback())
# workflow.add_node("interaction", InteractionAgent())

# # Define the edges
# workflow.set_entry_point("orchestrator")

# # Orchestration -> Execution or Interaction (conditional)
# workflow.add_conditional_edges(
#     "orchestrator",
#     lambda state: "interaction" if state.get("is_complete", False) else "execution",
#     {
#         "interaction": "interaction",
#         "execution": "execution"
#     }
# )
# # todo: send logs to server

# # Execution -> Verification
# workflow.add_edge("execution", "verification")
# # todo: send logs to server


# # Verification Logic: Path based on success/failure
# workflow.add_conditional_edges(
#     "verification",
#     lambda state: "fallback" if state.get("needs_fallback", False) else "orchestrator",
#     {
#         "fallback": "fallback",
#         "orchestrator": "orchestrator"
#     }
# )
# # todo: send logs to server

# # Fallback -> Back to Orchestration for new planning
# workflow.add_edge("fallback", "orchestrator")
# # todo: send logs to server

# # Interaction ends the process
# workflow.add_edge("interaction", END)
# # todo: send logs to server

# # Compile
# app = workflow.compile()