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

Startup reads the small save manifest without loading saved worlds or walking their histories. The History tab reads current world summaries on demand. Opening a saved world verifies its current state and restores it paused; older revisions and history records are read and verified only when requested. Saved-state loading runs off the main request loop so the rest of the app stays responsive. The launchers allow up to ten minutes for backend readiness. Set `BACKEND_STARTUP_TIMEOUT_SECONDS` (30–1800 seconds) in `backend/.env` to adjust that allowance.

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

The AI event registry exposes the same scene catalog through `catalog_event`.
Gemini can combine dinosaur, alien, robot and other catalog scenes with policy
and behavioral changes in a single validated plan. These events retain the
catalog's listed effects and bounded scene objects. For example, dinosaurs can
appear with wellbeing effects; autonomous chasing, attacks and building
destruction are not supplied by the dinosaur recipe and are explained as
unsupported parts of a request.

## Configuration

Defaults need no `.env` file. For server configuration, copy
[`backend/.env.example`](backend/.env.example) to `backend/.env` and edit it.
Both `npm run dev` and `npm start` load `backend/.env` automatically; the launchers
do not read a root `.env`. Existing shell environment variables take precedence
over the file. Relative server paths resolve from `backend/`. Restart the
application after changing settings.

Keep provider keys and credential files on the server, outside Git and the
frontend. Never place provider keys in a `VITE_` variable. Replace the placeholders
below with your own values and enable only the integrations you want to use.
The example file lists additional timeout, rate, concurrency and cache settings.

### Gemini

Set `LLM_MODE=rules` to run without a model provider. To use Gemini, choose one
of these authentication routes and set `GEMINI_MODEL` to a model available to
that account/project.

For the Developer API with an API key:

```dotenv
LLM_MODE=gemini
GEMINI_BACKEND=developer
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=your_available_model_id
```

For Vertex AI with Google Cloud credentials:

```dotenv
LLM_MODE=gemini
GEMINI_BACKEND=vertex
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=your_project_id
GOOGLE_CLOUD_LOCATION=global
GEMINI_MODEL=your_available_model_id
# Optional: point to an existing service-account JSON file on this machine.
# GOOGLE_APPLICATION_CREDENTIALS=C:/Users/YOUR_NAME/.agentcity/google-service-account.json
```

