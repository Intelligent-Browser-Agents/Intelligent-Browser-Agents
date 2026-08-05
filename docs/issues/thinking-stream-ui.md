# Issue: Animated "thinking" view for live agent runs

Status: **closed** (implemented 2026-08-02)
Branch: `Edwin-after-grad`
Opened: 2026-08-02

## Why

While a run is in flight, the dashboard shows raw stdout lines in the Agent Logs panel.
That is faithful but hard to read: node banners, `Plan Status:` fields, and bracket-tagged agent entries all land with equal weight.
ChatGPT and Claude ship a "thinking" surface that streams a readable narrative of what the model is doing, and that is the experience this app should give while the agent is processing, orchestrating, executing, and verifying.

## What

Two surfaces driven by one client-side derivation.

An in-chat thinking block inside each run's transcript (requested mid-implementation), matching how ChatGPT and Claude place thinking in the conversation:

- while the agent reasons (orchestrating, verifying, recovering) the header shows a shimmering "Thinking…";
- while it acts the header shows what it is doing, e.g. "Executing: Navigate to acme.com/careers…";
- thoughts stream into the collapsible body as they form, and the block collapses to "Thought for Xs" when the run finishes (click to expand).

A new Thinking view in the right-hand panel, shown as the default tab, with the existing raw log view kept as a second tab.

- The feed is derived on the client from the same log lines the panel already receives over `/ws/stream`; no backend changes.
- A parser (`frontend/src/lib/thinking.js`) turns raw lines into a curated narrative:
  - `[NODE]: X` banners become phase transitions (Orchestrating, Executing, Verifying, Recovering, Responding, Waiting).
  - `Reasoning:` lines and bracket-tagged entries (`[Decision]`, `[Executor]`, `[Verifier]`, `[Fallback]`, `[Interaction]`) become plain-English thoughts.
  - Plan printouts become a checklist; repeated printouts of the same plan collapse into a "now on step N" thought.
  - Bookkeeping noise (`Run ID:`, `Transactions Completed:`, `Error Type: none`, ...) is dropped.
- Presentation (`frontend/src/components/ThinkingStream.jsx`):
  - shimmer status line with the current phase and a live elapsed timer, "Thought for Xs" once finished;
  - new thoughts fade in word by word, like the referenced thinking UIs;
  - phase section markers, plan checklist, auto-scroll, blinking cursor while live;
  - `prefers-reduced-motion` disables the animations.

## Non-goals

- No new backend log format or WebSocket message types.
- The raw log view stays untouched (moved behind the "Logs" tab).

## Acceptance

- Starting a run shows the in-chat block and the Thinking tab streaming readable, animated thoughts in real time.
- The in-chat block header reads "Thinking…" while reasoning and "Executing: [task]…" while acting.
- Switching to the Logs tab shows exactly the previous behavior.
- A finished run renders its full thinking transcript statically (no replayed animation) with total thinking time, and the in-chat block collapses to "Thought for Xs".
- `npm run lint` and `npm run build` pass.

All verified 2026-08-02 against a scripted replay of a realistic run (plan, execute, verify, fallback, HITL pause, finish) in the dev server.
