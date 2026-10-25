# Machine A combined release verification

Date: 2026-10-24, America/New_York. **The three-service hosted release is not ready.**
Machine A's Tiger implementation and available Machine B integration are functional;
remaining gates require C's narration branch, Snowflake privileges and authorized
Vultr/HTTPS access. There are no remaining failures in the completed automated gates.

Application code: `c724845a85368660fb5d13347bf76e9f5883f219`.
Final test tree: `0f6b3a9909aaf6babf69165fbf0acc0fa9ec302d` (adds source-deletion/
actual-restart assertions without changing application code). Evidence-only report
commits follow. Starting dev was `2d22559368ffede1d0a5e500c487541a0120dda2`.
All source changes remain on `codex/tiger-release-integration`; dev was not pushed.

## Provenance and environment

- Normally merged Machine B `37c5fbc9064805fa98c810cfebb2c0004ce511ea`, containing
  implementation `ef0aae2bc0e7519bc942a0252a50e099c8b6091b`. Shared default-app and
  frontend wiring was applied in `c724845`; no older shared files were substituted.
- Verified ancestors: A security `2c39cdb`, C maintenance `f08b328`, B scenario
  `9e68329` / `fceecf9`, and skyline `28dee4f`. No scenario/provider implementation
  or frozen core contract changes were made by this release integration.
- Windows, Python 3.13.1, Node 22.23.2, npm 12.2.0, Chrome 155.0.8059.86,
  Playwright 1.64.1; local TLS SQL server PostgreSQL 18.6.
- Fresh frontend `npm ci`; isolated Python environment at
  `backend/.tmp/tiger-release-venv`, installed from committed `requirements.lock`.
  `pip check` passed. npm noted a blocked esbuild install script; the actual
  TypeScript/production build executed successfully with the installed binary.
- Ordinary checks use rules mode, disabled vendor adapters and disposable stores.
  Browser runs used test-only `CHOKIDAR_USEPOLLING=1`, installed Chrome and one
  Playwright worker. Both final core-browser stores contained **zero simulations**
  after fixture cleanup. Preferences and created profiles are restored/removed
  in `finally`, including on failure. Settings cases also retain their own isolation.
- Live Tiger checks explicitly received the existing server connection in memory;
  only random disposable schemas were created/dropped. No credential value, vendor
  exception body, token or account identifier is included in this evidence.

## Executed gates

Commands use the repository root unless `backend`/`frontend` is specified.
`PY` below is the isolated locked environment's `Scripts/python.exe` on this
Windows machine; `AGENTCITY_PYTHON` was set to its absolute path for `npm test`.

| Gate | Exact command | Actual result / application evidence |
| --- | --- | --- |
| Clean frontend lock install | `npm --prefix frontend ci` | Passed; 176 packages added, zero audit vulnerabilities. |
| Clean backend lock install | From backend: `.venv/Scripts/python.exe -m venv .tmp/tiger-release-venv`, then `PY -m pip install -r requirements.lock` | Passed; `PY -m pip check` passed. |
| Full frontend/backend/contracts/lint/format | `npm test` | Passed on final test tree `0f6b3a9`: frontend **150 passed**, backend **351 passed / 2 opt-in skips** in 185.93 seconds, 43 hashes/DTO/OpenAPI/stream match, Ruff lint and all 90 Python files formatted. |
| Production build / TypeScript | `npm run build` | Passed on `c724845`; existing third-party Rollup PURE-comment warnings only. |
| Full dependency audit | `npm --prefix frontend audit --json` | Zero findings. |
| Production dependency audit | `npm --prefix frontend audit --omit=dev --json` | Zero findings. |
| Full core browser | `CHOKIDAR_USEPOLLING=1 npm run test:e2e` | **26 passed**, 0 failures/skips/flaky, 106.83 seconds on `c724845`. Includes 7 Settings cases, production-origin HTTP/WebSocket, fallback/save/navigation and 30/100-agent rendering. |
| Snowflake browser / default History wiring | From frontend: `CHOKIDAR_USEPOLLING=1 node node_modules/@playwright/test/cli.js test --config playwright.snowflake.config.ts` | **3 passed** in 13.1 seconds on `c724845`; only external Snowflake HTTP is controlled. Third case uses the production History dialog, both extension routes, capability and exact displayed values. |
| Focused merged T/S/backup cases | From backend: `PY -m pytest tests/test_snowflake_comparison.py tests/test_tiger.py tests/test_store_backup.py` | **50 passed / 2 opt-in skips**. Both route-index assumptions in B's tests were adapted to the shared child; blocked-vendor/cancellation assertions remain. |
| Source deletion and real local restart | From backend: `PY -m pytest tests/test_release_exports.py tests/test_tiger.py::test_t03_branch_identity_lineage_and_source_deletion` | **3 passed**, including an actual reopened repository/app after source deletion, in `0f6b3a9`. |
| Real local SQL / restricted role | From backend: `PY -m scripts.tiger_local_postgres --bin 'C:\Program Files\PostgreSQL\18\bin'` | **2 passed / 18 deselected** in 8.68 seconds on `c724845`; disposable verified-TLS cluster, non-superuser and not database owner. |
| Live Tiger SQL / configured application | From backend: `PY -m pytest tests/test_tiger.py -k real_postgres -rs`, with `TIGER_TEST_DATABASE_URL` injected in memory from the supplied connection | **2 passed / 18 deselected** in 16.67 seconds on `c724845`. Real migrations/upserts/exact rows, branch keys, public worker/status, restart progress and query deadline verified. |

