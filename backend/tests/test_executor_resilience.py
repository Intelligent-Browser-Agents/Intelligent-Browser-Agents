import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


BACKEND_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BACKEND_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import agents.executor as executor_module
from agents.executor import Executor
from execution.models import ActionArgs, ExecutionOutput
from schema import ExecutionArgs, ExecutionResult


class DummyPage:
    def __init__(self, url: str = "https://ucf.edu"):
        self.url = url


class DummyLLM:
    def __init__(self, response: ExecutionResult):
        self.response = response
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        return self.response


def make_state(task: str = "Locate the search bar on the page.", url: str = "https://ucf.edu") -> dict:
    return {
        "messages": [{"role": "user", "content": "USER REQUEST: navigate to https://ucf.edu then search for academics"}],
        "current_task": task,
        "current_url": url,
        "number_of_transactions": 1,
    }


def build_executor(response: ExecutionResult, page: DummyPage | None = None, llm: DummyLLM | None = None) -> tuple[Executor, DummyLLM]:
    selected_page = page or DummyPage()
    selected_llm = llm or DummyLLM(response)

    executor = Executor.__new__(Executor)
    executor.runtime = {"page": selected_page}
    executor.system_prompt = "Test execution prompt"
    executor.llm = selected_llm
    return executor, selected_llm


def install_dom_mocks(monkeypatch, elements=None):
    interactive_elements = elements or [{"role": "textbox", "name": "Search site"}]

    async def fake_dom_main(page):
        return ('{"status":"success","url":"https://ucf.edu","title":"UCF","dom_tree":"<html></html>"}', b"", page)

    def fake_retrieve_interactive_elements(dom_json: str):
        return json.dumps({
            "status": "success",
            "interactive_elements": interactive_elements,
        })

    monkeypatch.setattr(executor_module.dom_extractor, "main", fake_dom_main)
    monkeypatch.setattr(executor_module.dom_extractor, "retrieve_interactive_elements", fake_retrieve_interactive_elements)


@pytest.mark.asyncio
async def test_click_missing_target_returns_structured_failure(monkeypatch):
    install_dom_mocks(monkeypatch)

    response = ExecutionResult(
        action="click",
        args=ExecutionArgs(role=None, name=None),
        status="success",
        error_type="none",
        message="Click the search bar.",
    )
    executor, _ = build_executor(response)

    was_dispatched = {"called": False}

    async def fake_dispatch(page, action):
        was_dispatched["called"] = True
        raise AssertionError("dispatch_action should not be called for invalid click args")

    monkeypatch.setattr(executor_module, "dispatch_action", fake_dispatch)

    state = {
        "messages": [{"role": "user", "content": "USER REQUEST: click the required control"}],
        "current_task": "Click the required control.",
        "current_url": "https://ucf.edu",
        "number_of_transactions": 1,
    }
    result = await executor(state)
    log = result["reasoning_log"][0]

    assert was_dispatched["called"] is False
    assert "[Executor] Status: failure" in log
    assert "Dispatch: skipped (invalid_action_args)" in log
    assert "Error Type: ambiguous_step" in log


@pytest.mark.asyncio
async def test_search_with_text_reaches_dispatch(monkeypatch):
    install_dom_mocks(monkeypatch)

    response = ExecutionResult(
        action="search",
        args=ExecutionArgs(text="academics"),
        status="success",
        error_type="none",
        message="Search for academics.",
    )
    page = DummyPage(url="https://ucf.edu")
    executor, _ = build_executor(response, page=page)

    captured = {"action": None}

    async def fake_dispatch(dispatch_page, action):
        captured["action"] = action
        dispatch_page.url = "https://ucf.edu/search/?q=academics"
        return ExecutionOutput(
            action="search",
            args={"text": "academics"},
            status="success",
            error_type="none",
            message="Searched for academics",
            execution_time_ms=12,
        )

    monkeypatch.setattr(executor_module, "dispatch_action", fake_dispatch)

    result = await executor(make_state(task="Search for academics in the site search bar."))
    log = result["reasoning_log"][0]

    assert captured["action"] is not None
    assert captured["action"].args.text == "academics"
    assert "[Executor] Status: success" in log
    assert result["current_url"] == "https://ucf.edu/search/?q=academics"


