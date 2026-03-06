"""
This file will act as the prototype of Intelligent Browser Agents (WORKING)

Course of action: 

[o] app opens an instance of browser
    [o] keep for duration of program)
    
[ ] Execution agent will select actions from execution handler
    [o] Navigate(page, url) - (working example in main.py)
    ! Everything after 'navigate's parameters are not passed in correctly. 
    [o] Click(page, role, name)
    [o] Type(page, text) - Does NOT work!!
    [X] Search(page, query)
    [o] Scroll(page, direction) - Does NOT work!!
    [o] Press Key(page, key)
    [o] Wait(page, seconds)
    
[ ] Get user input from the frontend and call this file from server passing in user input
    [ ] Send this input to the orchestrator

"""

from playwright.async_api import async_playwright, Browser, Error as PlaywrightError
from dom_extraction import dom_extractor
from execution import Action, dispatch_action, ActionArgs
from langgraph.checkpoint.memory import MemorySaver
from agents.verifier import Verifier
from main import build_workflow
import asyncio
import argparse
import sys


# Reset verifier counter for consistent simulation
Verifier.reset_simulation()

async def main(prompt: str, video_port: int):
    
    # 1. Setup the initial mission
    config = {
        "configurable": {"thread_id": "simulation_001"},
        "recursion_limit": 80,
    }

    # This is a sample initial input. Notice the fields we are passing in.

    # from frontend (use after backend testing)
    user_request = prompt
    #user_request = "navigate to https://ucf.edu. Then, go to google.com, look up nintendo, and give me information you found on the director of super smash bros."

    initial_input = {
        "messages": [{"role": "user", "content": f"USER REQUEST: {user_request}"}],
        "current_url": "https://google.com",
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
        "last_step_complete": False,
        "step_attempts": 0,
        "max_step_attempts": 6,
        "max_transactions": 80,
        "mission_failed": False,
        "abort_reason": None,
        "screenshot": None,
    }

    # 2. Stream the execution
    print("=" * 60)
    print("INTELLIGENT BROWSER AGENT - SIMULATION")
    print("=" * 60)
    print(f"\nUser Request: {user_request}")
    print(f"Starting URL: {initial_input['current_url']}")
    print("=" * 60)
    
    # create browser instance which will persist across agents
    async with async_playwright() as p:
        
        #initialize the browser instance
        print(f"Launching browser on port {video_port}...")
        browser = await p.chromium.launch(headless=False, args=[f'--remote-debugging-port={video_port}'])
        print(f"Browser launched on port {video_port}. Waiting for frontend connection...")
        context = await browser.new_context()
        page = await context.new_page()
        
       # save page to runtime object
        runtime =  {
            "page": page
        }
        
        # Initialize memory to track the thread
        checkpointer = MemorySaver()
        # initialize workflow using page as runtime across agents
        workflow = build_workflow(runtime)
        app = workflow.compile(checkpointer=checkpointer)
    

        # runs langgraph asynchronously
        async for event in app.astream(initial_input, config):
            
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=str, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.prompt, args.port))