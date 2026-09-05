"""The sensitive-action approval handshake.

Live failure (Apple careers run, 2026-09-05): the user approved the gated
"Submit Resume" click three times and it never ran. The approval was an exact
signature of the proposed arguments, the graph went back through the
orchestrator, a fresh executor call re-chose the action (and the page's other
duplicate link), and an unclear reply left the checkpoint. These tests pin the
repaired handshake: the approval carries the action, the graph routes straight
to the executor, and the executor dispatches it without a model call.
"""

from types import SimpleNamespace

import pytest

import agents.executor as executor_module
import agents.interaction as interaction_module
from agents.executor import Executor
from agents.interaction import InteractionAgent
from autonomy import approved_action
from execution.models import ExecutionOutput
from main import route_after_interaction


SUBMIT_RESUME = "Submit Resume: Software Engineer, Observability 200641941-3401"
CLICK_ARGS = {"role": "link", "name": SUBMIT_RESUME, "nth": 0}
PENDING = {
    "action": "click",
    "args": dict(CLICK_ARGS),
    "current_task": "Open the selected position's application process.",
    "reason": "final submission requires confirmation at this autonomy level",
    "target": f"click(link, {SUBMIT_RESUME})",
    "message": (
        f"Sensitive action checkpoint. I am about to execute click(link, {SUBMIT_RESUME}). "
        "Reply 'yes' to proceed or 'no' to cancel."
    ),
    "action_signature": Executor._action_signature("click", CLICK_ARGS),
}


def _interaction_with_replies(monkeypatch, replies):
    """An InteractionAgent whose interrupt() answers from `replies`, in order.

    A finish announcement is also an interrupt; it gets None once the replies
    run out, which the agent ignores.
    """
    payloads = []
    queue = list(replies)

    def fake_interrupt(payload):
        payloads.append(payload)
        return {
            "correlation_id": payload["correlation_id"],
            "user_input": queue.pop(0) if queue else None,
        }

    monkeypatch.setattr(interaction_module, "interrupt", fake_interrupt)
    return InteractionAgent(), payloads


def _checkpoint_state():
    return {
        "number_of_transactions": 11,
        "pending_sensitive_action": dict(PENDING),
        "messages": [{"role": "user", "content": "apply to apple as a software engineer"}],
        "reasoning_log": [],
    }


# ── the approval record ────────────────────────────────────────────────

def test_yes_records_the_exact_action_and_arguments(monkeypatch):
    agent, payloads = _interaction_with_replies(monkeypatch, ["yes"])

    out = agent(_checkpoint_state())

    assert len(payloads) == 1
    assert payloads[0]["requested_fields"] == ["approval"]
    approval = out["sensitive_action_approval"]
    assert approval["approved"] is True
    assert approval["action"] == "click"
    assert approval["args"] == CLICK_ARGS
    assert out["pending_sensitive_action"] is None
    assert out["is_complete"] is False
    assert approved_action(out) is approval


def test_unclear_reply_is_re_asked_inside_the_checkpoint(monkeypatch):
    """"yesd" used to leave the node: the orchestrator and a fresh executor turn
    ran before the question came back. The checkpoint now asks again itself."""
    agent, payloads = _interaction_with_replies(monkeypatch, ["yesd", "yes"])

    out = agent(_checkpoint_state())

    assert len(payloads) == 2
    assert "did not understand" in payloads[1]["message"]
    assert "yesd" in payloads[1]["message"]
    assert SUBMIT_RESUME in payloads[1]["message"]
    assert payloads[1]["requested_fields"] == ["approval"]
    # A distinct question gets a distinct correlation id, so the replay after
    # resume cannot hand the first (unclear) reply to the second question.
    assert payloads[1]["correlation_id"] != payloads[0]["correlation_id"]
    assert out["sensitive_action_approval"]["approved"] is True
    assert out["sensitive_action_approval"]["args"] == CLICK_ARGS


def test_no_ends_the_run_without_an_executable_approval(monkeypatch):
    agent, _payloads = _interaction_with_replies(monkeypatch, ["no"])

    out = agent(_checkpoint_state())

    assert out["is_complete"] is True
    assert out["sensitive_action_approval"]["approved"] is False
    assert approved_action(out) is None


# ── routing ────────────────────────────────────────────────────────────

