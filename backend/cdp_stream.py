"""Raw-CDP live-view relay.

The server used to attach to the agent's Chromium through Playwright. That was
the Windows no-video bug: Playwright's driver is a subprocess, uvicorn under
--reload on Windows runs a SelectorEventLoop, and SelectorEventLoop cannot
spawn subprocesses, so the attach died with NotImplementedError while the agent
ran fine (docs/issues/phase-6-streaming.md). CDP is just JSON over a WebSocket;
speaking it directly needs no subprocess, works on every event loop, and drops
one Playwright driver process per run.

The relay also carries the Phase 6 streaming contract:

- screencast bounded by max_width / max_height / every_nth_frame;
- frames forwarded to the frontend as BINARY WebSocket messages (raw JPEG,
  no base64-in-JSON), and only the newest frame is sent when the client is
  behind - frames are acked on receipt so Chromium keeps producing, and the
  sender task ships whatever is freshest;
- a JSON ``{"type": "VIEWPORT", "width": W, "height": H}`` message announces
  the real frame geometry before the first frame and again whenever it
  changes, so the frontend never has to hardcode 1280x720;
- when the agent opens a new page (popup, new tab), the relay closes the old
  CDP connection and attaches to the new target - nothing leaks;
- frontend input events (mouse, key, wheel) are dispatched to the attached
  page, including move/drag, right-click, and modifiers, so a human can take
  over at any time.
"""

from __future__ import annotations

import asyncio
import base64
import itertools
import json
from typing import Awaitable, Callable, Optional

import httpx
import websockets


class CdpError(RuntimeError):
    """A CDP command returned an error response."""


