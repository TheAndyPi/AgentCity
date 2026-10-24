# AgentCity integration handoff

Verified on 2026-10-24 on Windows with Node 22.23.2, Python 3.13 and Chrome.
Both applications are integrated together on the `main` branch, including the
live loading, city ground, persistence recovery and repository ignore fixes.
No public deployment was performed.

## Run

From the repository root:

```sh
npm run setup
npm run dev
```

The live interface is at http://127.0.0.1:5173; FastAPI is at
http://127.0.0.1:8000. The launcher checks readiness and connects Vite's HTTP and
WebSocket proxy to the selected API port. Ctrl+C stops its own child processes.
`PORT` and `FRONTEND_PORT` select alternative ports. Existing listeners are
reported rather than terminated.

`npm run build` followed by `npm start` serves the built client, API and WebSocket
on http://127.0.0.1:8000. Direct client-route reloads work. API failures and missing
assets retain their proper error responses. Static files cannot escape the
configured build directory. The static route is excluded from the frozen API.

Defaults use local authentication, local durable storage and deterministic rules.
The root launchers load optional `backend/.env` as configuration, with process
environment taking precedence. Provider secrets are never frontend variables.
`npm run dev:mock` is explicit fixture review with a visible Mock badge. Live
failures never switch the application to recorded data.

## Contract and integration corrections

All four supplied documents were used: Shared Contract, Backend Prompt,
Architecture and Prompts, and Frontend Prompt. Their marked shared contract
blocks match each other and the frozen 1.0.0 contract. No file under
`contracts/v1/` was edited. The raw frozen `CONTRACT.md` SHA-256 remains
`680a2d768e3e2f1fb8625cbe278adca31d94223335e4240792e58e8d66c7f95f`.

- Zod now matches request defaults, complete response fields, UTC timestamps,
  names, IDs, canonical shortcut codes and scenario bounds. Growing recorded
  history no longer inherits the 100-item request-selection limit. All 32 frozen
  shared acceptance/rejection fixtures run against both implementations.
- Live writes obtain a CSRF token even when the user acts before application
  bootstrap completes. Expired authenticated sessions reopen the login dialog.
- Stream handling rejects late frames and errors from an obsolete connection,
  in addition to stale revisions and obsolete world generations. Real REST
  polling takes over after repeated connection failures and yields to a recovered
  WebSocket without discarding the last valid world.
- Live inspector, decision, event, feed, overview and comparison queries retain
  their content during background refreshes instead of flashing a loading screen
  on every tick. Delayed responses still update the same resource without
  rewinding newer data. Switching citizens, worlds or replay revisions clears the
  previous selection immediately. Citizen collection requests use the displayed
  detail's committed revision.
- Replay excludes initialization revisions that have no WorldFrame. Branch
  navigation resets save guards so browser Back saves and pauses the new source.
- Scenario previews use the backend map dimensions. Stale controls can obtain a
  fresh preview while retaining the user's text; cancelling an obsolete editor
  preserves current playback. Failed refreshes leave retry controls available.
  Invalid prose severity/duration returns a contract-shaped validation error.
- Backend templates cover the UI's shortage, warning, festival and policy
  experiments. Suggested storm, warning and aid-drive phrases compile to actual
  supported effects. Compilation remains bounded and its preview says so.
- Outcome values show useful precision, tiny changes do not misleadingly round
  to signed zero, absent lessons are explicit, density overlays share the same
  backend inputs, and the engine label distinguishes rules from configured Gemini.
- City ground now uses grass and asphalt textures, sidewalks, curbs, crossings and
  building entrance paving in both 3D and 2D. Street geometry comes from the actual
  backend terrain cells. Textures are generated locally, without network asset
  loading. Navigation prefers roads (cost 1) over walkable lawns (cost 4), while
  preserving obstacles, speed bounds, destination access and detours. Existing
  recorded map geometry and historical paths are preserved.
- New city maps develop every block with two to four non-overlapping buildings,
  including two lots along the narrow waterfront. Default urban settings produce
  240 buildings; fresh setup defaults to 80 citizens and density 75. Homes,
  workplaces and shops retain their existing simulation kinds, with restaurant,
  market, apartment, townhouse and office names. Height ranges vary by purpose.
  Building interiors remain blocked and all entrances connect to public roads.
  Saved cities and setup drafts retain their original layout/population/settings.
- Buildings use purpose-specific instanced facades: apartment setbacks/balconies,
  office glazing, shop and restaurant awnings, pitched neighborhood roofs and
  hospital crosses. Hover or tap in 3D reveals a single purpose/name/capacity tag;
  2D supports hover, tap, keyboard focus and Escape. Geometry is retained between
  occupancy updates, and arbitrary polygon footprints are preserved.
- Applying the update exposed slow startup with a longer saved city. Recovery now
  verifies every unique object's checksum and journal reference, fully validates
  restored heads, and fully validates historical State objects on demand, without
  constructing and discarding every historical Python object graph. Launchers
  allow five minutes for readiness. The active city was saved and paused before
  restart, then its saved snapshot and historical reads were checked after restart.
  The backend ignore rule was also narrowed to `/data/`, so the `app/data/`
  persistence source is included in Git while runtime city data remains ignored.

## Final verification

