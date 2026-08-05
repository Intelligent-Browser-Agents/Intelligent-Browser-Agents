import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

import agents.executor as executor_module
from agents.executor import Executor
from execution.models import ActionArgs, ExecutionOutput
from schema import ExecutionArgs, ExecutionResult


# Marks tests that assert executor recovery behaviour which was removed in 66fb45f
# ("removing some of the more hardcoded helpers that made it brittle"). The tests
# were left behind and never ran, because a package-name collision aborted
# collection for the whole suite. They are kept as xfail rather than deleted or
# rewritten: they describe target behaviour for Phase 2 of docs/IMPROVEMENT_PLAN.md,
# which replaces this guesswork with explicit `ambiguous_target` candidate lists.
removed_recovery = pytest.mark.xfail(
    reason="Executor arg-recovery from plan/DOM context was removed; see Phase 2 of docs/IMPROVEMENT_PLAN.md",
    strict=True,
)

DEFAULT_ELEMENTS = [{"role": "textbox", "name": "Search site"}]


class DummyLocator:
    """Answers `locator("body").aria_snapshot()`, the modern snapshot source."""

    def __init__(self, elements):
        self._elements = elements

    async def aria_snapshot(self, **_kwargs):
        return "\n".join(f'- {el["role"]} "{el["name"]}"' for el in self._elements)


class DummyFrame:
    def __init__(self, elements, url: str):
        self._elements = elements
        self.url = url

    def locator(self, _selector):
        return DummyLocator(self._elements)

    async def evaluate(self, _js, *_args):
        # The metadata pass; no enrichment in the dummy.
        return []


class DummyContext:
    def __init__(self, page):
        self.pages = [page]


class DummyPage:
    """Stands in for a Playwright Page across the executor's access patterns."""

    def __init__(self, url: str = "https://ucf.edu", elements=None):
        self.url = url
        self.main_frame = DummyFrame(elements or DEFAULT_ELEMENTS, url)
        self.frames = [self.main_frame]
        self.context = DummyContext(self)

    async def screenshot(self, **_kwargs):
        return b""


class _ToolBoundLLM:
    """What `bind_tools()` returns: answers without any `tool_calls`.

    That is the executor's documented signal to fall back to structured output.
    """

    def __init__(self, parent):
        self._parent = parent

    async def ainvoke(self, messages, *_args, **_kwargs):
        self._parent.tool_messages = messages
        return AIMessage(content="no tool call")


class DummyLLM:
    """Stands in for both executor models.

    `llm_chat` and `llm_structured` are the same object here, so the two roles are
    kept apart by binding: the tool-calling path goes through `bind_tools()` and
    yields no tool call, while the structured path awaits `ainvoke` directly and
    receives the canned `ExecutionResult`.
    """

    def __init__(self, response: ExecutionResult):
        self.response = response
        self.messages = None
        self.tool_messages = None

    def invoke(self, messages):
        self.messages = messages
        return self.response

    async def ainvoke(self, messages, *_args, **_kwargs):
        self.messages = messages
        return self.response

    def bind_tools(self, _tools, **_kwargs):
        return _ToolBoundLLM(self)

    def get_num_tokens_from_messages(self, _messages, **_kwargs):
        return 0


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
    executor.system_prompt_json = "Test execution prompt"
    executor.system_prompt_tools = "Test execution tools prompt"
    executor.llm_structured = selected_llm
    executor.llm_chat = selected_llm
    return executor, selected_llm


def install_dom_mocks(monkeypatch, elements=None):
    """Stub the page-text extraction used to populate `dom_cache`.

    The interactive-element snapshot the prompt sees is built from each frame's
    `aria_snapshot()`, so pass `elements` to `DummyPage` for that.
    """

    async def fake_get_page_text(page, max_chars: int = 3500):
        return "UCF\nSearch site\nAcademics"

    monkeypatch.setattr(executor_module.dom_extractor, "get_page_text", fake_get_page_text)


