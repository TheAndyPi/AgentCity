# AgentCity backend — contract 1.0.0

One FastAPI process owns the simulation, HTTP commands, full-frame WebSocket,
and durable local history. Rules mode runs without vendor keys. The repository
originally contained only a placeholder README; this is a new backend.

## Run locally

For the complete application, run `npm run setup` and `npm run dev` from the
repository root. The UI opens on port 5173 and uses this backend on port 8000.
`npm run build` followed by `npm start` serves both on port 8000. Root launchers
load `backend/.env`; process environment variables take precedence. See the
[integration handoff](../docs/integration-handoff.md) for live browser evidence.

Use Python 3.13. From the repository root, in PowerShell:

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
$env:HOST = '127.0.0.1'
$env:DATA_DIR = './data'
$env:AUTH_MODE = 'local'
$env:LLM_MODE = 'rules'
.\.venv\Scripts\python.exe -m app
```

The server listens on port 8000. Interactive HTTP documentation is at
`http://127.0.0.1:8000/docs`. Health probes are `/health/live` and `/health/ready`.
Use exactly **one worker**. A file lock also rejects competing writers to the
same data directory. `.env.example` documents server environment variables;
the direct `python -m app` command reads process environment only, whereas the
root Node launchers load `backend/.env` as configuration data.

`requirements.lock` pins the complete tested runtime and verification tools.
`pyproject.toml` identifies direct runtime/development dependencies. Python 3.13
on Windows was tested; Linux deployment configuration is documented below but
has not been rehearsed on a Vultr host.

## Frontend integration

1. GET `/api/v1/capabilities` and `/api/v1/session` with cookies enabled.
2. Keep the returned CSRF token in memory. Send `X-CSRF-Token` and a fresh UUID
   `Idempotency-Key` on writes. A command's body `request_id` must match that key.
3. POST `/api/v1/simulations` with `{"config":{"name":"My city","seed":42}}`.
   Missing setup controls use documented defaults. The response is a durable
   initializing Simulation with HTTP 202. Poll its resource for real stages.
4. After `initialization.stage=ready`, GET `/state`. The city starts paused.
   Confirm or skip a non-null initial preview before playing.
5. Open `/api/v1/simulations/{id}/stream`; send
   `{"type":"hello","schema_version":"1.0.0","last_revision":null}` within
   five seconds. The first ready message is a complete snapshot. Initialization
   messages contain Simulation, without an empty fabricated world.
6. Pin `revision` on historical queries. Cursor tokens also pin revision and
   bind owner, collection and filters. Fetch durable audit pages independently
   of animation frames.

Every normative HTTP operation is implemented. Optional narration returns a
contract-shaped 501. See `../contracts/v1/openapi.yaml`, `schemas.json`,
`stream.schema.json` and the shared fixtures. The supplied contract is copied
verbatim and its hash is frozen. The integrated React/Zod consumer now passes
the same shared fixtures and real browser flows with HTTP and WebSocket data.

Development origins include localhost/127.0.0.1 ports 5173 and 8000. A frontend
proxy must forward `/api` and WebSocket upgrades. Use the backend map's x/y meter
coordinates directly; Three.js places them at `[x,elevation_m,y]`.

