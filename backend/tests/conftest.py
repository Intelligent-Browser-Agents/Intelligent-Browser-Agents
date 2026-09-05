"""
Shared pytest fixtures.

Three things happen here:

1. `page` provides a headless Chromium page for tests marked `browser`.
2. `site` serves `tests/fixtures/` over local HTTP, so browser tests need a
   browser but never the network.
3. `_stub_models` replaces the LLM factory with deterministic stubs for every test
   that is *not* marked `llm`, so the default suite runs offline and free. Without
   this, importing an agent is enough to require a provider API key, because
   `Models.<agent>()` resolves the key at construction time.
"""

from __future__ import annotations

import functools
import http.server
import pathlib
import threading

import pytest
import pytest_asyncio

FIXTURE_ROOT = pathlib.Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Deterministic environment
# ---------------------------------------------------------------------------

# A valid Fernet key (32 url-safe base64-encoded bytes, decoding to the ASCII
# above) so it reads as obviously fake. The specific value does not matter here:
# only `test_server.py` needs a fixed one, because it asserts on ciphertext it
# produced earlier in the same run, and it sets its own.
_TEST_CREDENTIALS_KEY = "dGVzdC1vbmx5LWtleS1ub3QtYS1yZWFsLXNlY3JldCE="  # test-only-key-not-a-real-secret!


@pytest.fixture(autouse=True)
def _test_environment(monkeypatch):
    """Pin the secrets the server module reads, for every test.

    `server.py` calls `load_dotenv()`, so without this the suite silently
    inherits whatever is in the developer's repo-root `.env`. That made the
    result depend on the machine: `test_runs_and_documents.py` passed locally
    because a real `CREDENTIALS_KEY` happened to be exported, and failed on any
    clean checkout with `TypeError: Expected a string value` from Fernet(None).
    CI is exactly that clean checkout.

    `test_server.py` has its own fixture setting the same variables. That one
    stays: it also patches the mailer and clears the rate limiter, and its
    values win where both apply.
    """
    monkeypatch.setenv("TOKEN_SECRET", "testsecret-long-enough-for-hs256-abcdef")
    monkeypatch.setenv("CREDENTIALS_KEY", _TEST_CREDENTIALS_KEY)
    monkeypatch.setenv("EMAIL_ACCOUNT", "from@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "password")


# ---------------------------------------------------------------------------
# Fixture site
# ---------------------------------------------------------------------------

class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler without the per-request stderr line."""

    def log_message(self, *_args):
        pass


@pytest.fixture(scope="session")
def site():
    """Base URL of a local static server rooted at `tests/fixtures/`.

    Served over HTTP rather than addressed as `file://` because the fixture
    application spans several pages and embeds a same-origin iframe. Under
    `file://` Chromium treats every document as a unique opaque origin, so
    `contentDocument` on the iframe is unreachable and the frame walk cannot be
    tested at all.

    Session-scoped: the server is stateless, so there is nothing to leak between
    tests, and the per-test cost of binding a socket is not worth paying.
    """
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        functools.partial(_QuietHandler, directory=str(FIXTURE_ROOT)),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


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
            work_items=[],
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
