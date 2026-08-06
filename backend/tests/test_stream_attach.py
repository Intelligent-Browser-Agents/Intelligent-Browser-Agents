"""Live-view relay tests.

Two generations of bugs are pinned here.

The original attach raced Chromium's boot: `browser.contexts[0].pages[0]`
raised IndexError when the debugging port opened before the agent's page
existed, and a failed port probe closed the WebSocket and killed a healthy run.

The second generation was the Windows no-video bug: the server attached with
Playwright, whose driver is a subprocess, and uvicorn under --reload on Windows
runs a SelectorEventLoop that cannot spawn subprocesses. The live view died
with NotImplementedError while the agent ran fine. The relay speaks raw CDP
over a WebSocket instead, which must work on ANY event loop
(docs/issues/phase-6-streaming.md).
"""

import asyncio
import inspect

import pytest

import server
from cdp_stream import ScreencastRelay


class _Collector:
    """Fake frontend socket: records binary frames and JSON messages."""

    def __init__(self) -> None:
        self.frames: list[bytes] = []
        self.messages: list[dict] = []
        self.first_frame = asyncio.Event()

    async def send_bytes(self, data: bytes) -> None:
        self.frames.append(data)
        self.first_frame.set()

    async def send_json(self, msg: dict) -> None:
        self.messages.append(msg)


async def _sleep_then(coro_factory, delay):
    await asyncio.sleep(delay)
    return await coro_factory()


@pytest.mark.browser
async def test_relay_streams_binary_frames_from_a_late_appearing_page():
    """Reproduces the original race: the relay starts before the agent opens
    its page, then must attach, announce VIEWPORT, and deliver binary JPEG."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, args=["--remote-debugging-port=9231"]
        )
        collector = _Collector()
        relay = ScreencastRelay(
            port=9231,
            send_bytes=collector.send_bytes,
            send_json=collector.send_json,
        )
        try:
            async def open_page():
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 720}
                )
                page = await context.new_page()
                await page.goto("data:text/html,<h1>stream me</h1>")
                return page

            late = asyncio.create_task(_sleep_then(open_page, 1.5))

            started = await relay.start(timeout=20)
            assert started, "relay gave up before the agent's page appeared"
            await late

            await asyncio.wait_for(collector.first_frame.wait(), timeout=15)
            # Binary JPEG, not base64-in-JSON: JPEG magic is FF D8.
            assert collector.frames[0][:2] == b"\xff\xd8"
            # The real geometry was announced before the first frame.
            viewports = [m for m in collector.messages if m.get("type") == "VIEWPORT"]
            assert viewports, "no VIEWPORT message before the first frame"
            assert viewports[0]["width"] > 0 and viewports[0]["height"] > 0

            # A STREAM, not a single frame. The first relay version deadlocked
            # on its own screencast ack (sent from the read loop, awaiting a
            # reply only that loop could deliver), which let exactly one frame
            # through and stalled - a static page hid it. Drive repaints and
            # require a sustained flow.
            page = await late
            for i in range(6):
                await page.evaluate(f"document.body.textContent = 'repaint {i}'")
                await asyncio.sleep(0.25)
            deadline = asyncio.get_event_loop().time() + 10
            while len(collector.frames) < 3 and asyncio.get_event_loop().time() < deadline:
                await page.evaluate("document.body.textContent += '.'")
                await asyncio.sleep(0.25)
            assert len(collector.frames) >= 3, (
                f"only {len(collector.frames)} frame(s) arrived; the stream stalled"
            )
        finally:
            await relay.close()
            await browser.close()


async def test_relay_gives_up_cleanly_when_nothing_is_listening():
    """Must return False rather than raising, so the run survives."""
    relay = ScreencastRelay(
        port=9899,
        send_bytes=lambda b: asyncio.sleep(0),
        send_json=lambda m: asyncio.sleep(0),
    )
    assert await relay.start(timeout=1.0) is False
    await relay.close()


def test_regression_relay_works_on_a_selector_event_loop():
    """The Windows bug: Playwright's attach needed asyncio subprocess support,
    which SelectorEventLoop lacks on Windows, so the live view silently died
    under `uvicorn --reload`. The raw-CDP relay must run on a selector loop
    without NotImplementedError; giving up on a dead port is fine."""
    loop = asyncio.SelectorEventLoop()
    try:
        relay = ScreencastRelay(
            port=9898,
            send_bytes=lambda b: asyncio.sleep(0),
            send_json=lambda m: asyncio.sleep(0),
        )
        started = loop.run_until_complete(relay.start(timeout=0.6))
        assert started is False
        loop.run_until_complete(relay.close())
    finally:
        loop.close()


def test_regression_server_does_not_import_playwright():
    """The stream path must never again depend on spawning a subprocess.
    Playwright in server.py is how the Windows no-video bug happened."""
    source = inspect.getsource(server)
    assert "async_playwright" not in source
    assert "from playwright" not in source


def test_regression_no_unguarded_index_into_contexts_or_pages():
    """`contexts[0]` / `pages[0]` must not reappear in the stream handler."""
    source = inspect.getsource(server.stream_endpoint)
    assert "contexts[0]" not in source
    assert "pages[0]" not in source
    assert "ScreencastRelay(" in source


def test_regression_missing_live_view_does_not_kill_the_run():
    """A failed attach used to close the socket and terminate the agent. The
    no-live-view branch must keep waiting on the process instead."""
    source = inspect.getsource(server.stream_endpoint)
    assert "No page target appeared" in source
    branch = source.split("No page target appeared", 1)[1]
    assert "Live browser view unavailable" in branch
    assert "_wait_for_process_or_disconnect" in branch


def test_stream_logs_why_it_ended():
    """Silent closes were undiagnosable from the server log."""
    source = inspect.getsource(server.stream_endpoint)
    assert "exit_reason" in source
    for reason in ("agent process exited", "client disconnected", "handler returned"):
        assert reason in source
