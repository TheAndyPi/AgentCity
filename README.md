# AgentCity

Current development coordination: [shared dev log](docs/dev-log.md),
[release integration handoff](docs/release/integration-handoff.md), and
[functional acceptance cases](docs/release/acceptance-cases.md).
Latest combined integration evidence: [scenario, survival and live-voice verification](docs/release/feature-merge-2026-10-25.md).

AgentCity runs a persistent society simulation with a React/Three.js interface and a FastAPI backend. The interface uses real HTTP and WebSocket data by default. Rules mode works locally without an API key.

## Start the application

Install Node.js 22.12+ (with npm) and Python 3.13+. From this directory:

```sh
npm run setup
npm run dev
```

Open [AgentCity](http://127.0.0.1:5173). The launcher starts both servers, checks their readiness, and stops its child processes on Ctrl+C. The API listens on port 8000; its [interactive documentation](http://127.0.0.1:8000/docs) and `/health/ready` probe are available there. Use one backend worker.

Reopening a larger saved history includes integrity verification. The launchers allow up to five minutes for backend readiness before reporting a startup timeout.

Create a city, confirm or skip its initial scenario, then use Play or Step. Custom scenarios pause the city while their effects are previewed. Outcomes, snapshots, replay, restored branches, profiles, settings and history use backend persistence in `backend/data/`. Restarted simulations reopen paused. Rules decisions are labeled in the interface.

Fresh setup defaults to ten citizens in a suburb; population can be adjusted up to the server's advertised maximum (normally 100). Existing drafts and templates can select different settings. City layouts vary with settlement and density, with separate buildings, road entrances and green courtyards. Apartments, offices, restaurants, markets and civic buildings have different silhouettes. Hover over a building in 3D or hover/focus one in 2D to see its name, purpose and capacity; tapping a building also shows its tag. Existing saved cities keep their original layout and population while receiving the new building rendering and tags.

The setup command creates `backend/.venv`, installs the pinned Python dependencies and runs `npm ci` in `frontend/`. On Windows, `python` must be on PATH; set `PYTHON` if another executable is needed when creating the environment. `AGENTCITY_PYTHON` can select an existing compatible Python environment.

## Scenarios and procedural scenes

Opening scenarios and interventions share 27 composable recipe families, including
visitors, wildlife, dinosaurs, alien arrivals, robots, markets, concerts, gardens,
protests, construction, clinics, illness, weather, discoveries and portals, plus
the original hazards and policies. Try “2 red robots deliver community aid during
a snowstorm in the east for 20 ticks” or “Dinosaurs arrive during a festival”.
Prompts support cardinal regions, severity, tick duration, prop counts and colors.
Without a region, social and resource effects cover the city; hazards use a
bounded district so citizens can still seek safety outside it. Request “citywide”
to deliberately affect the whole map.

Review the orbitable low-poly scene and the listed simulation effects before
confirming. Scene props appear during active events and are preserved in saves,
reports, repeats and replay. Each scene uses at most 24 simple props, without
external model downloads. Rules mode builds these locally. When Gemini is enabled,
it can additionally compose an unfamiliar subject from up to eight basic shapes,
using the existing provider timeout, rate limit and token budget. Malformed or
unavailable provider output falls back to the local scene. The shared recipe and color files
live in `contracts/scenario-catalog.json` and `contracts/scenario-palette.json`.
A premise must map to at least one recipe's simulation effects. When no recipe
term matches and Gemini is enabled, the model chooses recipes from the catalog
and the preview names its interpretation. If neither can interpret the premise,
the preview cannot be confirmed and asks for an event kind, region, severity and
duration, or a differently worded description. Props illustrate events;
they do not add autonomous creatures, new citizens or collision obstacles.

## Configuration

Defaults need no `.env` file. For server configuration, copy `backend/.env.example` to `backend/.env` and edit it. Root launchers load this file; environment variables take precedence. Relative server paths resolve from `backend/`. Secrets stay on the server. Never place provider keys in a `VITE_` variable.

`PORT` changes the API port and `FRONTEND_PORT` changes the development UI port. The launcher forwards both HTTP and WebSocket requests and derives matching loopback origins unless `ALLOWED_ORIGINS` is explicitly configured. An occupied port produces an error; the launcher does not stop other services.

For a built application served together with the API on one origin:

```sh
npm run build
npm start
```

Open [the built application](http://127.0.0.1:8000). Direct route reloads are supported. Public hosting still requires the HTTPS/session configuration in [backend operations](backend/operations.md); no public deployment was made.

`npm run dev:mock` explicitly selects recorded frontend fixtures for UI review. Its visible Mock badge distinguishes it from the live application. There is no automatic fallback from live data to fixtures.

With server-side ElevenLabs configuration, select a citizen or watch a conversation,
then choose **Enable live voices** for automatic committed dialogue. Sound starts
with new turns; replay is explicit. See [live voices setup and limits](docs/release/live-voices-handoff.md).

## Verify

```sh
npm test
npm run build
npm run test:e2e
```

`npm test` runs TypeScript, frontend unit/contract tests, backend tests, frozen contract verification and Ruff. Browser tests start isolated real backend processes and exercise the development proxy and built same-origin application. They use installed Chrome on Windows; on other systems install Playwright Chromium with `npm --prefix frontend exec -- playwright install chromium`. `PLAYWRIGHT_CHANNEL` can select an installed compatible browser. Browser tests use separate data directories under `backend/.tmp/`.

See [the release validation report](docs/release/validation-report.md) and [shared dev log](docs/dev-log.md) for dated evidence and limitations. Gemini supports Developer API or Vertex AI configuration; [prior live Vertex application verification](docs/vertex-integration.md) is documented separately from the default mocked provider tests. Optional [Tiger ingestion](docs/release/tiger-handoff.md) keeps local storage authoritative and has passed real SQL verification. [Snowflake comparisons](docs/release/snowflake-handoff.md) are wired into the default app; real SQL/Cortex verification still needs schema privileges. [ElevenLabs narration](docs/release/narration-handoff.md) supports recorded events, decisions and dialogue through the existing API and browser playback. All three adapters are disabled by default and require server-side configuration. [Vultr deployment preparation](deploy/README.md) is supplied; live hosting remains unverified.