For local Vertex authentication, either set `GOOGLE_APPLICATION_CREDENTIALS` to
an existing service-account JSON file or leave it unset and use
`gcloud auth application-default login`. An explicitly configured missing file
must be corrected or unset before using the latter method. `GEMINI_API_KEY` is
used only with `GEMINI_BACKEND=developer`; it does not authenticate Vertex requests.
An explicit `GEMINI_BACKEND` takes precedence over `GOOGLE_GENAI_USE_VERTEXAI`.
See [backend Gemini setup](backend/README.md#gemini-and-optional-integrations)
for project permissions and authentication details.

`LLM_SESSION_TOKEN_BUDGET` defaults to `200000` and limits automatic citizen
decisions and optional background generation. Recorded token usage and conservative
charges for requests without usage metadata persist in `DATA_DIR` across restarts.
To permit more automatic requests, increase this setting in `backend/.env` and
restart; restarting alone does not reset recorded usage.

Explicit custom events use `LLM_EVENT_TOKEN_BUDGET` (default `100000`) for each
planning request, shared across its corrections and transport retries. Background
citizen usage cannot exhaust this allowance. All event usage is still recorded in
the same persistent usage totals; the request rate, concurrency and timeout limits
still apply. Changing either allowance requires restarting the backend.

Event planning makes up to three generation/correction attempts within one
85-second deadline, including queueing, authentication and bounded transport
retries. Gemini chooses reasonable unspecified parameters, lists its assumptions,
and validates every operation against the supported simulation changes. Partial
plans explain unsupported parts. Budget, authentication, quota and connection
failures show their cause and offer **Retry event**, manual composition or the
keyword catalog.

### ElevenLabs voices and narration

```dotenv
ENABLE_NARRATION=true
ELEVENLABS_API_KEY=your_api_key
ELEVENLABS_VOICE_ID=your_event_narrator_voice_id
ELEVENLABS_CHARACTER_VOICE_IDS=voice_id_1,voice_id_2,voice_id_3
ELEVENLABS_MODEL_ID=your_available_model_id
ELEVENLABS_OUTPUT_FORMAT=mp3_44100_128
```

Use existing voices and a model that your ElevenLabs account can access.
`ELEVENLABS_VOICE_ID` is the event narrator. `ELEVENLABS_CHARACTER_VOICE_IDS` is a
comma-separated pool of distinct voices assigned persistently to citizens for
dialogue and decisions. Supply one distinct voice per citizen you want voiced;
citizens without an available assignment cannot speak. Keep established voice IDs
in the pool so existing citizens retain access to their assigned voices.

`ENABLE_NARRATION` defaults to `false`. After enabling and restarting, select a
citizen or watch a conversation and click **Enable live voices** to hear new
dialogue. Use **Replay this conversation** for recorded dialogue, or
**Listen to this record** on supported events and decisions. If a reverse proxy
requires an explicit browser origin for audio URLs, set `NARRATION_PUBLIC_ORIGIN`
to that origin without a path; leave it unset for normal local use. See
[live voices setup and limits](docs/release/live-voices-handoff.md).

### Tiger Data

```dotenv
PERSISTENCE_MODE=local
TIGER_ENABLED=true
TIGER_DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=verify-full
TIGER_SCHEMA=agentcity_tiger
```

`TIGER_ENABLED` defaults to `false`. The adapter reads `TIGER_DATABASE_URL`;
`DATABASE_URL` is ignored. Use a TCP hostname and certificate-verified TLS, and
provision the configured schema with the required permissions. Local storage
remains authoritative, so keep `PERSISTENCE_MODE=local`. See
[Tiger database setup](docs/release/tiger-handoff.md#sql-credentials-and-configuration).

### Snowflake

```dotenv
SNOWFLAKE_ENABLED=true
SNOWFLAKE_ACCOUNT=your_account_identifier
SNOWFLAKE_USER=YOUR_SERVICE_USER
SNOWFLAKE_ROLE=YOUR_ROLE
SNOWFLAKE_WAREHOUSE=YOUR_WAREHOUSE
SNOWFLAKE_DATABASE=YOUR_DATABASE
SNOWFLAKE_SCHEMA=YOUR_SCHEMA
SNOWFLAKE_PRIVATE_KEY_FILE=C:/Users/YOUR_NAME/.agentcity/snowflake-key.pem
# Optional: set only when the private key requires a passphrase.
# SNOWFLAKE_PRIVATE_KEY_PASSPHRASE_FILE=C:/Users/YOUR_NAME/.agentcity/snowflake-passphrase.txt
SNOWFLAKE_CORTEX_MODEL=your_available_cortex_model
```

For automatic city trends and event observations, run the operator migration in
[`Snowflake observations setup`](docs/release/snowflake-observations.md), then set
`SNOWFLAKE_OBSERVATIONS_ENABLED=true`. The observation switch is independent of
the comparison switch above. `SNOWFLAKE_OBSERVATION_POLL_SECONDS=30` controls
background ingestion; the default is 30 seconds. Open **Simulation overview →
Observations**, or follow the observation link from a citizen or event report.
Graphs use recorded health, trust, relationships and beliefs, with evidence and
revision coverage. Event reports distinguish recorded links from changes during
the same interval.

`SNOWFLAKE_ENABLED` defaults to `false`; `ENABLE_SNOWFLAKE` is ignored. This
adapter uses key-pair JWT authentication. `SNOWFLAKE_PRIVATE_KEY_FILE` must point
to an existing PEM RSA private key on the machine running the backend. If set,
`SNOWFLAKE_PRIVATE_KEY_PASSPHRASE_FILE` must also exist and contain its passphrase.
The paths above are Windows examples; use absolute paths appropriate to your
machine. `SNOWFLAKE_PASSWORD`, `SNOWFLAKE_TOKEN` and `SNOWFLAKE_AUTHENTICATOR` are
not consumed. Provision the comparison schema and permissions described in
[Snowflake setup](docs/release/snowflake-handoff.md#configuration-and-database-setup).

### Running with custom settings

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

Choose **Introduce an event → Disaster type** for independent earthquake magnitude,
tornado wind/track, flood depth, fire heat, and storm controls. Committed damage
persists; the City condition panel exposes repairs and doorway debris clearing.
See [disaster rules and versioned API](docs/release/disaster-controls-handoff.md).
Optional original ElevenLabs effects, instrumental music and assigned-voice cries
use the shared sound mixer; each category is independently configured and disabled
by default. See [disaster audio setup and verification](docs/release/disaster-audio-handoff.md).

## Verify

```sh
npm test
npm run build
npm run test:e2e
```

`npm test` runs TypeScript, frontend unit/contract tests, backend tests, frozen contract verification and Ruff. Browser tests start isolated real backend processes and exercise the development proxy and built same-origin application. They use installed Chrome on Windows; on other systems install Playwright Chromium with `npm --prefix frontend exec -- playwright install chromium`. `PLAYWRIGHT_CHANNEL` can select an installed compatible browser. Browser tests use separate data directories under `backend/.tmp/`.

See [the release validation report](docs/release/validation-report.md) and [shared dev log](docs/dev-log.md) for dated evidence and limitations. Gemini supports Developer API or Vertex AI configuration; [prior live Vertex application verification](docs/vertex-integration.md) is documented separately from the default mocked provider tests. Optional [Tiger ingestion](docs/release/tiger-handoff.md) keeps local storage authoritative and has passed real SQL verification. [Snowflake comparisons](docs/release/snowflake-handoff.md) are wired into the default app; real SQL/Cortex verification still needs schema privileges. [ElevenLabs narration](docs/release/narration-handoff.md) supports recorded events, decisions and dialogue through the existing API and browser playback. All three adapters are disabled by default and require server-side configuration. [Vultr deployment preparation](deploy/README.md) is supplied; live hosting remains unverified.
