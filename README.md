# AgentCity

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

Fresh setup defaults to 80 citizens in an urban neighborhood. New maps contain two to four separate buildings per block (240 buildings at the default urban density), with clear road entrances and green courtyards. Apartments, offices, restaurants, markets and civic buildings have different silhouettes. Hover over a building in 3D or hover/focus one in 2D to see its name, purpose and capacity; tapping a building also shows its tag. Existing saved cities keep their original layout and population while receiving the new building rendering and tags. Existing setup drafts retain their chosen settings.

The setup command creates `backend/.venv`, installs the pinned Python dependencies and runs `npm ci` in `frontend/`. On Windows, `python` must be on PATH; set `PYTHON` if another executable is needed when creating the environment. `AGENTCITY_PYTHON` can select an existing compatible Python environment.

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

## Verify

```sh
npm test
npm run build
npm run test:e2e
```

`npm test` runs TypeScript, frontend unit/contract tests, backend tests, frozen contract verification and Ruff. Browser tests start isolated real backend processes and exercise the development proxy and built same-origin application. They use installed Chrome on Windows; on other systems install Playwright Chromium with `npm --prefix frontend exec -- playwright install chromium`. `PLAYWRIGHT_CHANNEL` can select an installed compatible browser. Browser tests use separate data directories under `backend/.tmp/`.

See [the integration handoff](docs/integration-handoff.md) for test evidence and limitations. Gemini requires an account key and model configuration and has not been live-tested with credentials. PostgreSQL/Tiger Data, Snowflake and ElevenLabs adapters are unavailable; capabilities report that explicitly. The functioning local application uses durable local storage, rules simulation, live export and replay.
