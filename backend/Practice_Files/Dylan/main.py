from langgraph.graph import StateGraph, END
from agents.orchestrator import Orchestrator
from agents.executor import Executor
from agents.verifier import Verifier
from agents.fallback import Fallback
from agents.interaction import InteractionAgent
from state import ProjectState



# TODO: Add human-in-the-loop. Make sure to finish current first.
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