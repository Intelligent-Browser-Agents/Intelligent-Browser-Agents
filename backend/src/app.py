"""
Intelligent Browser Agents — subprocess entry point.

Runs the LangGraph workflow and communicates with the server via:
  stdout  → log lines  (plain text)
  stdout  → HITL messages (lines prefixed with @@HITL@@ followed by JSON)
  stdin   ← user replies  (one JSON line per reply: {"user_input": "..."})
"""

from playwright.async_api import async_playwright
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphRecursionError
from langgraph.types import Command
from main import build_workflow
import argparse
import asyncio
import json
import os
import sys
import traceback
import uuid


def _launch_headless() -> bool:
    """
    Headed Chromium requires a display (Windows/macOS desktop, Linux + X11 / xvfb).
    On headless Linux servers there is no $DISPLAY — use headless unless overridden.
    """
    if os.environ.get("PLAYWRIGHT_HEADED", "").lower() in ("1", "true", "yes"):
        return False
    if os.environ.get("PLAYWRIGHT_HEADLESS", "").lower() in ("1", "true", "yes"):
        return True
    if sys.platform == "linux" and not os.environ.get("DISPLAY"):
        return True
    return False

# Reconfigure stdout/stderr to UTF-8 so Unicode from web pages doesn't crash on Windows cp1252.
# write_through=True preserves unbuffered behaviour required by subprocess pipes.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", write_through=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", write_through=True)
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

HITL_PREFIX = "@@HITL@@"

# Supersteps of headroom between the orchestrator's own graceful abort (a soft
# stop that produces a user-facing explanation) and LangGraph's hard
# recursion_limit (which raises GraphRecursionError with no explanation at
# all). Before this, both ceilings were the same number, and every node visit
# increments both counters, so the hard stop could fire in the same superstep
# the soft stop needed to run in. Sized well above the ~5 nodes in one
# execute/verify/decide cycle so the soft stop always gets to act first.
_TRANSACTION_HEADROOM = 40

# How long to hold a paused run waiting for a HITL reply before giving up.
# Without this, a dropped frontend connection leaves the subprocess (and its
# pooled debug port) blocked on stdin forever.
_HITL_INPUT_TIMEOUT_SECONDS = float(os.environ.get("HITL_INPUT_TIMEOUT_SECONDS", "1200"))

# Resuming a "finish" interrupt should let the interaction node commit its own
# state (the final message, is_complete) and then reach END on its own. This
# caps how many times we'll do that in a row as a guard against an unforeseen
# routing bug looping instead of terminating.
_MAX_FINISH_RESUMES = 3

_DEFAULT_CHECKPOINT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".checkpoints", "runs.sqlite")
_SESSIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".browser_sessions")


def send_hitl(payload: dict):
    """Send a structured HITL message to the server over stdout."""
    print(f"{HITL_PREFIX}{json.dumps(payload, ensure_ascii=False)}", flush=True)

def _is_stop_command(text: str) -> bool:
    value = (text or "").strip().lower()
    return value in {"stop", "cancel", "quit", "exit", "abort"}


async def read_stdin_line(timeout: float = _HITL_INPUT_TIMEOUT_SECONDS) -> str | None:
    """Read one line from stdin without blocking the event loop.

    Returns None on timeout, distinct from "" (immediate EOF), so the caller
    can tell an abandoned wait from a closed pipe.
    """
    loop = asyncio.get_event_loop()
    try:
        line = await asyncio.wait_for(loop.run_in_executor(None, sys.stdin.readline), timeout=timeout)
    except asyncio.TimeoutError:
        return None
    return line.strip()


def print_event(node_name: str, state_update: dict):
    """Pretty-print a single graph event."""
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


async def _build_checkpointer():
    """A durable checkpointer when the optional sqlite backend is installed.

    Falls back to MemorySaver (in-process, lost on subprocess exit) with a
    logged notice. Returns (checkpointer, async_context_manager_or_None); the
    caller must exit the context manager if one is returned.
    """
    db_path = os.environ.get("AGENT_CHECKPOINT_DB", _DEFAULT_CHECKPOINT_DB).strip()
    if not db_path:
        print("[startup] AGENT_CHECKPOINT_DB explicitly empty; using in-memory checkpointing.", flush=True)
        return MemorySaver(), None
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    except ImportError:
        print(
            "[startup] langgraph-checkpoint-sqlite is not installed; using in-memory "
            "checkpointing. A run cannot survive a subprocess restart until it is added "
            "to requirements.txt.",
            flush=True,
        )
        return MemorySaver(), None

    try:
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        cm = AsyncSqliteSaver.from_conn_string(db_path)
        checkpointer = await cm.__aenter__()
        return checkpointer, cm
    except Exception as e:
        print(f"[startup] Could not open durable checkpoint store ({e}); using in-memory checkpointing.", flush=True)
        return MemorySaver(), None


