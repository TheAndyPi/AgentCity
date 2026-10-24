# AgentCity frontend handoff

> Historical independent frontend baseline. Integration is now implemented and
> verified with the real backend; the current results, run commands and remaining
> limits are in [integration-handoff.md](integration-handoff.md). The baseline
> claims below about missing backend/contracts and default mock mode are superseded.

Contract: **1.0.0**, from the three supplied Markdown documents. Implementation ownership: `frontend/**`, this file, and `docs/frontend-contract-requests.md`. The initial repository had only an initial README and no frontend, backend, shared schemas, tests, or API integration. No existing application was replaced. Root README, root package configuration, deployment, backend and protected contract paths were not edited.

## Delivered

`frontend/src/main.tsx` defines all requested routes. `pages/` contains Landing, Setup, Loading, Simulation, History, Templates, Settings and About. The visual system uses violet surfaces, restrained neon accents, an original wire city/brand, subtle circuits/gears, responsive sheets, pastel light colors and reduced motion. There are no remote image or font dependencies.

`api/types.ts` is a mechanical projection of the supplied DTO notation; `api/schemas.ts` provides strict Zod response, stream and mutation validators. `AgentCityClient` is shared by live and fixture transports. It validates envelopes, sends cookies/CSRF/idempotency headers, encodes opaque path IDs, and keeps revision queries explicit. `state/world.ts` uses useSyncExternalStore and rejects stale, equal, foreign or obsolete-generation frames. Socket hello, heartbeat, reconnect and two-second polling fallback are implemented. The last valid world remains available after transport errors; there is no automatic switch to fixtures.

`world/World.tsx` consumes returned cells, footprints, entrances, paths, hazards, zones and citizen coordinates (x/elevation/y). Rectangular buildings and citizens use instancing; nonrectangular buildings use their actual polygons. Ground/map dimensions are taken from the frame. Facade choices are decorative. Interpolation uses only a verified prefix of the previous legal path, snaps without that evidence, and stops at the newest acknowledged position. Historical/branch jumps cancel follow. The 2D SVG renderer supports citizen selection, pan, zoom, follow and the same overlays. Context-loss listeners are removed before canvas disposal, preventing normal branch cleanup from triggering fallback.

Event entry waits for intervention acknowledgment. Preview never applies effects. Typed input survives errors, editing invalidates previews, commit retries retain the same key, and repeat only offers resolved events. Initial previews require Confirm or Skip. Outcome modal data comes from the event report and pending outcome IDs; controlled dismissal acknowledges rather than issuing Play. Undo branches from the returned pre-event snapshot and opens a new paused simulation. Recorded consequences, interval measurements and proposed preparations are labeled separately.

One typed drawer stack supports Search → Citizen → Decision/Event → Back; it also hosts logs, overview, durable dialogue, directed relationships, overlays, custom-agent picker and comparison. Inspectors are scoped to simulation/revision; replay uses committed revisions and never asks a model to regenerate history. Continue from here and Return to live are separate actions. A navigation blocker also protects browser Back: the source world is saved and paused before routing. A failed save keeps the user in the city.

Settings/profile CRUD uses server versions. Profiles include all contract fields; edits affect future copies only. Setup drafts survive a visit to Settings. Periodic autosave is explained separately from mandatory event/navigation snapshots. Shortcuts are validated for canonical chords and duplicates, and world shortcuts are focus-scoped. Live advanced overrides require explicit substantive-intervention confirmation. Optional narration is capability-gated; CSV export is scoped to the inspected revision.

## Fixture scope

`.env.development` explicitly enables the frontend review adapter; production defaults to live. The badge remains visible. The fixture adapter selects recorded map/pose/outcome samples, supports initialization/intervention/queued/active/resolved/report/branch/history/profile transitions, returns contract-shaped errors, and preserves review state in sessionStorage. This cache is never used by the live transport and is not backend persistence. Mock refresh restores running/editor state paused. Override execution is visibly unavailable in review mode; CSV export and optional narration require live capabilities. Natural-language interpretation in review mode is a bounded fixture selector, not Gemini.

`tests/fixtures/ready.json`, `preview.json`, `rejected_decision.json`, and `report.json` are validated local samples. `tests/fixtures/flow-trace.json` records exact request/response envelopes for creation, staged initialization, initial confirmation, stepping to an outcome, report query, pre-event branching, state and inspector reads. Generate with `npm exec vite-node -- scripts/generate-fixtures.ts`.

## Verification

