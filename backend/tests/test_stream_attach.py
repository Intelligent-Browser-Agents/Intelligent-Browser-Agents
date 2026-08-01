"""
CDP attach tests for the live browser view.

The debugging port starts accepting connections as soon as Chromium boots, which
is before `src/app.py` calls `new_context()` / `new_page()`. The server attached
on the first successful TCP connect and did `browser.contexts[0].pages[0]`, which
raised `IndexError: list index out of range` whenever it won that race, costing
the run its live view.

Separately, a failed port probe used to fall straight through to cleanup, which
closed the WebSocket and terminated an otherwise healthy agent run.
"""

import asyncio
import inspect

import pytest

import server


async def _sleep_then(coro_factory, delay):
    await asyncio.sleep(delay)
    return await coro_factory()


@pytest.mark.browser
async def test_attach_waits_for_a_page_that_appears_late():
    """Reproduces the original race: attach before the agent opens its page."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, args=["--remote-debugging-port=9231"]
        )
        try:
            async def open_page():
                context = await browser.new_context()
                return await context.new_page()

            # The page only exists after 1.5s; the attach starts immediately.
            late = asyncio.create_task(_sleep_then(open_page, 1.5))

            attached_browser, context, page = await server.attach_to_agent_page(
                p, 9231, timeout=20
            )
            await late

            assert page is not None, "attach gave up before the agent's page appeared"
            assert context is not None
            # Proves the handle is usable, which is what the old IndexError prevented.
            client = await context.new_cdp_session(page)
            await client.send("Page.startScreencast", {"format": "jpeg", "quality": 40})
            await client.send("Page.stopScreencast")
        finally:
            await browser.close()


@pytest.mark.browser
async def test_attach_finds_a_page_that_already_exists():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, args=["--remote-debugging-port=9232"]
        )
        try:
            context = await browser.new_context()
            await context.new_page()
            _, ctx, page = await server.attach_to_agent_page(p, 9232, timeout=20)
            assert page is not None
            assert ctx is not None
        finally:
            await browser.close()


async def test_attach_gives_up_cleanly_when_nothing_is_listening():
    """Must return a None triple rather than raising, so the run survives."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        result = await server.attach_to_agent_page(p, 9899, timeout=1.0)
        assert result == (None, None, None)


def test_regression_no_unguarded_index_into_contexts_or_pages():
    """`contexts[0]` / `pages[0]` must not reappear in the stream handler."""
    source = inspect.getsource(server.stream_endpoint)
    assert "contexts[0]" not in source
    assert "pages[0]" not in source
    assert "attach_to_agent_page" in source


def test_regression_missing_debug_port_does_not_kill_the_run():
    """A failed port probe used to close the socket and terminate the agent."""
    source = inspect.getsource(server.stream_endpoint)
    # The no-port branch must keep waiting on the process instead of falling through.
    assert "Debug port" in source
    branch = source.split("Debug port", 1)[1]
    assert "_wait_for_process_or_disconnect" in branch


def test_stream_view_unavailable_keeps_the_socket_open():
    source = inspect.getsource(server.stream_endpoint)
    assert "except StreamViewUnavailable:" in source
    handler = source.split("except StreamViewUnavailable:", 1)[1]
    # The agent keeps running; only the video is gone.
    assert "_wait_for_process_or_disconnect" in handler.split("except NotImplementedError")[0]


def test_stream_logs_why_it_ended():
    """Silent closes were undiagnosable from the server log."""
    source = inspect.getsource(server.stream_endpoint)
    assert "exit_reason" in source
    for reason in ("agent process exited", "client disconnected", "handler returned"):
        assert reason in source
