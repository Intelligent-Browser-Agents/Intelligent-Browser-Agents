from langgraph.checkpoint.memory import MemorySaver
from main import workflow
from agents.verifier import Verifier
import sys

# Reset verifier counter for consistent simulation
Verifier.reset_simulation()

# Initialize memory to track the thread
checkpointer = MemorySaver()
app = workflow.compile(checkpointer=checkpointer)

# 1. Setup the initial mission
config = {"configurable": {"thread_id": "simulation_001"}}

# This is a sample initial input. Notice the fields we are passing in.

# Simulation context to guide agents - this makes it explicit that actions succeed
SIMULATION_CONTEXT = """
[SIMULATION MODE]
This is a TEST SIMULATION. No real browser is connected.
- All actions should be assumed to SUCCEED unless there's a clear logical error.
- The verifier should mark steps as complete when the action matches the plan step intent.
- After all plan steps are executed, mark goal_complete=True.
- Do NOT repeatedly trigger fallback for the same issue.
- Verification steps (like "verify login") succeed by observing the simulated page state shows success indicators.
"""
user_input = str(sys.argv[1])
user_request = user_input

initial_input = {
    "messages": [{"role": "user", "content": f"{SIMULATION_CONTEXT}\n\nUSER REQUEST: {user_request}"}],
    "current_url": "https://my.ucf.edu",
    # Plan tracking
    "plan_history": [],
    "current_plan": [],  # Will be populated by orchestrator
    "current_step_index": 0,
    # Coordination
    "plan_status": "CREATE",  # Start by creating a plan
    "current_task": "",
    "reasoning_log": [],
    "is_complete": False,
    "needs_fallback": False,
    "screenshot": None,
}

# 2. Stream the execution
print("=" * 60)
print("INTELLIGENT BROWSER AGENT - SIMULATION")
print("=" * 60)
print(f"\nUser Request: {user_request}")
print(f"Starting URL: {initial_input['current_url']}")
print("=" * 60)

for event in app.stream(initial_input, config):
    for node_name, state_update in event.items():
        print(f"\n{'-' * 40}")
        print(f"[NODE]: {node_name.upper()}")
        print(f"{'-' * 40}")
        
        # Show the plan if created/updated
        if "current_plan" in state_update and state_update["current_plan"]:
            print("  PLAN:")
            for i, step in enumerate(state_update["current_plan"]):
                marker = ">>>" if i == state_update.get("current_step_index", 0) else "   "
                print(f"    {marker} {i+1}. {step}")
        
        # Check the Orchestrator's plan logic
        if "plan_status" in state_update:
            print(f"  Plan Status: {state_update['plan_status']}")
        
        # Show step progress
        if "current_step_index" in state_update:
            print(f"  Current Step: {state_update['current_step_index'] + 1}")
            
        # Show reasoning if available
        if "reasoning_log" in state_update and state_update["reasoning_log"]:
            latest_reasoning = state_update["reasoning_log"][-1]
            # Truncate long reasoning for display
            if len(latest_reasoning) > 200:
                print(f"  Reasoning: {latest_reasoning[:200]}...")
            else:
                print(f"  Reasoning: {latest_reasoning}")
            
        # Check the Execution handoff
        if "current_task" in state_update:
            print(f"  Current Task: {state_update['current_task']}")
            
        # Check completion status
        if "is_complete" in state_update:
            print(f"  Is Complete: {state_update['is_complete']}")
            
        # Check fallback status
        if "needs_fallback" in state_update:
            print(f"  Needs Fallback: {state_update['needs_fallback']}")
            
        # Show final message if from interaction agent
        if "messages" in state_update and node_name == "interaction":
            print(f"\n  {'*' * 30}")
            print("  FINAL RESPONSE TO USER:")
            print(f"  {'*' * 30}")
            for msg in state_update["messages"]:
                if isinstance(msg, dict):
                    content = msg.get("content", "")
                else:
                    content = str(msg)
                # Indent the final response
                for line in content.split("\n"):
                    print(f"  {line}")
        
        # Show transaction count
        if "number_of_transactions" in state_update:
            print(f"  Transactions Completed: {state_update['number_of_transactions']}")

print("\n" + "=" * 60)
print("SIMULATION COMPLETE")
print("=" * 60)
