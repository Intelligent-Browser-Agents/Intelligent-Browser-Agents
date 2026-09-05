from langgraph.graph import StateGraph, END
from agents.orchestrator import Orchestrator
from agents.verifier import Verifier
from agents.executor import Executor
from agents.fallback import Fallback
from agents.interaction import InteractionAgent
from state import ProjectState
from autonomy import approved_action
import status_tracker

# Agents load their own prompts through prompt_loader, which resolves paths
# relative to this package rather than the process working directory.


def route_after_interaction(state) -> str:
    """Where the graph goes after the interaction node.

    END when the mission is complete or aborted. Straight back to execution when
    the user has just approved a sensitive action: the approval is a one-shot
    ticket the executor dispatches as-is. Routing it through the orchestrator
    first let a fresh decision rewrite the task and a fresh executor call pick a
    different target, so the same click was confirmed three times in the Apple
    careers run. Otherwise the orchestrator (a clarification was answered or
    context was supplied).
    """
    if state.get("is_complete", False):
        return "END"
    if approved_action(state) is not None:
        return "execution"
    return "orchestrator"


def build_workflow(runtime):
    # Initialize the graph
    workflow = StateGraph(ProjectState)

    # Add nodes — each wrapped with the status tracker so mission_status
    # is refreshed after every node execution.
    workflow.add_node("orchestrator", status_tracker.wrap(Orchestrator(), "orchestrator"))
    workflow.add_node("execution", status_tracker.wrap(Executor(runtime), "execution"))
    workflow.add_node("verification", status_tracker.wrap(Verifier(), "verification"))
    workflow.add_node("fallback", status_tracker.wrap(Fallback(), "fallback"))
    workflow.add_node("interaction", status_tracker.wrap(InteractionAgent(), "interaction"))

    # Define the edges
    workflow.set_entry_point("orchestrator")

    # Orchestration -> Execution or Interaction (conditional)
    workflow.add_conditional_edges(
        "orchestrator",
        lambda state: "interaction" if state.get("handoff_interaction", False) else "execution",
        {
            "interaction": "interaction",
            "execution": "execution"
        }
    )

    # Execution -> Interaction (HITL checkpoint) or Verification
    workflow.add_conditional_edges(
        "execution",
        lambda state: "interaction" if state.get("handoff_interaction", False) else "verification",
        {
            "interaction": "interaction",
            "verification": "verification",
        }
    )

    # Verification Logic: Path based on success/failure
    workflow.add_conditional_edges(
        "verification",
        lambda state: "fallback" if state.get("needs_fallback", False) else "orchestrator",
        {
            "fallback": "fallback",
            "orchestrator": "orchestrator"
        }
    )

    # Fallback -> Interaction (if human browser help needed) or Orchestration
    workflow.add_conditional_edges(
        "fallback",
        lambda state: "interaction" if state.get("handoff_interaction", False) else "orchestrator",
        {
            "interaction": "interaction",
            "orchestrator": "orchestrator",
        }
    )


    # Interaction: END when complete/aborted, execution when a sensitive action
    # was just approved, otherwise back to the orchestrator.
    workflow.add_conditional_edges(
        "interaction",
        route_after_interaction,
        {
            "END": END,
            "execution": "execution",
            "orchestrator": "orchestrator",
        }
    )

    print("Created agent workflow!")
    return workflow