def test_route_after_interaction_prefers_end_then_execution_then_orchestrator():
    approved = {"approved": True, "action": "click", "args": dict(CLICK_ARGS)}
    denied = {"approved": False, "action": "click", "args": dict(CLICK_ARGS)}

    assert route_after_interaction({"is_complete": True, "sensitive_action_approval": approved}) == "END"
    assert route_after_interaction({"is_complete": False, "sensitive_action_approval": approved}) == "execution"
    assert route_after_interaction({"is_complete": False, "sensitive_action_approval": denied}) == "orchestrator"
    assert route_after_interaction({"is_complete": False}) == "orchestrator"


def test_legacy_approval_without_arguments_is_not_dispatched():
    """A checkpoint written by the old code carries only a signature."""
    legacy = {"approved": True, "action_signature": "click:{}", "action": "click"}
    assert approved_action({"sensitive_action_approval": legacy}) is None
    assert route_after_interaction({"sensitive_action_approval": legacy}) == "orchestrator"


# ── executor ───────────────────────────────────────────────────────────

class _FakePage:
    url = "https://jobs.apple.com/en-us/details/200641941/software-engineer-observability"
    context = SimpleNamespace(pages=[])


def _executor_with_fake_dispatch(monkeypatch, outcome):
    page = _FakePage()
    executor = Executor({"page": page})
    dispatched = []

    async def fake_dispatch(_page, action, runtime=None):
        dispatched.append(action)
        return outcome

    async def fake_snapshot(_page, max_chars=0, section=1):
        return '[ref=e1] [role="heading"] "Software Engineer, Observability"'

    monkeypatch.setattr(executor_module, "dispatch_action", fake_dispatch)
    monkeypatch.setattr(executor, "_get_real_dom_snapshot", fake_snapshot)
    return executor, dispatched


def _approved_state(args=None):
    return {
        "current_task": "Open the selected position's application process.",
        "current_url": _FakePage.url,
        "messages": [{"role": "user", "content": "apply to apple as a software engineer"}],
        "reasoning_log": [],
        "number_of_transactions": 12,
        "sensitive_action_approval": {
            "approved": True,
            "reply": "yes",
            "action": "click",
            "args": dict(args or CLICK_ARGS),
            "action_signature": PENDING["action_signature"],
            "target": PENDING["target"],
        },
    }


def _outcome(status, error_type="none", message="Clicked link.", verified=True):
    return ExecutionOutput(
        action="click",
        args=dict(CLICK_ARGS),
        status=status,
        error_type=error_type,
        message=message,
        execution_time_ms=40,
        verified=verified,
    )


@pytest.mark.asyncio
async def test_executor_dispatches_the_approved_click_without_a_model_call(monkeypatch):
    executor, dispatched = _executor_with_fake_dispatch(
        monkeypatch, _outcome("success", message=f"Clicked link '{SUBMIT_RESUME}'")
    )

    out = await executor(_approved_state())

    # No model was consulted: the stubs record every invocation.
    assert executor.llm_chat.calls == []
    assert executor.llm_structured.calls == []
    # The recorded arguments went to the page as-is, nth included: the page's
    # other duplicate link (nth=1) cannot be substituted any more.
    assert len(dispatched) == 1
    assert dispatched[0].action == "click"
    assert dispatched[0].args.name == SUBMIT_RESUME
    assert dispatched[0].args.nth == 0
    assert out["sensitive_action_approval"] is None
    assert out["last_execution_event"]["status"] == "success"
    assert "explicit user approval" in out["reasoning_log"][0]
    assert "handoff_interaction" not in out


@pytest.mark.asyncio
async def test_failed_approved_dispatch_still_clears_the_approval(monkeypatch):
    """The ticket is one-shot. If the page changed and the click misses, the
    ordinary verify/fallback path takes over and a retry asks again."""
    executor, dispatched = _executor_with_fake_dispatch(
        monkeypatch,
        _outcome("failure", error_type="element_not_found", message="No link named that.", verified=False),
    )

    out = await executor(_approved_state())

    assert len(dispatched) == 1
    assert out["sensitive_action_approval"] is None
    assert out["last_execution_event"]["status"] == "failure"


def test_action_args_from_tool_args_maps_file_path_and_drops_nones():
    args = Executor._action_args_from_tool_args(
        {"role": "textbox", "name": "Resume", "file_path": "/store/1/resume/r.pdf", "nth": None}
    )
    assert args.document_id == "/store/1/resume/r.pdf"
    assert args.nth is None
    assert Executor._action_args_from_tool_args({"role": "link", "name": "Submit", "nth": 1}).nth == 1
