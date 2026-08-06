import { useEffect, useRef, useState } from "react";
import "./LiveView.css";

// CDP modifier bitmask: Alt=1, Ctrl=2, Meta=4, Shift=8.
const modifiersOf = (e) =>
  (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0);

const MOUSE_BUTTONS = { 0: "left", 1: "middle", 2: "right" };
const MOUSE_MOVE_MIN_INTERVAL_MS = 33;

/**
 * The live browser view.
 *
 * Frames arrive as BINARY WebSocket messages (raw JPEG) and are painted onto a
 * canvas via createImageBitmap, held in refs the whole way: a frame never
 * touches React state, so streaming does not re-render the Dashboard (the old
 * data-URL-in-state approach re-rendered the entire page per frame and re-ran
 * an O(n) log reduce).
 *
 * Geometry comes from the server's {"type": "VIEWPORT"} message, not a
 * hardcoded 1280x720. Coordinates map against the canvas itself (it has the
 * frame's aspect ratio, so getBoundingClientRect is the drawn area) and are
 * clamped on both ends.
 *
 * The user can take over at ANY time while a run is live, not only during a
 * HITL pause: clicking the view captures the mouse and keyboard, Escape (or
 * leaving the view) releases the keyboard. This is the escape hatch for
 * CAPTCHAs and widgets the agent cannot drive.
 */