The two skips in default backend runs are precisely the opt-in real PostgreSQL
tests; both were executed successfully against local PostgreSQL and real Tiger
separately. They are not missing offline assertions or counted as ordinary passes.
The complete backend run also covers security/context/deadlines, startup/recovery,
writer ownership, cancellation accounting and scenario/domain regressions.

## Acceptance matrix

| Cases | Executable evidence | Result / limits | Owner |
| --- | --- | --- | --- |
| T-01 | `test_tiger.py::test_t01_exact_committed_records_and_no_initialization_placeholders`, metric-version test, both opt-in SQL tests | Passed; exact metric/decision/event/movement payloads, totals and source revisions. Same-tick metric versions remain available for earlier pins. | A |
| T-02 | Duplicate/lost-ack test and real SQL migration/upsert test | Passed; repeated delivery/read-back remains identical, no duplicate rows/aggregates. | A |
| T-03 | Branch identity/source-deletion test and live public-worker branch test | Passed; inherited IDs are simulation-scoped and lineage is retained. | A |
| T-04 | External commit before local cursor / restart, corrupt-cursor replay, live public-worker restart | Passed; persistent cursors reconcile committed history without skipping. | A |
| T-05 | Failed manifest, blocked database, outage recovery and projection-budget tests | Passed; failed local revisions excluded; event-synchronized blocked database leaves HTTP controls/ticks usable; lag/errors truthful; retry/projection bounds enforced. | A |
| T-06 | Child auth/ownership/validation/write-envelope tests, combined schema snapshot, local/live SQL tests | Passed; authenticated sanitized status, canonical keys, CSRF/Origin, separate documented schema, TLS SQL execution. | A |
| S-01–S-05 | `test_snowflake_comparison.py` (31 cases including default-app wiring) | Passed with controlled external transport; exact data, pinned citations, bounds, retry/gate and cancellation checked. | B + A wiring |
| S-06 | `snowflake-e2e/snowflake.spec.ts` (3 cases) | Controlled browser passed. Real SQL/Cortex remains unverified; B's live attempt was rejected for schema privileges. | B / operator |
| N-01–N-07 | C branch/handoff unavailable | Blocked; no adapter claimed. Narration remains disabled/501. | C |
| M regressions | Full backend/frontend plus `settings.spec.ts`, dependency validation, provider deadlines, stream authorization/context and domain cases | Passed on the combined application. | A verification |
| R-01 | `test_flows.py`, full browser create/flood/outcome/history/replay/branch flow | Passed locally in rules/disabled modes, ten agents explicit. | A |
| R-02 | `test_release_exports.py` pinned JSON/CSV/metrics/state test | Passed through head changes and restart. | A |
| R-03 | Extended branch export test, Tiger branch test, durability suite | Passed after source deletion and actual app restart; physical garbage collection is not claimed. | A |
| R-04 | All 26 core browser cases and isolated fixture cleanup | Passed; fallback/save/navigation, preferences and no leftover cities. | A |
| R-05 | Local session/Origin/CSRF/socket-revocation/second-writer tests; same-origin built browser | Local coverage passed; deployed HTTPS/proxy/media remains unverified. | A / host operator |
| R-06 | `test_store_backup.py`, durability/recovery tests; deployment runbook | Local stopped-store restore preserves exact branch/source states and refuses overwrite/live writers. Host restart/restore/rollback drill unverified. | A / host operator |
| R-07 | Both benchmark commands below | Measured 10/30/100 and a configured 100-tick completion under blocked Tiger. Full 10,000-tick endurance and hosted SLO unverified. | A |
| R-08 | Two real Tiger tests; B live smoke report | Tiger passed separately. Combined live services blocked by Snowflake privileges, missing narration and host access. | A/B/C/operator |

## Failures found and repaired

