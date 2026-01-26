from langgraph.graph import StateGraph, END
from agents.orchestrator import Orchestrator
from agents.executor import Executor
from agents.verifier import Verifier
from agents.fallback import Fallback
from agents.interaction import InteractionAgent
from state import ProjectState
from google import genai


client = genai.Client()


# prompts for each agent from their respective files
# === prompts start ===

# helper to grab text from the md files in the prompts folder
def read_markdown_file(file_path): 
    try: 
        with open(file_path, 'r', encoding='utf-8') as f: 
            markdown_text = f.read()
        return markdown_text
    except FileNotFoundError:
        return f"Error: {file_path} was not found."

orchestration_prompt = read_markdown_file('backend\prototype\prompts\orchestration.prompt.md')
execution_prompt = read_markdown_file('backend\prototype\prompts\execution.prompt.md')
verification_prompt = read_markdown_file('backend\prototype\prompts\\verification.prompt.md')
fallback_prompt = read_markdown_file('backend\prototype\prompts\\fallback.prompt.md')
interaction_prompt = read_markdown_file('backend\prototype\prompts\interaction.prompt.md')
# === prompts end ===

# TODO: Add human-in-the-loop. Make sure to finish current first.
# todo: grab user input from frontend
user_input = "example text"

# Initialize the graph
workflow = StateGraph(ProjectState)

# Add nodes
workflow.add_node("orchestrator", Orchestrator())
workflow.add_node("execution", Executor())
workflow.add_node("verification", Verifier())
workflow.add_node("fallback", Fallback())
workflow.add_node("interaction", InteractionAgent())

# Define the edges
workflow.set_entry_point("orchestrator")

# Orchestration -> Execution
workflow.add_edge("orchestrator", "execution")

# Execution -> Verification
workflow.add_edge("execution", "verification")

# Verification Logic: Path based on success/failure
workflow.add_conditional_edges(
    "verification",
    lambda state: "fallback" if state["needs_fallback"] else "orchestrator",
    {
        "fallback": "fallback",
        "orchestrator": "orchestrator" # Return success to orchestration
    }
)

# Fallback -> Back to Orchestration for new planning
workflow.add_edge("fallback", "orchestrator")

# Orchestration -> Interaction
workflow.add_conditional_edges(
    "orchestrator",
    lambda state: "interaction" if state["is_complete"] else "execution",
    {
        "interaction": "interaction",
        "execution": "execution"
    }
)

# Interaction ends the process
workflow.add_edge("interaction", END)

# Compile
app = workflow.compile()