export default function LiveView({ socketRef, runActive, onStreamChange }) {
  const canvasRef = useRef(null);
  const viewportRef = useRef({ width: 1280, height: 720 });
  const decodingRef = useRef(false);
  const pendingFrameRef = useRef(null);
  const hasFrameRef = useRef(false);
  const lastMoveSentRef = useRef(0);
  const [captured, setCaptured] = useState(false);
  const runActiveRef = useRef(runActive);
  runActiveRef.current = runActive;

  const sendInput = (payload) => {
    const socket = socketRef.current;
    if (runActiveRef.current && socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "INPUT", ...payload }));
    }
  };

  // ── frame pipeline ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!runActive) return undefined;
    const socket = socketRef.current;
    if (!socket) return undefined;
    socket.binaryType = "arraybuffer";

    const drawFrame = async (buffer) => {
      // Newest frame wins on the client too: while a decode is in flight,
      // remember only the latest buffer and drop the rest.
      if (decodingRef.current) {
        pendingFrameRef.current = buffer;
        return;
      }
      decodingRef.current = true;
      try {
        let current = buffer;
        while (current) {
          const bitmap = await createImageBitmap(
            new Blob([current], { type: "image/jpeg" })
          );
          const canvas = canvasRef.current;
          if (canvas) {
            if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
              canvas.width = bitmap.width;
              canvas.height = bitmap.height;
            }
            canvas.getContext("2d").drawImage(bitmap, 0, 0);
          }
          bitmap.close();
          if (!hasFrameRef.current) {
            hasFrameRef.current = true;
            onStreamChange?.(true);
          }
          current = pendingFrameRef.current;
          pendingFrameRef.current = null;
        }
      } catch {
        // A corrupt frame must not kill the pipeline; the next one repaints.
      } finally {
        decodingRef.current = false;
      }
    };

    const onMessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        drawFrame(event.data);
        return;
      }
      if (typeof event.data === "string") {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "VIEWPORT" && msg.width > 0 && msg.height > 0) {
            viewportRef.current = { width: msg.width, height: msg.height };
          }
        } catch {
          // JSON routing belongs to the Dashboard's own handler.
        }
      }
    };

    socket.addEventListener("message", onMessage);
    return () => socket.removeEventListener("message", onMessage);
  }, [socketRef, runActive, onStreamChange]);

  // A new run streams fresh: report the first frame of each run, and release
  // the keyboard when the run ends. The previous run's last frame stays on
  // the canvas until the new run paints, so a finished run leaves evidence.
  useEffect(() => {
    if (runActive) {
      hasFrameRef.current = false;
      pendingFrameRef.current = null;
      onStreamChange?.(false);
    } else {
      setCaptured(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runActive]);

  // ── coordinate mapping ─────────────────────────────────────────────────
  const mapCoords = (e) => {
    const canvas = canvasRef.current;
    const { width, height } = viewportRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return { x: 0, y: 0 };
    const x = Math.round(((e.clientX - rect.left) / rect.width) * width);
    const y = Math.round(((e.clientY - rect.top) / rect.height) * height);
    return {
      x: Math.min(Math.max(x, 0), Math.max(width - 1, 0)),
      y: Math.min(Math.max(y, 0), Math.max(height - 1, 0)),
    };
  };

  // ── mouse ──────────────────────────────────────────────────────────────
  const handleMouseDown = (e) => {
    canvasRef.current?.focus();
    setCaptured(true);
    e.preventDefault();
    sendInput({
      inputType: "mouse",
      action: "mousePressed",
      ...mapCoords(e),
      button: MOUSE_BUTTONS[e.button] || "left",
      clickCount: Math.max(1, e.detail),
      buttons: e.buttons,
      modifiers: modifiersOf(e),
    });
  };

  const handleMouseUp = (e) => {
    e.preventDefault();
    sendInput({
      inputType: "mouse",
      action: "mouseReleased",
      ...mapCoords(e),
      button: MOUSE_BUTTONS[e.button] || "left",
      clickCount: Math.max(1, e.detail),
      buttons: e.buttons,
      modifiers: modifiersOf(e),
    });
  };

  const handleMouseMove = (e) => {
    // Hover states and drags both need moves; throttle so a fast mouse does
    // not flood the socket.
    const now = performance.now();
    if (now - lastMoveSentRef.current < MOUSE_MOVE_MIN_INTERVAL_MS) return;
    lastMoveSentRef.current = now;
    sendInput({
      inputType: "mouse",
      action: "mouseMoved",
      ...mapCoords(e),
      button: MOUSE_BUTTONS[e.button] || "none",
      buttons: e.buttons,
      modifiers: modifiersOf(e),
    });
  };

  // ── keyboard ───────────────────────────────────────────────────────────
  const handleKeyDown = (e) => {
    if (e.key === "Escape") {
      // Escape releases the capture instead of being swallowed forever.
      setCaptured(false);
      canvasRef.current?.blur();
      return;
    }
    e.preventDefault();
    const isPrintable = e.key.length === 1;
    const base = {
      inputType: "key",
      key: e.key,
      code: e.code,
      keyCode: e.keyCode,
      modifiers: modifiersOf(e),
    };
    sendInput({ ...base, action: isPrintable ? "keyDown" : "rawKeyDown" });
    if (isPrintable) {
      // The char event carries the text; keyCode stays the real virtual key
      // code (the old path sent charCodeAt(0), which is a character code and
      // broke non-letter keys).
      sendInput({ ...base, action: "char", text: e.key, unmodifiedText: e.key });
    }
  };

  const handleKeyUp = (e) => {
    if (e.key === "Escape") return;
    e.preventDefault();
    sendInput({
      inputType: "key",
      action: "keyUp",
      key: e.key,
      code: e.code,
      keyCode: e.keyCode,
      modifiers: modifiersOf(e),
    });
  };

  // ── wheel (attached manually: React root wheel listeners are passive, so
  //    preventDefault would be ignored and the page would scroll too) ─────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const onWheel = (e) => {
      e.preventDefault();
      const point = mapCoords(e);
      sendInput({
        inputType: "scroll",
        ...point,
        deltaX: e.deltaX,
        deltaY: e.deltaY,
        modifiers: modifiersOf(e),
      });
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className={`live-view${captured ? " live-view-captured" : ""}${runActive ? " live-view-running" : ""}`}>
      <canvas
        ref={canvasRef}
        className="browser-frame live-view-canvas"
        width={1280}
        height={720}
        tabIndex={runActive ? 0 : -1}
        aria-label="Live browser view. Click to take over; press Escape to release."
        onMouseDown={runActive ? handleMouseDown : undefined}
        onMouseUp={runActive ? handleMouseUp : undefined}
        onMouseMove={runActive ? handleMouseMove : undefined}
        onKeyDown={runActive ? handleKeyDown : undefined}
        onKeyUp={runActive ? handleKeyUp : undefined}
        onContextMenu={(e) => e.preventDefault()}
        onBlur={() => setCaptured(false)}
      />
      {runActive && (
        <div className="live-view-hint" aria-hidden="true">
          {captured ? "Keyboard captured - Esc to release" : "Click to take over"}
        </div>
      )}
    </div>
  );
}
