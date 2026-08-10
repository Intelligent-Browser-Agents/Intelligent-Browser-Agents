"""The read_page feedback loop and the verbatim-repeat guard.

Regression tests for the Apple-careers failure run (8975c575): read_page output
vanished before the next executor turn, so the model read the same section five
times and the run burned its transaction budget without acting.
See docs/issues/executor-page-visibility-loop.md.
"""

import pytest
from langchain_core.messages import AIMessage

import agents.executor as executor_module
from agents.executor import Executor
from execution.models import ActionArgs, ExecutionOutput


class _DummyLocator:
    async def aria_snapshot(self, **_kwargs):
        return '- textbox "Search site"'


class _DummyFrame:
    def __init__(self, url: str):
        self.url = url

    def locator(self, _selector):
        return _DummyLocator()

    async def evaluate(self, _js, *_args):
        return []


class _DummyContext:
    def __init__(self, page):
        self.pages = [page]


class DummyPage:
    """Stands in for a Playwright Page across the executor's access patterns."""

    def __init__(self, url: str = "https://jobs.example.com/search"):
        self.url = url
        self.main_frame = _DummyFrame(url)
        self.frames = [self.main_frame]
        self.context = _DummyContext(self)

    async def screenshot(self, **_kwargs):
        return b""


def make_state(task: str = "Open one Software Engineer posting.") -> dict:
    return {
        "messages": [{"role": "user", "content": "apply to a software engineer role"}],
        "current_task": task,
        "current_url": "https://jobs.example.com/search",
        "number_of_transactions": 1,
    }


SECTION_2 = (
    "[page snapshot: section 2 of 5, elements 61-101 of 224]\n"
    '[ref=e95] [role="heading"] "Software Engineer - Apple Services 200676478"\n'
    '[ref=e96] [role="link"] "Software Engineer - Apple Services 200676478"'
)


def _read_page_output(section: int = 2) -> ExecutionOutput:
    return ExecutionOutput(
        action="read_page",
        args={"section": section},
        status="success",
        error_type="none",
        message=f"Section {section} of 5 (224 elements total).",
        execution_time_ms=5,
        verified=True,
        extracted_text=SECTION_2,
    )


def _executor_for_finish(page: DummyPage) -> Executor:
    executor = Executor.__new__(Executor)
    executor.runtime = {"page": page, "pages_before_action": [page]}
    executor._secret_values = ()
    return executor


# ---------------------------------------------------------------------------
# read_page output must flow forward, and must stay out of the report pipeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_page_section_becomes_the_page_evidence():
    page = DummyPage()
    executor = _executor_for_finish(page)

    out = await executor._finish_from_result(make_state(), page, page.url, _read_page_output())

    assert out["last_page_snapshot"] == SECTION_2
    assert SECTION_2.splitlines()[1] in out["reasoning_log"][0]
    # Raw DOM rows are working context, not report material.
    assert "extracted_content" not in out


@pytest.mark.asyncio
async def test_extract_content_still_feeds_the_report_pipeline():
    page = DummyPage()
    executor = _executor_for_finish(page)
    result = ExecutionOutput(
        action="extract_content",
        args={"max_chars": 15000},
        status="success",
        error_type="none",
        message="Extracted page text.",
        execution_time_ms=5,
        verified=True,
        extracted_text="The role requires five years of Swift experience.",
    )

    out = await executor._finish_from_result(make_state(), page, page.url, result)

    assert out["extracted_content"] == ["The role requires five years of Swift experience."]


def test_read_section_block_present_after_read_page():
    state = make_state()
    state["last_execution_event"] = {
        "action": "read_page",
        "args": {"section": 2},
        "status": "success",
        "message": "Section 2 of 5.",
    }
    state["last_page_snapshot"] = SECTION_2

    block = Executor._build_read_section_context(state, dom_snapshot='[ref=e1] [role="link"] "Store"')

    assert "PAGE_SECTION_JUST_READ" in block
    assert "Software Engineer - Apple Services" in block


def test_read_section_block_skipped_when_snapshot_already_shows_it():
    state = make_state()
    state["last_execution_event"] = {
        "action": "read_page",
        "args": {"section": 2},
        "status": "success",
        "message": "Section 2 of 5.",
    }
    state["last_page_snapshot"] = SECTION_2

    assert Executor._build_read_section_context(state, dom_snapshot=SECTION_2) == ""


