# AgentCity frontend

A TypeScript / React / Three.js society-simulation interface implementing the supplied AgentCity 1.0.0 contract. The backend remains the authority for simulation state.

## Run

```sh
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173. Development explicitly selects **Mock mode** in `.env.development` so the complete frontend can be reviewed without a backend. The persistent badge identifies all fixture views. Start at the landing page or choose “Explore the preview city.” The fixture adapter uses recorded map/pose/outcome samples; it is not a simulation engine or live model integration.

On this machine the Homebrew Node executable has a missing library. `./run.sh` automatically uses the available bundled Node runtime without changing machine configuration:

```sh
./run.sh ci
./run.sh                   # fixture preview
./run.sh run dev:live      # real FastAPI integration
./run.sh run typecheck
./run.sh run test
./run.sh run build
```

For another machine, use Node 22.12+ and npm. All dependencies and lockfiles are frontend-local.

## Connect FastAPI

Run the backend on port 8000, then `npm run dev:live`. Vite proxies `/api`, including WebSocket upgrades, preserving Origin. `.env.example` documents the two public settings. Production defaults to `VITE_DATA_MODE=live` and `VITE_API_BASE_URL=/api/v1`.

Build with `npm run build`, serve `dist/` with SPA fallback, and reverse-proxy `/api` and WebSockets to the backend. No server secret or provider key belongs in a `VITE_` variable. Session mode uses cookies and CSRF returned by the server; a passphrase dialog appears when authentication is needed. There is no automatic live-to-mock fallback.

## Frontend behavior

- Landing, single-page setup with retained draft, initialization, full-screen 3D city and interactive 2D fallback.
- Stable instanced citizen picking, bounded interpolation along acknowledged paths, orbit/pan/zoom/follow, scalar overlays, live/replay/connection labels.
- One navigable inspector drawer: citizens, memories, relationships, beliefs, goals, validated decisions, events, feed, overview, comparison, and custom citizen picker.
- Server-mediated event pause → preview → confirm/cancel, initial scenario confirmation, durable outcome reports, and undo into a new paused branch.
- Save-before-navigation, including browser Back; manual save; archived/active history; duplication; exact-target archive deletion with partial-failure reporting.
- Revision-bound historical playback, separate return-to-live and branch continuation, common-scale comparisons, lineage and endpoint differences.
- Custom profile CRUD, pastel/dark themes, reduced motion, view choice, editable validated keyboard shortcuts, usage and nullable pricing. Optional server narration and live CSV export.

Space toggles play while the map has focus. Arrow keys pan. Cmd/Ctrl with +/- zooms, and Cmd/Ctrl with Left/Right rotates. Visible controls provide alternatives. Escape dismisses the top layer through its appropriate server flow.

## Verify

```sh
npm run typecheck
npm test
npm run build
npm exec vite-node -- scripts/generate-fixtures.ts
```

Tests cover DTO rejection, preview/commit/cancel semantics, idempotent retries, historical isolation, source-save failure, restored branches, copied profiles, CSRF headers, stale frames, reconnect polling, and instance selection. `tests/fixtures/` contains frontend-local validated samples and an exact fixture request/response trace. These do not replace coordinator-owned cross-language parity artifacts.

`tests/visual/index.html` is a development-only responsive harness. Choose a CSS viewport and route. It scales the iframe to the available panel and reports horizontal document overflow. It is excluded from the production entry. A development city URL with `?qa=1` exposes a measured FPS readout and a WebGL-loss test control. Neither appears in production.

Review-cache data is confined to sessionStorage **in mock mode**, resumes paused after refresh, and can be discarded with the browser session. A full cache can remain memory-only. Live worlds are never stored in browser storage; only the unsent setup draft is locally cached.

See [frontend handoff](../docs/frontend-handoff.md) for validation evidence, scope and integration prerequisites.