@pytest.mark.asyncio
async def test_search_text_is_recovered_from_current_task(monkeypatch):
    install_dom_mocks(monkeypatch)

    response = ExecutionResult(
        action="search",
        args=ExecutionArgs(text=None),
        status="failure",
        error_type="ambiguous_step",
        message="The search tool requires a text argument.",
    )
    page = DummyPage(url="https://ucf.edu")
    executor, _ = build_executor(response, page=page)

    captured = {"action": None}

    async def fake_dispatch(dispatch_page, action):
        captured["action"] = action
        dispatch_page.url = "https://ucf.edu/search/?q=academics"
        return ExecutionOutput(
            action="search",
            args={"text": action.args.text},
            status="success",
            error_type="none",
            message=f"Searched for '{action.args.text}'",
            execution_time_ms=20,
        )

    monkeypatch.setattr(executor_module, "dispatch_action", fake_dispatch)

    result = await executor(make_state(task="Enter 'academics' in the search bar."))
    log = result["reasoning_log"][0]

    assert captured["action"] is not None
    assert captured["action"].args.text == "academics"
    assert "[Executor] Status: success" in log
    assert "Recovery: inferred text='academics'" in log


@pytest.mark.asyncio
async def test_search_text_is_recovered_from_plan_context(monkeypatch):
    install_dom_mocks(monkeypatch)

    response = ExecutionResult(
        action="search",
        args=ExecutionArgs(text=None),
        status="failure",
        error_type="ambiguous_step",
        message="Missing search text.",
    )
    page = DummyPage(url="https://ucf.edu")
    executor, _ = build_executor(response, page=page)

    captured = {"action": None}

    async def fake_dispatch(dispatch_page, action):
        captured["action"] = action
        return ExecutionOutput(
            action="search",
            args={"text": action.args.text},
            status="success",
            error_type="none",
            message="Recovered search",
            execution_time_ms=9,
        )

    monkeypatch.setattr(executor_module, "dispatch_action", fake_dispatch)

    state = make_state(task="Initiate the search.")
    state["current_plan"] = [
        "Navigate to https://ucf.edu",
        "Enter 'academics' in the search bar.",
        "Initiate the search.",
    ]
    result = await executor(state)
    log = result["reasoning_log"][0]

    assert captured["action"] is not None
    assert captured["action"].args.text == "academics"
    assert "Recovery: inferred text='academics'" in log


@pytest.mark.asyncio
async def test_search_recovery_prefers_quoted_query_from_context(monkeypatch):
    install_dom_mocks(monkeypatch)

    response = ExecutionResult(
        action="search",
        args=ExecutionArgs(text=None),
        status="failure",
        error_type="ambiguous_step",
        message="Missing search text.",
    )
    executor, _ = build_executor(response, page=DummyPage(url="https://ucf.edu"))

    captured = {"action": None}

    async def fake_dispatch(dispatch_page, action):
        captured["action"] = action
        return ExecutionOutput(
            action="search",
            args={"text": action.args.text},
            status="success",
            error_type="none",
            message="Recovered search",
            execution_time_ms=10,
        )

    monkeypatch.setattr(executor_module, "dispatch_action", fake_dispatch)

    state = make_state(task="Locate and present the relevant search results related to academics.")
    state["current_plan"] = [
        "Navigate to https://ucf.edu",
        "Search for 'academics' using the search bar.",
        "Locate and present the relevant search results related to academics.",
    ]
    result = await executor(state)
    log = result["reasoning_log"][0]

    assert captured["action"] is not None
    assert captured["action"].args.text == "academics"
    assert "Recovery: inferred text='academics'" in log


@pytest.mark.asyncio
async def test_click_target_is_recovered_from_dom_for_search_task(monkeypatch):
    install_dom_mocks(
        monkeypatch,
        elements=[
            {"role": "button", "name": "Search"},
            {"role": "textbox", "name": "Search UCF"},
            {"role": "link", "name": "Academics"},
        ],
    )

    response = ExecutionResult(
        action="click",
        args=ExecutionArgs(role=None, name=None),
        status="failure",
        error_type="ambiguous_step",
        message="Could not determine the element to click.",
    )
    page = DummyPage(url="https://ucf.edu")
    executor, _ = build_executor(response, page=page)

    captured = {"action": None}

    async def fake_dispatch(dispatch_page, action):
        captured["action"] = action
        return ExecutionOutput(
            action="click",
            args={"role": action.args.role, "name": action.args.name},
            status="success",
            error_type="none",
            message="Clicked recovered target",
            execution_time_ms=11,
        )

    monkeypatch.setattr(executor_module, "dispatch_action", fake_dispatch)

    result = await executor(make_state(task="Locate the search bar on the UCF website."))
    log = result["reasoning_log"][0]

    assert captured["action"] is not None
    assert captured["action"].args.role in {"textbox", "searchbox", "combobox"}
    assert captured["action"].args.name == "Search UCF"
    assert "[Executor] Status: success" in log
    assert "Recovery: inferred click target" in log


