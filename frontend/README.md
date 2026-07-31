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
- `src/components/` - `ProtectedRoute` (route guard) and `UserCredentialsCard`.
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

## Known gaps

The build toolchain aliases `vite` to `rolldown-vite` via `overrides` in
`package.json`. There is no test script and no TypeScript, despite
`@types/react` being installed.