| Check                                                | Result                                                      |
| ---------------------------------------------------- | ----------------------------------------------------------- |
| Fresh documented setup                               | Passed; locked Python install and frontend `npm ci`         |
| TypeScript, including Playwright tests/configuration | Passed                                                      |
| Frontend unit/contract tests                         | 81 passed                                                   |
| Backend tests                                        | 127 passed in 99.80 s                                       |
| Frozen contract gate                                 | 36 file hashes plus DTO, OpenAPI and stream equality passed |
| Ruff lint and format checks                          | Passed; 52 Python files formatted                           |
| Production build                                     | Passed                                                      |
| Real Chrome browser tests                            | 13 passed in 107.1 s; no skips, flaky tests or failures     |
| Git whitespace/error check                           | Passed                                                      |

Run the same verification with `npm test`, `npm run build`, then
`npm run test:e2e`. Browser tests launch isolated local backend processes and use
separate data directories under `backend/.tmp/`. Windows uses installed Chrome;
other hosts can install Playwright Chromium as described in the root README.
Only the current Windows environment was exercised.

The earlier intermittent initialization timeout recurred during the denser-city
update. A separate full browser run also reached a degraded persistence store.
A disposable save stress test then captured `[WinError 5] Access is denied` at
`os.replace(manifest.json.tmp, manifest.json)` after 53 publications. Atomic saves
now retry only Windows rename errors 5, 32 and 33, with six exponential delays
totaling at most 1.26 seconds. They reuse the same fsynced temporary file, retain
the previous commit until success, and still halt writes on persistent failure.
Disk-full and other errors fail immediately. Fault tests cover successful retry,
exhaustion, unchanged durable/in-memory metadata and non-retryable errors. A fresh
2,000-publication stress run passed. No test deadlines or assertions were weakened.

The browser suite also checks a real 80-citizen, 240-building city, multiple
buildings per block, hover tags on several 3D building kinds, restaurant hover in
2D, hospital keyboard focus and Escape dismissal. Screenshots include
`dense-city-3d.png` and `dense-city-2d-purpose-tag.png`.

The browser suite exercises real creation and staged initialization, initial
flood preview, queued confirmation, stepping/streaming, citizen inspection,
measured reports, acknowledgment, pre-event undo, durable saved history, replay
and continued branches. It also checks lost-response idempotent retry, a pause
from another tab invalidating a preview, running/paused editor cancellation,
three failed sockets followed by REST polling and WebSocket recovery, and a
failed navigation save retaining the city until the same operation succeeds.

The inspector refresh regression deliberately delays detail responses beyond
several ticks and delivers them out of order. It verifies uninterrupted content,
the selected tab remaining mounted, continued detail updates without revision
rewinds, and isolation when switching citizens or historical revisions.

At 390px it verifies settings, light/reduced-motion preferences, setup-draft
retention, profile creation/copy isolation/edit/delete, and archive/exact-name
deletion. Both 30- and 100-citizen running worlds render with real WebGL and
retain selection/inspection after forced context loss switches to 2D. A separate
test verifies the built application's same-origin HTTP, WebSocket and deep reload.
Fault tests inject transport failures around real backend responses; they do not
replace the simulation with fixture state.

Recorded evidence:

- `backend/artifacts/test-results.xml`: final 127-test JUnit report.
- `frontend/artifacts/integration/playwright-results.json`: final browser report,
  timings and running-world render measurements.
- `frontend/artifacts/integration/live-request-response.json`: actual UI mutation
  requests and backend responses, omitting authentication headers/cookies.
- `frontend/artifacts/integration/screenshots/`: full-resolution live preview,
  outcome, inspector, mobile, built application and 30/100-citizen evidence.

Short Chrome headless samples at 1440×900 measured 155.8 FPS for 30 citizens and
163.0 FPS for 100 while running, using the real local backend. These are local
render observations rather than universal performance guarantees. The prior
backend cadence/storage measurements remain in `backend/artifacts/performance.json`.
The Three.js/Fiber/Drei bundle is approximately 305.5 KB gzip, loaded separately.

## Remaining limitations

- Gemini's gateway exists and provider failure paths are tested, but no account
  key/model was supplied and no live Gemini request was made. Only persona and
  decision generation currently use that optional provider. Other simulation
  reasoning, dialogue and social mechanics use labeled rules.
- PostgreSQL/Tiger Data, Snowflake and ElevenLabs adapters are unavailable.
  Capabilities report local persistence, `snowflake=false` and `narration=false`.
  Unsupported narration returns 501 and PostgreSQL configuration fails clearly.
  Local history, branching, inspection and export work without these services.
- Scenarios use a keyword compiler with exact previewed effects and unsupported
  notices; arbitrary prose does not define new physics. Missing provider token
  metadata makes the affected usage endpoint explicitly unavailable instead of
  fabricating totals or prices.
- Full revision objects retain growing audit history. Long 10,000-tick runs,
  prolonged high speeds, retention/compaction and production storage operations
  still need endurance testing. Logical deletion does not reclaim all objects.
  Follow `backend/operations.md` for backup and recovery.
- Public HTTPS/session hosting and a Vultr deployment were not rehearsed here.
  Backend tests cover cookie/CSRF/owner/origin enforcement; the live browser suite
  uses loopback local mode. Formal screen-reader/accessibility certification and
  broader device testing remain release work.

The current local application has no known failing integration check. The older
frontend/backend handoffs document their independent baselines; this handoff
supersedes their previous statements that the opposite application was absent.
