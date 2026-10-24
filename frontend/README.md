# AgentCity frontend

A TypeScript / React / Three.js society-simulation interface implementing the supplied AgentCity 1.0.0 contract. The backend remains the authority for simulation state.

## Run

From the repository root, use Node 22.12+ and Python 3.13+:

```sh
npm run setup
npm run dev
```

Open http://127.0.0.1:5173. Development now defaults to **live backend data**. The root launcher starts FastAPI and Vite together. `npm run dev:mock` from the root explicitly selects fixture review mode. Its persistent badge identifies recorded views; it is not a simulation engine or live model integration. The old `run.sh` is an optional legacy Unix helper; normal Node/npm commands work on the current Windows installation.

## Connect FastAPI

For separate terminals, run the backend on port 8000 and then `npm run dev:live` from `frontend/`. Vite proxies `/api`, including WebSocket upgrades, preserving Origin. `.env.example` documents the two public settings. Production defaults to `VITE_DATA_MODE=live` and `VITE_API_BASE_URL=/api/v1`.

From the root, `npm run build` followed by `npm start` serves the built UI, API and WebSocket on port 8000 with direct-route fallback. An external reverse proxy is optional for local use and required for public TLS hosting. No server secret or provider key belongs in a `VITE_` variable. Session mode uses cookies and CSRF returned by the server; a passphrase dialog appears when authentication is needed. There is no automatic live-to-mock fallback.

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
npm run test:e2e
npm exec vite-node -- scripts/generate-fixtures.ts
```

Tests cover DTO rejection, all 32 frozen shared parity fixtures, preview/commit/cancel semantics, idempotent retries, historical isolation, source-save failure, restored branches, copied profiles, CSRF headers, stale frames, reconnect polling, and instance selection. `tests/fixtures/` contains additional frontend-local samples. `artifacts/integration/` records actual live browser evidence. Build before running browser tests; the test runner starts isolated development and built backend servers automatically.

`tests/visual/index.html` is a development-only responsive harness. Choose a CSS viewport and route. It scales the iframe to the available panel and reports horizontal document overflow. It is excluded from the production entry. A development city URL with `?qa=1` exposes a measured FPS readout and a WebGL-loss test control. Neither appears in production.

Review-cache data is confined to sessionStorage **in mock mode**, resumes paused after refresh, and can be discarded with the browser session. A full cache can remain memory-only. Live worlds are never stored in browser storage; only the unsent setup draft is locally cached.

See the current [integration handoff](../docs/integration-handoff.md) and historical [frontend handoff](../docs/frontend-handoff.md) for evidence and scope.
