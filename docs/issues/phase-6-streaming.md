# Issue: Phase 6 - streaming and the live view (and the Windows no-video bug)

Status: **closed** (implemented 2026-08-05)
Branch: `Edwin-after-grad`
Opened: 2026-08-05
Plan reference: `docs/IMPROVEMENT_PLAN.md`, Phase 6

Closed with: the raw-CDP relay (`backend/cdp_stream.py`), binary frames + VIEWPORT + newest-frame-wins, the canvas LiveView component with takeover-any-time, and the acceptance evidence below.
The interim "run without --reload" workaround is obsolete.
Verification on the previously failing machine and server invocation: the scripted probe received VIEWPORT plus binary JPEG frames with `frames_received == frames_sent == acks_sent` (loss-free pipeline); the dashboard canvas painted real page pixels; click-to-capture and Escape-to-release verified in the running UI; suite and lint green.
Two bugs found during verification are recorded in the plan doc's Phase 6 notes (ack deadlock, everyNthFrame starvation), plus one refuted hypothesis (screencast survives navigation; no restart needed).

## The Windows bug, reproduced and diagnosed

Report: the live stream works on macOS and shows nothing on Windows.

Reproduced on Windows against the locally running server (started with the README's own command, `uvicorn server:app ... --reload`): a scripted client drove `/ws/stream` exactly like the frontend and received `STATUS: Video streaming not available on this platform; continuing with logs only.` and **zero FRAME messages**, while 137 log lines and the final response streamed normally.

Causal chain, each step verified:

1. uvicorn 0.42.0 on win32 selects `SelectorEventLoop` whenever it runs under the reloader (`asyncio_loop_factory(use_subprocess=True)`), and `ProactorEventLoop` otherwise.
2. `async_playwright()` starts the Playwright driver with `asyncio.create_subprocess_exec`, which `SelectorEventLoop` does not implement on Windows (probe: `_WindowsSelectorEventLoop: NotImplementedError`, `ProactorEventLoop: OK`).
3. `server.py` catches `NotImplementedError` and downgrades to logs-only, so the failure is silent apart from one status line.
4. macOS selector loops support subprocesses, so the identical command works there.

Interim workaround: run the backend without `--reload` on Windows.

## Why the fix is the Phase 6 rebuild

The server uses Playwright only to attach to the agent's browser and relay screencast frames and input events.
All of that is a thin layer over CDP's JSON protocol, reachable over a plain WebSocket client (`websockets`, already a dependency), which needs no subprocess and works on every event loop.
Removing Playwright from the server's streaming path fixes Windows structurally (no interpreter-level dependency on loop type), removes one Playwright driver process per run, and is the same code the rest of Phase 6 has to touch anyway.

## What

1. **Backend: raw-CDP streaming relay** (`backend/cdp_stream.py`):
   - discover the agent page via `http://127.0.0.1:{port}/json/list`, connect to its `webSocketDebuggerUrl`;
   - `Page.startScreencast` with `maxWidth`/`maxHeight`/`everyNthFrame` bounds;
   - forward frames as **binary WebSocket messages** (no base64-in-JSON), keeping only the newest frame when the client is behind;
   - send a JSON `VIEWPORT` message with the real frame dimensions (from screencast metadata) on start and on change;
   - on page switch, close the old CDP connection and attach to the new target (no leaked sessions);
   - relay `Input.dispatchMouseEvent` / `Input.dispatchKeyEvent` from the frontend, including move/drag/hover, right-click, wheel, and modifiers.
2. **Deterministic viewport** in `src/app.py`'s `new_context()` so frame geometry stops depending on a Playwright default.
3. **Frontend: `LiveView` component**: render binary frames into a `<canvas>` via `createImageBitmap`, holding the frame in a ref so a frame never re-renders the Dashboard; use the `VIEWPORT` message for coordinate mapping with clamping on both sides; attach handlers to the canvas, not the padded wrapper.
4. **Keyboard**: scoped capture with Escape to release, correct `windowsVirtualKeyCode` handling, no unconditional `preventDefault`.
5. **Takeover at any time**, not only during HITL pauses.

## Acceptance

- The scripted stream probe on this Windows machine, with the server running under `--reload`, receives binary frames within seconds of the browser starting (the exact setup that failed before the fix).
- A sustained run holds a stable frame rate with the log panel responsive; a takeover click lands within a few pixels at any panel size.
- Suite and eslint green.