@pytest.mark.asyncio
async def test_click_missing_target_returns_structured_failure(monkeypatch):
    install_dom_mocks(monkeypatch)

    response = ExecutionResult(
        action="click",
        args=ExecutionArgs(role=None, name=None),
        status="failure",
        error_type="ambiguous_step",
        message="Could not identify the element to click.",
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
    assert "Error Type: ambiguous_step" in log


def test_click_success_requires_role_and_name():
    """The schema itself rejects a successful click with no target.

    This is the guard that replaced the executor's old
    "Dispatch: skipped (invalid_action_args)" log branch.
    """
    with pytest.raises(ValidationError):
        ExecutionResult(
            action="click",
            args=ExecutionArgs(role=None, name=None),
            status="success",
            error_type="none",
            message="Click the search bar.",
        )


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
    # The recovery itself is not surfaced anywhere: _validate_and_normalize_action
    # builds a "Recovered search text from PLAN_STEP" message, then
    # _finish_from_result overwrites it with the dispatcher's own message. Assert the
    # behaviour, not the log, until the log carries the recovery.
    assert "text=academics" in log


@removed_recovery
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


@removed_recovery
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


@removed_recovery
@pytest.mark.asyncio
async def test_click_target_is_recovered_from_dom_for_search_task(monkeypatch):
    install_dom_mocks(monkeypatch)
    dom_page = DummyPage(
        url="https://ucf.edu",
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
    executor, _ = build_executor(response, page=dom_page)

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
    assert "Error Type: ambiguous_step" in log


@pytest.mark.asyncio
async def test_prompt_uses_real_interactive_dom_snapshot(monkeypatch):
    install_dom_mocks(monkeypatch)
    page = DummyPage(
        url="https://ucf.edu",
        elements=[
            {"role": "textbox", "name": "Search site"},
            {"role": "link", "name": "Academics"},
        ],
    )

    response = ExecutionResult(
        action="wait",
        args=ExecutionArgs(seconds=0.1),
        status="success",
        error_type="none",
        message="Wait briefly.",
    )
    llm = DummyLLM(response)
    executor, _ = build_executor(response, page=page, llm=llm)

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

    # Both the tool-call attempt and the structured fallback must see the snapshot.
    assert llm.tool_messages is not None
    assert llm.messages is not None
    for messages in (llm.tool_messages, llm.messages):
        human_message = messages[1].content
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

    # Phase 3 removed the site-specific listing heuristic so section numbers are
    # stable across every page shape, not special-cased for one travel DOM.
    assert budget == 3500


def test_recovery_screenshot_capture_gate_requires_retry_or_high_signal_error():
    should_capture = Executor._should_capture_recovery_screenshot(
        state={"step_attempts": 0, "stall_cycles": 0},
        result_status="failure",
        result_error_type="execution_failure",
    )
    assert should_capture is False

    should_capture_retry = Executor._should_capture_recovery_screenshot(
        state={"step_attempts": 1, "stall_cycles": 0},
        result_status="failure",
        result_error_type="execution_failure",
    )
    assert should_capture_retry is True

    should_capture_blocked = Executor._should_capture_recovery_screenshot(
        state={"step_attempts": 0, "stall_cycles": 0},
        result_status="failure",
        result_error_type="navigation_blocked",
    )
    assert should_capture_blocked is True


def test_build_recovery_screenshot_meta_tracks_freshness_fields():
    meta = Executor._build_recovery_screenshot_meta(
        state={"current_step_index": 3, "step_attempts": 2},
        transaction_index=18,
        result_status="failure",
        result_error_type="navigation_blocked",
        action="click",
    )

    assert meta["transaction_index"] == 18
    assert meta["step_index"] == 3
    assert meta["step_attempts"] == 2
    assert meta["status"] == "failure"
    assert meta["error_type"] == "navigation_blocked"
    assert meta["action"] == "click"
    assert meta["capture_mode"] == "fallback_last_resort"