- `npm run typecheck`: passed.
- `npm test`: **37 tests passed** across contract, workflow and streaming suites. Coverage includes running/paused cancel and commit, invalid/expired previews, idempotent commit retry, outcome acknowledgment under manual stepping, source-save failure, profile copy isolation, exact initial-preview revision, archived-only deletion, lower/equal revision rejection, instance ID remapping, bounded path interpolation, CSRF headers, late REST races, socket generation cleanup, invalid stream recovery and polling after three failed connections.
- `npm run build`: passed. React/route assets are split; the Three/Fiber/Drei chunk is approximately 305 KB gzip. Production build and typecheck passed again after the rendering corrections.
- Browser: landing → setup → returned initialization progress → paused 100-citizen city → initial flood preview → queued event → Play → report at tick 9 → Undo into a new paused branch with baseline metrics restored. Original timeline remained available. Search and citizen inspection, custom preview and queued-until-Play notice were also exercised.
- Responsive harness: CSS viewports 1440×900, 1280×800, 768×1024 and 390×844; checked layouts reported no horizontal document overflow. The in-app browser panel is physically narrow; saved wide-view screenshots are explicitly scaled QA previews, not native full-resolution desktop captures.
- `frontend/screenshots/` contains captured landing/setup/loading/city/inspector/scenario/report/history/settings evidence. Remaining browser findings and measurements are appended below.

## Integration prerequisites and limits

The repository has no backend or frozen coordinator-owned machine artifacts. Therefore **F2 live API integration, Python/Zod parity, OpenAPI snapshot parity, real WebSocket delivery, session security, server persistence/restart recovery, real Gemini reasoning, narration and analytics have not been verified**. The live adapter follows the supplied 1.0.0 endpoint table, but an interface implementation is not proof of a working server. No backend durability or model behavior is claimed from the fixture demonstration.

The coordinator must provide/freeze the files listed in `docs/frontend-contract-requests.md` and run the first real slice: capabilities/session → create → initialization → state → stream hello/snapshot → play/pause → citizen → decision. Then rehearse custom intervention commit/cancel under both prior playback states, pending outcomes after reconnect, undo/branching, source-save failure and persistence restart. Deployment/reverse-proxy validation and actual endpoint authorization remain backend/integration gates. The frontend is local; nothing was published.

Browser accessibility, rendering, and keyboard checks provide practical evidence, not universal device performance or a formal WCAG certification. CSS contrast was designed for readable light/dark surfaces; formal contrast tooling and screen-reader review remain release checks. Complex deeper lineage comparisons show explicit absence of a verified common point rather than claiming unsupported provenance. No statistical significance is implied by independent branch runs.

## Run on the current machine

The global Homebrew Node executable cannot load its llhttp dylib. `frontend/run.sh` uses the bundled Node 24 runtime if available and changes no system files. Run `cd frontend && ./run.sh` for review, or `./run.sh run dev:live` with FastAPI on 8000. Normal Node/npm commands work on machines with a healthy installation.

## Final browser observations

The restored-branch context-loss issue was corrected and regression-tested: replay → Continue from here opened a new paused **3D** world and remained in 3D after normal disposal. The explicit WEBGL_lose_context test then switched a 100-citizen world to 2D, where selecting Maya opened the same metric/decision inspector. Orthographic screen-space building labels were also corrected so they no longer expand over the scene.

Measured two-second useFrame windows in the physically narrow in-app viewport: **120.0 FPS with 30 citizens** and **120.1 FPS with 100 citizens**, on paused fixture worlds. A full 100-citizen flood sequence also completed responsively through its tick-9 report. These observations do not substitute for running-world 1440×900 profiling or real-server throughput measurements.

Settings saved the pastel light theme and reduced motion; DOM state confirmed `theme=light`, `motion=reduced` and no horizontal overflow. The mandatory save barrier displayed acknowledgment before History/Settings navigation. History contained both the original resolved event world and the new pre-event branch. Screenshots are labeled `*-narrow.png` for native panel captures and `*-preview.png` for scaled CSS-viewport captures.

No provider calls were made. No deployed Site or public mutation endpoint was created. The backend/contract-freeze integration gates above remain explicit.

Final checks after the label and listener fixes: production build/typecheck passed; the final test suite contains **37 passing tests**. The WebGL disposal regression and an ambiguous intervention-response recovery case are included. A viewport-focused Space press started the world, and another Space press returned it to paused state in the browser. The preview server was stopped after QA; `frontend/run.sh` restarts it without system configuration changes.