def _session_storage_path(session_key: str) -> str:
    safe_key = "".join(c for c in (session_key or "anonymous") if c.isalnum() or c in ("-", "_")) or "anonymous"
    return os.path.join(_SESSIONS_DIR, f"{safe_key}.json")


async def _run_hitl_loop(app, config: dict, graph_input: dict) -> None:
    """Stream the graph to completion, handling interrupts as they arise.

    Each outer iteration streams graph events until the graph either completes
    (reaches END) or hits an interrupt() inside the interaction node. On
    interrupt we deliver the message to the user and, for a clarification
    request, wait for input before resuming. A "finish" interrupt is also
    resumed (with the reply discarded) so the interaction node's own state
    update — the final message and is_complete — actually commits to the
    checkpoint instead of being lost as a permanently pending interrupt.
    """
    stream_input = graph_input
    finish_resumes = 0
    while True:
        try:
            async for event in app.astream(stream_input, config):
                for node_name, state_update in event.items():
                    print_event(node_name, state_update)
        except GraphRecursionError:
            print("\n[FATAL] Graph hit the recursion limit before its own safety stop could run.", flush=True)
            send_hitl({
                "type": "finish",
                "message": (
                    "The run stopped because it exceeded the maximum number of steps "
                    "without reaching a safe checkpoint. No further actions were taken."
                ),
            })
            return
        except Exception:
            print("\n[FATAL] Graph execution crashed:", flush=True)
            traceback.print_exc()
            return

        # Check whether the graph stopped because of an interrupt
        state_snapshot = await app.aget_state(config)
        pending = state_snapshot.tasks
        has_interrupt = any(
            getattr(t, "interrupts", None) for t in pending
        ) if pending else False

        if not has_interrupt:
            return

        # Extract the interrupt payload from the interaction node
        interrupt_value = None
        for task in pending:
            for intr in getattr(task, "interrupts", []):
                interrupt_value = intr.value
                break
            if interrupt_value is not None:
                break

        if interrupt_value is None:
            return

        hitl_type = interrupt_value.get("type", "finish")
        correlation_id = interrupt_value.get("correlation_id")

        # Send structured HITL message to the server / frontend
        send_hitl(interrupt_value)

        if hitl_type == "finish":
            finish_resumes += 1
            if finish_resumes > _MAX_FINISH_RESUMES:
                print("[HITL] Finish interrupt kept recurring; ending simulation without further resume.", flush=True)
                return
            print("[HITL] Final response sent; resuming so it commits, then ending.", flush=True)
            stream_input = Command(resume={"correlation_id": correlation_id, "user_input": None})
            continue

        # ── Clarification needed — wait for user input ──
        print("[HITL] Waiting for user input...", flush=True)
        raw_line = await read_stdin_line()
        if raw_line is None:
            print("[HITL] No input received before timeout; aborting.", flush=True)
            send_hitl({"type": "finish", "message": "Run stopped: no response was received in time."})
            return
        if not raw_line:
            print("[HITL] No input received, aborting.", flush=True)
            return

        try:
            payload = json.loads(raw_line)
            user_reply = payload.get("user_input", raw_line)
        except json.JSONDecodeError:
            user_reply = raw_line

        if _is_stop_command(str(user_reply)):
            send_hitl({
                "type": "finish",
                "message": "Run stopped by user request.",
            })
            print("[HITL] User requested stop; ending simulation.", flush=True)
            return

        # Resume the graph — the interrupt() call inside the interaction node
        # returns this value. Wrapping it with the correlation id lets the
        # interaction agent detect a resume meant for a different question
        # (possible after LangGraph re-runs the node from the top on resume)
        # instead of silently consuming it at the wrong call site.
        stream_input = Command(resume={"correlation_id": correlation_id, "user_input": user_reply})


