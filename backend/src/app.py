"""
Intelligent Browser Agents — subprocess entry point.

Runs the LangGraph workflow and communicates with the server via:
  stdout  → log lines  (plain text)
  stdout  → HITL messages (lines prefixed with @@HITL@@ followed by JSON)
  stdin   ← user replies  (one JSON line per reply: {"user_input": "..."})
"""

from playwright.async_api import async_playwright, Browser, Error as PlaywrightError
from dom_extraction import dom_extractor
from execution import Action, dispatch_action, ActionArgs
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from agents.verifier import Verifier
from main import build_workflow
import asyncio
import argparse
import json
import sys
import traceback

# Reconfigure stdout/stderr to UTF-8 so Unicode from web pages doesn't crash on Windows cp1252.
# write_through=True preserves unbuffered behaviour required by subprocess pipes.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", write_through=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", write_through=True)
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

Verifier.reset_simulation()

HITL_PREFIX = "@@HITL@@"


def send_hitl(payload: dict):
    """Send a structured HITL message to the server over stdout."""
    print(f"{HITL_PREFIX}{json.dumps(payload, ensure_ascii=False)}", flush=True)


async def read_stdin_line() -> str:
    """Read one line from stdin without blocking the event loop."""
    loop = asyncio.get_event_loop()
    line = await loop.run_in_executor(None, sys.stdin.readline)
    return line.strip()


def print_event(node_name: str, state_update: dict):
    """Pretty-print a single graph event (unchanged from original logging)."""
    print(f"\n{'-' * 40}", flush=True)
    print(f"[NODE]: {node_name.upper()}", flush=True)
    print(f"{'-' * 40}", flush=True)

    if "current_plan" in state_update and state_update["current_plan"]:
        print("  PLAN:", flush=True)
        for i, step in enumerate(state_update["current_plan"]):
            marker = ">>>" if i == state_update.get("current_step_index", 0) else "   "
            print(f"    {marker} {i+1}. {step}", flush=True)
    if "plan_status" in state_update:
        print(f"  Plan Status: {state_update['plan_status']}", flush=True)
    if "current_step_index" in state_update:
        print(f"  Current Step: {state_update['current_step_index'] + 1}", flush=True)
    if "reasoning_log" in state_update and state_update["reasoning_log"]:
        latest = state_update["reasoning_log"][-1]
        if node_name == "interaction":
            print(f"  Reasoning: {latest}", flush=True)
        elif len(latest) > 200:
            print(f"  Reasoning: {latest[:200]}...", flush=True)
        else:
            print(f"  Reasoning: {latest}", flush=True)
    if "current_task" in state_update:
        print(f"  Current Task: {state_update['current_task']}", flush=True)
    if "is_complete" in state_update:
        print(f"  Is Complete: {state_update['is_complete']}", flush=True)
    if "needs_fallback" in state_update:
        print(f"  Needs Fallback: {state_update['needs_fallback']}", flush=True)
    if "number_of_transactions" in state_update:
        print(f"  Transactions Completed: {state_update['number_of_transactions']}", flush=True)


async def main(prompt: str, video_port: int):
    config = {
        "configurable": {"thread_id": "simulation_001"},
        "recursion_limit": 80,
    }

    user_request = prompt
    graph_input = {
        "messages": [{"role": "user", "content": f"USER REQUEST: {user_request}"}],
        "current_url": "https://google.com",
        "plan_history": [],
        "current_plan": [],
        "current_step_index": 0,
        "plan_status": "CREATE",
        "current_task": "",
        "reasoning_log": [],
        "extracted_content": [],
        "is_complete": False,
        "handoff_interaction": False,
        "needs_fallback": False,
        "last_step_complete": False,
        "step_attempts": 0,
        "max_step_attempts": 6,
        "max_transactions": 80,
        "mission_failed": False,
        "abort_reason": None,
        "screenshot": None,
    }

    print("=" * 60, flush=True)
    print("INTELLIGENT BROWSER AGENT - SIMULATION", flush=True)
    print("=" * 60, flush=True)
    print(f"\nUser Request: {user_request}", flush=True)
    print(f"Starting URL: {graph_input['current_url']}", flush=True)
    print("=" * 60, flush=True)

    async with async_playwright() as p:
        print(f"Launching browser on port {video_port}...", flush=True)
        browser = await p.chromium.launch(
            headless=False, args=[f"--remote-debugging-port={video_port}"]
        )
        print(f"Browser launched on port {video_port}. Waiting for frontend connection...", flush=True)
        context = await browser.new_context()
        page = await context.new_page()

        runtime = {"page": page}
        checkpointer = MemorySaver()
        workflow = build_workflow(runtime)
        app = workflow.compile(checkpointer=checkpointer)

        # ── Main HITL loop ────────────────────────────────────
        # Each iteration streams graph events until the graph either
        # completes (reaches END) or hits an interrupt() inside the
        # interaction node.  On interrupt we deliver the message to
        # the user and, if clarification is needed, wait for input
        # before resuming.
        stream_input = graph_input
        while True:
            try:
                async for event in app.astream(stream_input, config):
                    for node_name, state_update in event.items():
                        print_event(node_name, state_update)
            except Exception:
                print("\n[FATAL] Graph execution crashed:", flush=True)
                traceback.print_exc()
                break

            # Check whether the graph stopped because of an interrupt
            state_snapshot = app.get_state(config)
            pending = state_snapshot.tasks
            has_interrupt = any(
                getattr(t, "interrupts", None) for t in pending
            ) if pending else False

            if not has_interrupt:
                break

            # Extract the interrupt payload from the interaction node
            interrupt_value = None
            for task in pending:
                for intr in getattr(task, "interrupts", []):
                    interrupt_value = intr.value
                    break
                if interrupt_value is not None:
                    break

            if interrupt_value is None:
                break

            hitl_type = interrupt_value.get("type", "finish")
            hitl_message = interrupt_value.get("message", "")

            # Send structured HITL message to the server / frontend
            send_hitl(interrupt_value)

            if hitl_type == "finish":
                # Deliver the final response and resume to let the
                # graph apply the node's return value and reach END.
                stream_input = Command(resume=True)
                # Run one more iteration so the node's return is applied
                try:
                    async for event in app.astream(stream_input, config):
                        for node_name, state_update in event.items():
                            print_event(node_name, state_update)
                except Exception:
                    pass
                break

            # ── Clarification needed — wait for user input ──
            print("[HITL] Waiting for user input...", flush=True)
            raw_line = await read_stdin_line()
            if not raw_line:
                print("[HITL] No input received, aborting.", flush=True)
                break

            try:
                payload = json.loads(raw_line)
                user_reply = payload.get("user_input", raw_line)
            except json.JSONDecodeError:
                user_reply = raw_line

            # Resume the graph — the interrupt() call inside the
            # interaction node returns this value, which becomes the
            # user's reply in the conversation.
            stream_input = Command(resume=user_reply)

    print("\n" + "=" * 60, flush=True)
    print("SIMULATION COMPLETE", flush=True)
    print("=" * 60, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=str, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.prompt, args.port))
