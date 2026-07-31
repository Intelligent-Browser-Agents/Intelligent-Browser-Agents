"""
Shared pytest fixtures.

Two things happen here:

1. `page` provides a headless Chromium page for tests marked `browser`.
2. `_stub_models` replaces the LLM factory with deterministic stubs for every test
   that is *not* marked `llm`, so the default suite runs offline and free. Without
   this, importing an agent is enough to require a provider API key, because
   `Models.<agent>()` resolves the key at construction time.
"""

from __future__ import annotations

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def page():
    """A fresh headless Chromium page per test.

    Deliberately function-scoped: a shared page leaks cookies, history, and
    dialog handlers between tests, and these are integration tests where that
    cross-talk is hard to debug. Costs roughly 2.5s per test.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        new_page = await context.new_page()
        try:
            yield new_page
        finally:
            await context.close()
            await browser.close()


# ---------------------------------------------------------------------------
# Deterministic LLM stubs
# ---------------------------------------------------------------------------

def _stub_for_schema(schema):
    """Build a minimal valid instance of an agent output schema.

    Values are intentionally neutral. A test that depends on a *particular*
    model judgement should be marked `llm` rather than tuned against these.
    """
    name = getattr(schema, "__name__", "")

    if name == "OrchestratorPlan":
        return schema(
            needs_clarification=False,
            clarifying_questions=[],
            goal="stubbed goal",
            steps=["stubbed step 1", "stubbed step 2", "stubbed step 3"],
        )
    if name == "OrchestratorDecision":
        return schema(reasoning="stubbed reasoning", action="advance", task_refinement=None)
    if name == "ExecutionResult":
        # extract_content is the only action with no required args, so this is the
        # one shape guaranteed to pass ExecutionResult's model_validator.
        args_cls = schema.model_fields["args"].annotation
        return schema(
            action="extract_content",
            args=args_cls(),
            status="success",
            error_type="none",
            message="stubbed execution",
        )
    if name == "VerificationResult":
        return schema(
            verdict="success",
            step_complete=True,
            goal_complete=False,
            error_type="none",
            message="stubbed verification",
            handoff="orchestration",
        )
    if name == "FallbackStrategy":
        return schema(
            update_type="revise_step",
            diagnosis="stubbed diagnosis",
            proposed_step="stubbed revised step",
            insert_step=None,
            requested_context=[],
            message_to_orchestration="stubbed instruction",
        )
    if name == "InteractionResponse":
        return schema(
            type="finish",
            message="stubbed user-facing message",
            data=None,
            requested_fields=[],
        )

    raise AssertionError(
        f"No LLM stub registered for schema {name!r}. Add one to "
        "_stub_for_schema, or mark the test with @pytest.mark.llm."
    )


class _StubLLM:
    """Stands in for a LangChain chat model, with or without structured output."""

    def __init__(self, schema=None):
        self._schema = schema
        self.calls: list = []

    def invoke(self, messages, *args, **kwargs):
        self.calls.append(messages)
        if self._schema is None:
            from langchain_core.messages import AIMessage

            return AIMessage(content="stubbed response")
        return _stub_for_schema(self._schema)

    async def ainvoke(self, messages, *args, **kwargs):
        return self.invoke(messages, *args, **kwargs)

    def bind_tools(self, _tools, **_kwargs):
        # No tool_calls on the response, which routes the executor down its
        # structured-output path. That path is deterministic and testable.
        return self

    def with_structured_output(self, schema, **_kwargs):
        return _StubLLM(schema)

    def get_num_tokens_from_messages(self, _messages, **_kwargs):
        return 0


@pytest.fixture(autouse=True)
def _stub_models(request, monkeypatch):
    """Patch the LLM factory unless the test is marked `llm`."""
    if request.node.get_closest_marker("llm"):
        return None

    import models

    def fake_get_llm(schema=None, temperature=0.3, model_key="stub"):
        return _StubLLM(schema)

    monkeypatch.setattr(models, "get_llm", fake_get_llm)
    return fake_get_llm