def test_read_section_block_absent_after_other_actions():
    state = make_state()
    state["last_execution_event"] = {
        "action": "click",
        "args": {"role": "link", "name": "Search Roles"},
        "status": "success",
        "message": "Clicked.",
    }
    state["last_page_snapshot"] = SECTION_2

    assert Executor._build_read_section_context(state, dom_snapshot="") == ""


# ---------------------------------------------------------------------------
# Verbatim-repeat guard for read-only discovery actions
# ---------------------------------------------------------------------------

def _state_after_read_page(section: int = 2) -> dict:
    state = make_state()
    state["last_execution_event"] = {
        "action": "read_page",
        "args": {"section": section},
        "status": "success",
        "message": f"Section {section} of 5.",
    }
    return state


def test_repeat_guard_blocks_identical_read_page():
    message = Executor._repeated_readonly_call(_state_after_read_page(2), "read_page", {"section": 2})
    assert message is not None
    assert "PAGE_SECTION_JUST_READ" in message


def test_repeat_guard_allows_a_different_section():
    assert Executor._repeated_readonly_call(_state_after_read_page(2), "read_page", {"section": 3}) is None


def test_repeat_guard_defaults_missing_section_to_one():
    assert Executor._repeated_readonly_call(_state_after_read_page(1), "read_page", {}) is not None


def test_repeat_guard_ignores_failed_previous_calls():
    state = _state_after_read_page(2)
    state["last_execution_event"]["status"] = "failure"
    assert Executor._repeated_readonly_call(state, "read_page", {"section": 2}) is None


def test_repeat_guard_never_touches_state_changing_actions():
    state = make_state()
    state["last_execution_event"] = {
        "action": "scroll",
        "args": {"direction": "down"},
        "status": "success",
        "message": "Scrolled.",
    }
    assert Executor._repeated_readonly_call(state, "scroll", {"direction": "down"}) is None


class _ToolCallLLM:
    """bind_tools() wrapper that answers with a fixed tool call."""

    def __init__(self, name: str, args: dict):
        self._call = {"name": name, "args": args, "id": "call_1", "type": "tool_call"}

    def bind_tools(self, _tools, **_kwargs):
        return self

    async def ainvoke(self, _messages, *_args, **_kwargs):
        return AIMessage(content="", tool_calls=[self._call])


@pytest.mark.asyncio
async def test_repeated_read_page_is_rejected_before_touching_the_page(monkeypatch):
    async def fake_get_page_text(page, max_chars: int = 3500):
        return "Careers"

    monkeypatch.setattr(executor_module.dom_extractor, "get_page_text", fake_get_page_text)

    page = DummyPage()
    llm = _ToolCallLLM("read_page", {"section": 2})
    executor = Executor.__new__(Executor)
    executor.runtime = {"page": page}
    executor.system_prompt_json = "Test execution prompt"
    executor.system_prompt_tools = "Test execution tools prompt"
    executor.llm_chat = llm
    executor.llm_structured = llm

    state = _state_after_read_page(2)
    out = await executor(state)
    log = out["reasoning_log"][0]

    assert "[Executor] Status: failure" in log
    assert "Error Type: repeated_action" in log
    assert out["last_execution_event"]["action"] == "read_page"


# ---------------------------------------------------------------------------
# fill(press_enter=True)
# ---------------------------------------------------------------------------

class _EnterLocator:
    def __init__(self, page):
        self._page = page
        self.pressed = []

    async def press(self, key, **_kwargs):
        self.pressed.append(key)
        self._page.url = "https://jobs.example.com/search?search=software+engineer"


class _EnterPage:
    def __init__(self):
        self.url = "https://jobs.example.com/search"

    async def wait_for_load_state(self, *_args, **_kwargs):
        return None


@pytest.mark.asyncio
async def test_commit_with_enter_presses_on_the_field_and_reports_navigation():
    from execution.actions import _commit_with_enter

    page = _EnterPage()
    locator = _EnterLocator(page)

    suffix = await _commit_with_enter(page, locator)

    assert locator.pressed == ["Enter"]
    assert "navigated to https://jobs.example.com/search?search=software+engineer" in suffix


def test_action_args_accept_press_enter():
    args = ActionArgs(role="textbox", name="Search", text="software engineer", press_enter=True)
    assert args.press_enter is True