async def main(prompt: str, video_port: int, credentials: dict | None = None, run_id: str | None = None, session_key: str | None = None):
    run_id = run_id or str(uuid.uuid4())
    session_key = session_key or run_id
    max_transactions = 80
    config = {
        "configurable": {"thread_id": run_id},
        "recursion_limit": max_transactions + _TRANSACTION_HEADROOM,
    }

    user_request = prompt
    graph_input = {
        # No "USER REQUEST: " prefix: state.get_mission_goal() reads this
        # directly once, instead of four agents each stripping their own copy
        # of a marker that existed only because this string once needed one.
        "messages": [{"role": "user", "content": user_request}],
        "mission_goal": None,
        "current_url": "about:blank",
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
        "stall_cycles": 0,
        "stall_tracked_step": -1,
        "goal_retry_cycles": 0,
        "max_step_attempts": 6,
        "max_transactions": max_transactions,
        "mission_failed": False,
        "abort_reason": None,
        "pending_sensitive_action": None,
        "sensitive_action_approval": None,
        "requested_context": [],
        "screenshot": None,
        "screenshot_meta": None,
        "user_credentials": credentials or {},
        "autonomy_policy": None,
        "mission_status": "",
        "status_signals": {},
        "last_execution_event": None,
        "last_page_snapshot": None,
        "step_intent": None,
        "recovery_context": None,
        "work_items": None,
        "current_item_index": 0,
        "item_results": [],
    }

    print("INTELLIGENT BROWSER AGENT - SIMULATION", flush=True)
    print(f"Run ID: {run_id}", flush=True)
    print(f"\nUser Request: {user_request}", flush=True)
    print(f"Starting URL: {graph_input['current_url']}", flush=True)

    headless = _launch_headless()
    storage_state_path = _session_storage_path(session_key)
    has_saved_session = os.path.isfile(storage_state_path)

    async with async_playwright() as p:
        print(f"Launching browser on port {video_port} (headless={headless})...", flush=True)
        browser = await p.chromium.launch(
            headless=headless,
            args=[f"--remote-debugging-port={video_port}"],
        )
        print(f"Browser launched on port {video_port}. Waiting for frontend connection...", flush=True)
        # Explicit viewport: frame geometry and the live view's coordinate
        # mapping must not depend on a Playwright default that happens to be
        # 1280x720 today. The streaming relay reports the real size in a
        # VIEWPORT message either way.
        context_kwargs = {"viewport": {"width": 1280, "height": 720}}
        if has_saved_session:
            context_kwargs["storage_state"] = storage_state_path
            print(f"Restoring saved browser session for {session_key}.", flush=True)
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        # Auto-dismiss JavaScript dialogs (alert/confirm/prompt/beforeunload).
        # An unhandled dialog blocks Playwright's event loop, which freezes
        # all async I/O including LLM API calls.
        page.on("dialog", lambda dialog: asyncio.ensure_future(dialog.accept()))

        runtime = {"page": page}
        checkpointer, checkpointer_cm = await _build_checkpointer()
        try:
            workflow = build_workflow(runtime)
            graph = workflow.compile(checkpointer=checkpointer)
            await _run_hitl_loop(graph, config, graph_input)
        finally:
            if checkpointer_cm is not None:
                try:
                    await checkpointer_cm.__aexit__(None, None, None)
                except Exception:
                    pass

        # Persist cookies/localStorage for next time so the agent does not
        # re-authenticate on every run. Best-effort: a failure here should not
        # turn a completed mission into a crashed one.
        try:
            os.makedirs(_SESSIONS_DIR, exist_ok=True)
            await context.storage_state(path=storage_state_path)
        except Exception as e:
            print(f"[shutdown] Could not save browser session: {e}", flush=True)

    print("", flush=True)
    print("SIMULATION COMPLETE", flush=True)


def read_credentials_from_stdin() -> dict:
    """Read the credential blob the server writes as the first stdin line.

    Credentials used to arrive as a --credentials_json command-line argument,
    which is visible to any other process on the machine through the process
    list. stdin is private to the parent and this child.
    """
    try:
        line = sys.stdin.readline()
    except (OSError, ValueError):
        return {}
    if not line or not line.strip():
        return {}
    try:
        loaded = json.loads(line)
    except json.JSONDecodeError:
        print("[startup] Could not parse the credential line; continuing without saved credentials.", flush=True)
        return {}
    return loaded if isinstance(loaded, dict) else {}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", type=str, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--run_id", type=str, default=None, help="Resume an existing run's checkpoint (requires a durable checkpointer).")
    parser.add_argument("--session_key", type=str, default=None, help="Identity for browser session persistence (defaults to run_id).")
    args = parser.parse_args()

    credentials = read_credentials_from_stdin()

    asyncio.run(main(args.prompt, args.port, credentials, run_id=args.run_id, session_key=args.session_key))