The initial full browser run was **22 passed / 4 failed**, not a release pass.
The failures were an all-buttons citizen count that included the new hide button,
the old fixed-ten/read-only population expectation, and two obsolete population
spinbutton selectors. Tests now target the real citizen focus buttons and supported
population slider, explicitly choose ten, and verify restoring an 80-person draft.
A follow-up closeup run exposed intentional low-zoom speech suppression; the test
now zooms to a readable scale before checking both unselected speakers and their
non-overlapping layout. Dialogue completion, mobile, movement and all earlier
behavioral assertions remain in place. Final full browser results are above.

The first backend run was **318 passed / 1 failed / 1 skipped**. The unique-evacuee
lesson test selected an eastern hazard containing every shelter on the current
seeded map. Its fixture now uses the default hazard, which deliberately leaves a
safe facility, while preserving the exact unique-citizen sentence assertion.
The existing city-layout test received Ruff-only formatting. No scenario behavior
or frozen assertion was changed. Merging B also exposed two tests assuming the
integration mount was `app.routes[0]`; these now use `app.state.integrations` and
retain all concurrency/cancellation checks. One new History-browser selector was
corrected against its rendered accessible name before the final 3-case pass.

## Measured performance

Commands, from backend using the isolated lock:

```text
PY -m scripts.benchmark --steps 30 --live-ticks 10 --output artifacts/tiger-release-performance.json
PY -m scripts.benchmark --steps 90 --live-ticks 10 --horizon 100 --blocked-tiger --output artifacts/tiger-release-outage-performance.json
```

Application `c724845`; rules mode, disposable storage. These are local measurements,
not a hosted SLO. Step/control latency includes the driver's control-version read.
Memory is the cumulative peak working set of the app plus test-driver process.
Disk is actual persisted store bytes, rounded to MiB. The two workloads have
different history lengths; their difference is not a causal vendor-overhead estimate.

| Workload | Agents | Step p95 ms | Control p95 ms | Live ticks/s (target 2) | Peak MiB | Store MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 40 ticks, vendors disabled | 10 | 79.72 | 58.03 | 1.90 | 101.84 | 5.29 |
| 40 ticks, vendors disabled | 30 | 164.49 | 108.75 | 1.87 | 134.82 | 8.68 |
| 40 ticks, vendors disabled | 100 | 426.72 | 240.14 | 1.84 | 212.07 | 20.37 |
| Complete configured 100 ticks, blocked Tiger fake | 10 | 96.72 | 77.18 | 1.88 | 112.27 | 12.36 |
| Complete configured 100 ticks, blocked Tiger fake | 30 | 215.50 | 141.39 | 1.86 | 162.82 | 20.75 |
| Complete configured 100 ticks, blocked Tiger fake | 100 | 539.85 | 335.55 | 1.76 | 293.13 | 53.79 |

Both raw result files are in `backend/artifacts/`. All decisions used rules; paid
provider calls and provider queue depth were zero. Blocked-Tiger runs completed
at tick 100 and honestly reported 119 revisions of lag, with bounded outage logs.
Disabled runs report disabled integration (their unprocessed revision count is
not an operational outage). No HTTP operation failed in these benchmark drivers.
The 100-agent long-history run falls below the nominal 2 ticks/s cadence. No
performance threshold was agreed in the assignment, so no unsupported performance
pass is asserted. Do not extrapolate this short configured horizon to 10,000 ticks;
growing full-state retention needs a separate endurance/space gate.

## Remaining release actions

1. C must publish `codex/elevenlabs-narration` and its handler/router/dependency
   handoff. A then merges normally, updates capability/core handler/shared audio
   route, and executes N-01–N-07 plus combined gates. No ElevenLabs key/voice was
   configured in the inspected environment. No live audio is claimed.
2. An authorized Snowflake operator must supply usable schema privileges/runtime
   grants. B's reported live smoke reached HTTP 422 / insufficient privileges at
   disposable schema creation; setup, MERGE/read-back and real Cortex were not
   reached. That is B-branch evidence, not a fresh live rerun here. Rerun the explicit
   `node scripts/snowflake-live-smoke.mjs --live` only with authorized access.
3. Provide an authorized Vultr host/hostname and exercise the prepared
   [deployment runbook](../../deploy/README.md): HTTPS/session/socket checks,
   supervised restart, separate-directory restore and rollback. No billing, DNS,
   IAM, firewall or infrastructure changes were made by A.
4. Review/merge the published integration branch through a normal verified merge
   into current dev after the missing service/host gates. Do not force-push dev.

Automatic approval review rejected removal of one stopped disposable PostgreSQL
bootstrap folder with the reason “blocked by policy.” The leftover folder is
`C:\Users\andre\AppData\Local\Temp\agentcity-tiger-pg-4zona6k3`; that test server was
stopped, and later disposable SQL runs shut down normally. It has no application
or credential dependency and does not invalidate the passing SQL checks.
Review also rejected deletion of generated browser screenshots; those files are
retained with the validation artifacts instead of being removed.
