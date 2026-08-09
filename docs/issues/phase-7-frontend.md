# Issue: Phase 7 - HUMANi frontend overhaul and run lifecycle

Status: **closed** (implemented 2026-08-09)
Branch: `Edwin-after-grad`
Opened: 2026-08-09
Plan reference: `docs/IMPROVEMENT_PLAN.md`, Phase 7

Closed with: the full scope below.
Verification: 266 backend tests green (16 new for runs/documents/HITL routing), eslint and build clean, and a live end-to-end pass on the running dev servers - a real run persisted as `aborted / stopped by user` with a served JPEG artifact after a Stop, and screenshots confirmed the login page, dashboard, and settings modal render on-brand with Escape closing the modal.
The acceptance items needing a full application flow (HITL form round-trip, resume attach on the fixture form, two concurrent runs) are covered by unit tests plus the structured message contract; exercising them against real ATS pages is the next validation step.
Results table in the plan doc's Phase 7 section.

## Why

The agent core (Phases 0-6) is capable and observable, but the product around it is not:
runs are ephemeral (a refresh erases every transcript), unlabeled (every ended run says "Complete", including crashes), uncontrollable (stopping requires typing "stop" into chat), and single-file.
Settings collect values nothing reads, two buttons do nothing, and HITL renders as a bare chat line even though the backend sends structured fields.

Separately, the product now has a brand: **HUMANi** - a friendly figure in a browser window with a cursor.
The current sky-cyan gradient theme predates it.

## Brand and design direction

- Recreate the provided logo as **flat SVG** (the mark: blue browser frame, round-headed figure, cursor; the wordmark: dark-navy HUMAN + blue i). No gradients; the PNG originals carry incidental ones.
- Palette from the mark: brand blue `#4285F4` (actions, active states), dark navy ink `#1A1F4B` (headings, wordmark), soft blue tint `#EAF2FE` (selection, chips), neutral slate grays for body text and borders, white surfaces on a `#F6F8FC` canvas.
- Status colors: green `#1F9D61` (succeeded), red `#DE3B4B` (failed), amber `#E8930C` (needs you / aborted), slate (idle).
- Flat, simple, approachable: solid colors, 1px borders, soft shadows, generous radii, the mascot in empty states. Professional but friendly. No gradients anywhere they are not necessary (target: none).
- Applies to every page: dashboard, login, register, forgot/change password, about.

## What (scoping decisions against the plan's 15 items)

1. **Stop button** - sends the existing `abort_run` frame over the run's socket; prominent in the live panel.
2. **Real run status** - the server emits a structured `run_finished` message with `status` (`succeeded` / `failed` / `aborted`) and `exit_reason`; session chips and history render it. Status derives from exit code, abort flag, and mission outcome.
3. **Persist runs server-side** - a `runs` table: run_id, user_id, prompt, status, exit_reason, started/finished timestamps, final response, per-item results JSON, and a log tail. Endpoints: `GET /api/runs`, `GET /api/runs/{run_id}`. v1 keeps full log transcripts out of the DB (the tail is for diagnosis; artifacts carry the evidence).
4. **Result artifacts** - the streaming relay already holds the newest frame; on run end the server saves it as the run's final screenshot, served by an authenticated endpoint and shown in run history.
5. **Multi-run support** - frontend state (socket, running flag, stream) keyed per session; backend HITL reply queues keyed per (user, run) so two runs cannot eat each other's replies. The ten-port pool already isolates the browsers.
6. **Structured HITL only** - the server emits `HITL_CLOSED` when a reply is consumed; the frontend drops the `[NODE]: __INTERRUPT__` log-substring detection entirely.
7. **Structured HITL form** - `requested_fields` renders as a labeled form in chat; one input per field, submitted as one reply.
8. **Log panel** - STDERR visually distinct, no line-mangling sanitizer, monospace, autoscroll only when already at the bottom, entry cap.
9. **Document store** - upload resume/cover letter (server-side per-user disk store, authenticated endpoints); document paths ride the existing stdin credential blob so the agent's `upload_file` can attach them. Managed from Settings.
10. **Job queue UI** - a batch composer turns a pasted URL list into a work-items mission; per-item outcomes render from the run's item results.
11. **Multi-line prompt input** - textarea, Enter submits, Shift+Enter newlines, IME composition guard.
12. **Environment configuration** - `VITE_API_BASE` via `import.meta.env` with same-origin fallback; no hardcoded `localhost:8000` outside `vite.config.js` dev proxy.
13. **Dead code** - remove `UserCredentialsCard.jsx`, `App.css`, the `axios` dependency, the `agentPrompt` setting, and the react.svg/vite.svg leftovers.
14. **Modal hygiene** - `role="dialog"`, `aria-modal`, focus trap, Escape closes, explicit Cancel vs Save, consistent persistence semantics.
15. **Useful settings** - working password change (the Phase 1 flow), working account deletion (endpoint exists), document manager, and an **autonomy level** picker (confirm irreversible actions vs fully autonomous) stored per user and passed to the agent via the credential blob into `autonomy_policy`, which the backend already honors.

## Non-goals

- Log transcript persistence beyond the tail (revisit with the observability work).
- TypeScript migration, accessibility audit beyond the modal/focus items above (parked in the plan).
- Anti-bot posture changes.

## Acceptance

- A crashed run shows `failed` with an exit reason; an aborted run shows `aborted`; a completed one `succeeded` - verified by forcing each.
- Refresh after a run: the run, its status, its final response, and its screenshot artifact are still there (served from the backend).
- Stop button halts a live run within seconds.
- A HITL request for specific fields renders labeled inputs; the reply resumes the run; no log-substring parsing remains.
- Uploading a resume in Settings makes "attach my resume" work in a run against the local fixture form.
- Two runs in two sessions stream and accept replies independently.
- `rg -i 'gradient' frontend/src` returns nothing (or only justified cases).
- eslint clean, build clean, backend suite green.