@pytest.mark.asyncio
async def test_model_failure_skips_dispatch(monkeypatch):
    install_dom_mocks(monkeypatch)

    response = ExecutionResult(
        action="wait",
        args=ExecutionArgs(seconds=1.0),
        status="failure",
        error_type="ambiguous_step",
        message="Step is ambiguous.",
    )
    executor, _ = build_executor(response)

    async def fake_dispatch(page, action):
        raise AssertionError("dispatch_action should be skipped when model returns failure")

    monkeypatch.setattr(executor_module, "dispatch_action", fake_dispatch)

    result = await executor(make_state(task="Wait for page transition."))
    log = result["reasoning_log"][0]

    assert "[Executor] Status: failure" in log
    assert "Dispatch: skipped (model_reported_failure)" in log
    assert "Error Type: ambiguous_step" in log


@pytest.mark.asyncio
async def test_prompt_uses_real_interactive_dom_snapshot(monkeypatch):
    calls = {"dom_main": 0, "retrieve": 0}

    async def fake_dom_main(page):
        calls["dom_main"] += 1
        return ('{"status":"success","url":"https://ucf.edu","title":"UCF","dom_tree":"<html></html>"}', b"", page)

    def fake_retrieve_interactive_elements(dom_json: str):
        calls["retrieve"] += 1
        return json.dumps({
            "status": "success",
            "interactive_elements": [
                {"role": "textbox", "name": "Search site"},
                {"role": "link", "name": "Academics"},
            ],
        })

    monkeypatch.setattr(executor_module.dom_extractor, "main", fake_dom_main)
    monkeypatch.setattr(executor_module.dom_extractor, "retrieve_interactive_elements", fake_retrieve_interactive_elements)

    response = ExecutionResult(
        action="wait",
        args=ExecutionArgs(seconds=0.1),
        status="success",
        error_type="none",
        message="Wait briefly.",
    )
    llm = DummyLLM(response)
    executor, _ = build_executor(response, llm=llm)

    async def fake_dispatch(page, action):
        return ExecutionOutput(
            action="wait",
            args={"seconds": 0.1},
            status="success",
            error_type="none",
            message="Waited 0.1s",
            execution_time_ms=100,
        )

    monkeypatch.setattr(executor_module, "dispatch_action", fake_dispatch)

    await executor(make_state(task="Pause briefly before the next action."))

    assert calls["dom_main"] == 1
    assert calls["retrieve"] == 1
    assert llm.messages is not None
    human_message = llm.messages[1].content
    assert '[role="textbox"] "Search site"' in human_message
    assert '[role="link"] "Academics"' in human_message


def test_actionargs_accepts_legacy_query_alias():
    args = ActionArgs(query="academics")
    dumped = args.model_dump()

    assert args.text == "academics"
    assert dumped["text"] == "academics"
    assert "query" not in dumped


def test_executionargs_accepts_legacy_query_alias():
    args = ExecutionArgs(query="academics")
    dumped = args.model_dump()

    assert args.text == "academics"
    assert dumped["text"] == "academics"
    assert "query" not in dumped


def test_actionargs_rejects_unexpected_extra_field():
    with pytest.raises(ValidationError):
        ActionArgs(text="academics", unexpected="value")


def test_dom_cache_context_prefers_diff_summary_when_two_snapshots_exist():
    state = {
        "dom_cache": [
            "URL: https://booking.com\nWhere are you going?\nSearch\nPopular destinations",
            "URL: https://booking.com/searchresults\nRiu Plaza Chicago\nShow prices\nFilter by price",
        ]
    }

    context = Executor._build_dom_cache_context(state)

    assert "cached diff summary" in context
    assert "text_added_count" in context
    assert "Riu Plaza Chicago" in context


def test_dom_snapshot_budget_for_listing_tasks_is_moderate_and_bounded():
    budget = Executor._dom_snapshot_budget("Select a hotel from the booking results listing.")

    assert budget == 5500