class CdpConnection:
    """One WebSocket connection to a single CDP page target."""

    def __init__(self, ws) -> None:
        self._ws = ws
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._event_handlers: dict[str, Callable[[dict], Awaitable[None]]] = {}
        self._reader: Optional[asyncio.Task] = None
        self.closed = asyncio.Event()

    @classmethod
    async def connect(cls, ws_url: str) -> "CdpConnection":
        ws = await websockets.connect(
            ws_url,
            max_size=32 * 1024 * 1024,
            ping_interval=None,  # DevTools does not speak WS pings reliably
            close_timeout=2,
        )
        conn = cls(ws)
        conn._reader = asyncio.create_task(conn._read_loop())
        return conn

    def on(self, method: str, handler: Callable[[dict], Awaitable[None]]) -> None:
        self._event_handlers[method] = handler

    async def send(self, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
        msg_id = next(self._ids)
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = future
        try:
            await self._ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(msg_id, None)

    async def send_no_reply(self, method: str, params: dict | None = None) -> None:
        """Send a command without waiting for its response.

        Required for anything sent from inside an event handler: handlers run
        on the read loop, so awaiting a response there deadlocks until the
        timeout - the response could only be read by the loop the handler is
        blocking. The screencast ack is the canonical case.
        """
        await self._ws.send(json.dumps({"id": next(self._ids), "method": method, "params": params or {}}))

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if "id" in msg:
                    future = self._pending.get(msg["id"])
                    if future is not None and not future.done():
                        if "error" in msg:
                            future.set_exception(CdpError(str(msg["error"])))
                        else:
                            future.set_result(msg.get("result") or {})
                    continue
                handler = self._event_handlers.get(msg.get("method", ""))
                if handler is not None:
                    try:
                        await handler(msg.get("params") or {})
                    except Exception:
                        pass
        except Exception:
            pass
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(CdpError("connection closed"))
            self.closed.set()

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
        try:
            await self._ws.close()
        except Exception:
            pass
        self.closed.set()


async def list_page_targets(port: int) -> list[dict]:
    """Page targets from the DevTools HTTP endpoint.

    127.0.0.1 on purpose: `localhost` can resolve to ::1 on Windows while
    Chromium binds the debugging port on IPv4 only, and using the IP in the
    request also makes Chromium hand back webSocketDebuggerUrls that carry
    the IP rather than a hostname.
    """
    async with httpx.AsyncClient(timeout=3.0) as client:
        response = await client.get(f"http://127.0.0.1:{port}/json/list")
        response.raise_for_status()
        targets = response.json()
    return [
        t for t in targets
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl")
        and not str(t.get("url", "")).startswith("devtools://")
    ]


class ScreencastRelay:
    """Attach to the agent's page over raw CDP and relay frames and input.

    ``send_bytes`` / ``send_json`` are the frontend-socket senders. They are
    only ever called from this relay's own tasks; a send failure sets
    ``send_failed`` so the owner can react (the stream socket is gone).
    """

    def __init__(
        self,
        port: int,
        send_bytes: Callable[[bytes], Awaitable[None]],
        send_json: Callable[[dict], Awaitable[None]],
        max_width: int = 1280,
        max_height: int = 720,
        # 1 = every compositor frame. Backpressure is handled by newest-frame-
        # wins in the sender, not by skipping: a mostly-static page can go
        # seconds between compositor commits, and with N>1 the single frame a
        # static page produces on screencast start never arrives at all.
        every_nth_frame: int = 1,
        quality: int = 55,
    ) -> None:
        self._port = port
        self._send_bytes = send_bytes
        self._send_json = send_json
        self._max_width = max_width
        self._max_height = max_height
        self._every_nth_frame = every_nth_frame
        self._quality = quality

        self._conn: Optional[CdpConnection] = None
        self._attached_target_id: Optional[str] = None
        self._known_target_ids: set[str] = set()

        self._latest_frame: Optional[bytes] = None
        self._frame_ready = asyncio.Event()
        self._viewport: tuple[int, int] = (0, 0)

        self._tasks: list[asyncio.Task] = []
        self.send_failed = asyncio.Event()
        self.first_frame_sent = asyncio.Event()

        # Pipeline counters, reported over the stream as STREAM_STATS. When a
        # live view misbehaves in the field, these say WHERE it stopped:
        # frames_received small = Chromium is not producing; received large but
        # sent small = the sender or the frontend socket is the bottleneck.
        self.stats = {"frames_received": 0, "frames_sent": 0, "acks_sent": 0, "attaches": 0}

    @property
    def latest_frame(self) -> Optional[bytes]:
        """The newest JPEG received; the run's final frame once it ends."""
        return self._latest_frame

    # ── lifecycle ────────────────────────────────────────────────────────

    async def start(self, timeout: float = 25.0) -> bool:
        """Discover the agent page and start streaming. False if it never appears."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            try:
                targets = await list_page_targets(self._port)
            except Exception:
                targets = []
            if targets:
                try:
                    await self._attach(targets[0])
                except Exception:
                    await asyncio.sleep(0.5)
                    continue
                self._known_target_ids = {t.get("id") for t in targets}
                self._tasks.append(asyncio.create_task(self._sender_loop()))
                self._tasks.append(asyncio.create_task(self._target_watcher()))
                self._tasks.append(asyncio.create_task(self._stats_reporter()))
                return True
            await asyncio.sleep(0.25)
        return False

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ── attachment and page switching ────────────────────────────────────

    async def _attach(self, target: dict) -> None:
        """Connect to a page target and start its screencast, replacing any
        previous connection (the old CDP session is closed, not leaked)."""
        old = self._conn
        self.stats["attaches"] += 1
        conn = await CdpConnection.connect(target["webSocketDebuggerUrl"])
        conn.on("Page.screencastFrame", self._on_frame)
        await conn.send("Page.enable")
        await conn.send("Page.startScreencast", {
            "format": "jpeg",
            "quality": self._quality,
            "maxWidth": self._max_width,
            "maxHeight": self._max_height,
            "everyNthFrame": self._every_nth_frame,
        })
        self._conn = conn
        self._attached_target_id = target.get("id")
        if old is not None:
            await old.close()

    async def _target_watcher(self) -> None:
        """Follow the agent across pages.

        A target id we have never seen means the agent opened a new page
        (popup, OAuth window, new tab): attach to it. If the attached target
        disappears or its connection drops, fall back to any surviving page.
        """
        while True:
            await asyncio.sleep(1.5)
            try:
                targets = await list_page_targets(self._port)
            except Exception:
                continue
            current_ids = {t.get("id") for t in targets}

            fresh = [t for t in targets if t.get("id") not in self._known_target_ids]
            self._known_target_ids = current_ids

            attached_alive = (
                self._attached_target_id in current_ids
                and self._conn is not None
                and not self._conn.closed.is_set()
            )

            pick = None
            if fresh:
                pick = fresh[0]
            elif not attached_alive and targets:
                pick = targets[0]

            if pick is not None and pick.get("id") != (self._attached_target_id if attached_alive else None):
                try:
                    await self._attach(pick)
                except Exception:
                    pass

    # ── frames ───────────────────────────────────────────────────────────

    async def _on_frame(self, params: dict) -> None:
        conn = self._conn
        session_id = params.get("sessionId")
        self.stats["frames_received"] += 1
        try:
            frame = base64.b64decode(params.get("data") or "")
        except Exception:
            frame = b""

        # Ack immediately so Chromium keeps producing; the sender ships only
        # the newest frame, which is where slow-client backpressure goes.
        # Fire-and-forget: this handler runs on the connection's read loop,
        # so awaiting the ack's response here would deadlock the stream.
        if conn is not None and session_id is not None:
            try:
                await conn.send_no_reply("Page.screencastFrameAck", {"sessionId": session_id})
                self.stats["acks_sent"] += 1
            except Exception:
                pass

        if not frame:
            return
        metadata = params.get("metadata") or {}
        width = int(metadata.get("deviceWidth") or 0)
        height = int(metadata.get("deviceHeight") or 0)
        if width and height and (width, height) != self._viewport:
            self._viewport = (width, height)
            try:
                await self._send_json({"type": "VIEWPORT", "width": width, "height": height})
            except Exception:
                self.send_failed.set()
                return

        self._latest_frame = frame
        self._frame_ready.set()

    async def _sender_loop(self) -> None:
        while True:
            await self._frame_ready.wait()
            self._frame_ready.clear()
            frame = self._latest_frame
            if frame is None:
                continue
            try:
                await self._send_bytes(frame)
                self.stats["frames_sent"] += 1
                self.first_frame_sent.set()
            except Exception:
                self.send_failed.set()
                return

    async def _stats_reporter(self, interval: float = 5.0) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await self._send_json({"type": "STREAM_STATS", **self.stats})
            except Exception:
                return

    # ── input ────────────────────────────────────────────────────────────

    async def dispatch_input(self, msg: dict) -> None:
        """Forward a frontend input event to the attached page.

        Coordinates arrive already mapped to viewport space by the frontend
        (it knows the real geometry from VIEWPORT); they are clamped here too
        so a stray event can never land outside the page.
        """
        conn = self._conn
        if conn is None:
            return
        width, height = self._viewport or (self._max_width, self._max_height)

        def clamp(value, upper):
            try:
                value = float(value)
            except (TypeError, ValueError):
                return 0
            return min(max(value, 0), upper if upper > 0 else value)

        try:
            input_type = msg.get("inputType")
            if input_type == "mouse":
                params = {
                    "type": msg.get("action", "mousePressed"),
                    "x": clamp(msg.get("x", 0), width),
                    "y": clamp(msg.get("y", 0), height),
                    "button": msg.get("button", "left"),
                    "clickCount": int(msg.get("clickCount", 1)),
                    "modifiers": int(msg.get("modifiers", 0)),
                }
                # `buttons` is the currently-pressed bitmask; needed for drags.
                if "buttons" in msg:
                    params["buttons"] = int(msg.get("buttons") or 0)
                await conn.send("Input.dispatchMouseEvent", params)
            elif input_type == "key":
                action = msg.get("action", "keyDown")
                key = msg.get("key", "")
                key_code = int(msg.get("keyCode", 0) or 0)
                params = {
                    "type": action,
                    "key": key,
                    "code": msg.get("code", ""),
                    "windowsVirtualKeyCode": key_code,
                    "nativeVirtualKeyCode": key_code,
                    "modifiers": int(msg.get("modifiers", 0)),
                }
                if action == "char":
                    params["text"] = msg.get("text", key)
                    params["unmodifiedText"] = msg.get("unmodifiedText", key)
                elif action in ("keyDown", "rawKeyDown"):
                    params["text"] = msg.get("text", "")
                await conn.send("Input.dispatchKeyEvent", params)
            elif input_type == "scroll":
                await conn.send("Input.dispatchMouseEvent", {
                    "type": "mouseWheel",
                    "x": clamp(msg.get("x", 0), width),
                    "y": clamp(msg.get("y", 0), height),
                    "deltaX": float(msg.get("deltaX", 0) or 0),
                    "deltaY": float(msg.get("deltaY", 0) or 0),
                    "modifiers": int(msg.get("modifiers", 0)),
                })
        except Exception as exc:
            print(f"[INPUT] CDP dispatch error: {type(exc).__name__}")