## Verification and demo

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check app scripts tests
.\.venv\Scripts\ruff.exe format --check app scripts tests
.\.venv\Scripts\python.exe -m scripts.contracts --check
.\.venv\Scripts\python.exe -m scripts.demo
.\.venv\Scripts\python.exe -m scripts.benchmark --steps 30 --live-ticks 10
```

The demo seeds a 30-citizen city in `DATA_DIR` (default `./data`), confirms a
flood, steps to a measured outcome, and creates a restored pre-event copy. It
leaves both worlds durable and paused. Run it before starting the server using
that directory, then inspect the worlds through the API. `artifacts/demo-trace.json`
contains the last recorded rehearsal; `request-response-trace.json` records its
actual HTTP write requests/responses, and `performance.json` holds measured results.

To reset an experiment, branch from its initial snapshot. To undo an event,
branch from `pre_event_snapshot_id`; the original timeline remains. To remove a
world, archive it and DELETE with its exact `confirmation_name`. Each bulk
deletion must use a separate endpoint call and handle partial failures.

In a restricted Windows automation sandbox, set `TEMP`/`TMP` to a writable
project directory for pytest and allow local sockets: Python's event loop itself
uses a loopback socket pair. Normal PowerShell execution does not need this
sandbox workaround. Tests launch and clean up a real one-worker Uvicorn process
in addition to in-process HTTP/WebSocket checks.

## Modules and rules

- `simulation/engine.py`: staged ticks, needs, seeded fair ordering and cadence.
- `simulation/agents.py`: profiles, memory retrieval/reflection, directed ties,
  perception and derived metrics.
- `simulation/game_master.py`: legal intents, resource/capacity checks and effects.
- `simulation/interactions.py`: invitations, acceptance, local speech and aid groups.
- `simulation/scenarios.py`: town generation, compilation, event lifecycle/reports.
- `data/repository.py`, `api/views.py`: atomic journal/checkpoints, historical reads,
  analytics, pagination and export.
- `service.py`, `infrastructure/`, `api/`: commit orchestration, provider budgets,
  authentication and transport. Nine versioned role templates and internal output
  schemas live in `prompts/`.

Detailed formulas and assumptions are in `rules.md`; storage/recovery and the
deployment recipe are in `operations.md`. The handoff and known limitations are
in `../docs/backend-handoff.md` and `../docs/backend-contract-requests.md`.

## Gemini and optional integrations

Gemini supports two explicit billing routes. Set `LLM_MODE=gemini` and
`GEMINI_MODEL=gemini-3.5-flash-lite` in `backend/.env`.

For Google Cloud (Vertex AI), set `GEMINI_BACKEND=vertex`,
`GOOGLE_CLOUD_PROJECT` to your project ID, and `GOOGLE_CLOUD_LOCATION=global`.
Enable `aiplatform.googleapis.com` on that project and confirm its linked billing
account has eligible unexpired credits. The calling identity needs Vertex AI User
(`roles/aiplatform.user`) and Service Usage Consumer (`roles/serviceusage.serviceUsageConsumer`).
For local authentication, install the Google Cloud CLI and run:

```sh
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

Alternatively, set `GOOGLE_APPLICATION_CREDENTIALS` to the absolute path of a
service-account JSON file stored outside Git (owner-only permissions, e.g. `chmod 600`).
The local unattended setup uses service account
`agentcity-backend@agentcityx.iam.gserviceaccount.com` in project `agentcityx`.
The secret itself is not included in this repository. Set
`GOOGLE_GENAI_USE_VERTEXAI=true` as the standard Google SDK routing flag;
AgentCity's explicit `GEMINI_BACKEND` takes precedence if both are set.
For a Google Cloud deployment, prefer attaching the service account to the
runtime and omit `GOOGLE_APPLICATION_CREDENTIALS` so metadata credentials are used.
Google Cloud authentication refreshes
off the simulation event loop. This route never uses `GEMINI_API_KEY` or silently
switches to AI Studio billing. Credit eligibility and charges are controlled by
Google Cloud, not by these environment variables.

For the AI Studio Developer API instead, set `GEMINI_BACKEND=developer` and
`GEMINI_API_KEY`. That route uses AI Studio billing, which excludes the standard
Google Cloud welcome credits.

From the repository root, `npm run test:gemini` loads the local environment and
makes one small live structured-decision request. Authentication must be completed
first. `npm run test:gemini -- --application` starts a disposable real backend,
creates a ten-citizen city through HTTP, plays it, and requires an accepted
Gemini decision returned through the decision API. It pauses the test city and
removes its temporary storage. Both commands make real, potentially billable
Vertex requests; they are opt-in and excluded from `npm test`.
Restart the backend after configuration changes.

The gateway uses structured JSON and semantic Game Master
checks. Physical ticks never await the provider. Timeout, rate limit, malformed,
obsolete, budget-limited and circuit-open responses fall back to labeled rules.
Citizen decisions and optional free-form scenario geometry call the provider in
this build. Scenario geometry uses a bounded SceneDesign schema and is generated
outside simulation commit locks; preview retries reuse the original result.
Deterministic planning, social updates, speech and batched reflection implement
the remaining core behavior. The other role templates are validated proposal interfaces for
future optional enrichment, not evidence of live model execution.

No live Gemini request was made without user credentials. Tests use explicit
mock provider responses to verify the gateway and failure paths. Recorded demo
and performance artifacts are labeled **rules**. Usage records actual response
metadata; when any call has no token metadata, the affected Usage endpoint
returns explicit 503 unavailable instead of a fabricated token total. Conservative
internal budget charges survive restart. Estimated dollars remain null.

PostgreSQL/Tiger Data, Snowflake and ElevenLabs adapters are unavailable.
Capabilities report local persistence, `snowflake=false`, and `narration=false`.
Selecting `PERSISTENCE_MODE=postgres` fails configuration clearly. These optional
services are not prerequisites for simulation, history, export or branching.
