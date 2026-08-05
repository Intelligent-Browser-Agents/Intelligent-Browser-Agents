# Frontend

React + Vite UI for Intelligent Browser Agents. Users log in, submit a task
prompt, watch the agent's live browser feed and logs, and answer
human-in-the-loop (HITL) questions.

See the root [README.md](../README.md) for full-system setup and
[docs/IMPROVEMENT_PLAN.md](../docs/IMPROVEMENT_PLAN.md) for known defects.

## Running

```bash
npm install
npm run dev
```

The dev server proxies to a backend expected on port 8000 (see `vite.config.js`):

- `/api` to `http://localhost:8000`
- `/ws` to `ws://localhost:8000`

Start the backend first, then open the URL Vite prints (usually
`http://localhost:5173`).

## Scripts

| Command | Purpose |
| --- | --- |
| `npm run dev` | Dev server with HMR |
| `npm run build` | Production build to `dist/` |
| `npm run preview` | Serve the production build locally |
| `npm run lint` | ESLint over `src/` |

## Layout

- `src/pages/` - `Login`, `Register`, `ForgotPassword`, `Dashboard`, `About`, each with a sibling CSS file.
- `src/components/` - `ProtectedRoute` (route guard), `UserCredentialsCard`, and `ThinkingStream` (animated thinking views).
- `src/lib/` - `api.js` (REST/WS helpers) and `thinking.js` (log-to-thought derivation).
- `src/App.jsx` - route table.
- `assets/` - agent icons and the HITL notification sound, imported directly by `Dashboard.jsx`.

Note that `assets/` sits beside `src/`, not inside it. The ten PNGs under
`assets/icons/` are required build inputs; a blanket `*.png` gitignore rule used
to exclude them.

## Dashboard streaming

`Dashboard.jsx` opens `WS /ws/stream/{user_id}` per run and handles five message
types: `FRAME` (base64 JPEG browser frame), `STATUS`, `LOG`, `CLARIFICATION`
(HITL prompt), and `RESPONSE`.

There is currently no reconnect logic, no stop button, and no run persistence
across a page refresh. Phases 6 and 7 of the improvement plan cover these.

## Thinking view

The run logs also drive an animated "thinking" surface, in the style of the
ChatGPT / Claude thinking UIs. Everything is derived client-side from the
existing `LOG`/`STATUS` messages; there is no dedicated backend channel.

- `src/lib/thinking.js` parses raw log lines into a curated feed: `[NODE]:`
  banners become phase sections, `[Decision]`/`[Executor]`/`[Verifier]`/
  `[Fallback]`/`[Interaction]` entries become plain-English thoughts, plan
  printouts become a checklist (reprints collapse into "Now on step N"), and
  bookkeeping noise is dropped.
- `src/components/ThinkingStream.jsx` renders two surfaces from that feed:
  - `ThinkingChatBlock` - a collapsible block inside each chat run whose header
    shows "Thinking…" while the agent reasons and "Executing: [task]" while it
    acts, then collapses to "Thought for Xs" when the run ends;
  - `ThinkingStream` (default export) - the full-height Thinking tab in the
    right-hand panel, next to the raw Logs tab.
- New thoughts fade in word by word; `prefers-reduced-motion` disables all of
  the animation.

The issue that introduced this is
[docs/issues/thinking-stream-ui.md](../docs/issues/thinking-stream-ui.md).

## Known gaps

The build toolchain aliases `vite` to `rolldown-vite` via `overrides` in
`package.json`. There is no test script and no TypeScript, despite
`@types/react` being installed.
