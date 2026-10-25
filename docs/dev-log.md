# Shared development log

Read this file and [the release handoff](release/integration-handoff.md) before
starting an integration. Dates use America/New_York. Entries distinguish code
inspection, earlier branch evidence, and tests rerun on the merged application.

## 2026-10-24 - Twelve-hour release handoff

### Verified remote baseline

Fetched `origin/dev`; latest application commit observed is
`560e2eda691c5fdbffe4d5d39b8153ddb2f123e5`, authored by
**Codex (Machine C)** at **22:20:15 EDT**. The clean local dev checkout was
fast-forwarded to that commit. This confirms commit authorship and included
changes; it does not prove that Machine B has finished every task on its machine.

Included work:

- Machine C's `f08b328`: patched frontend dependencies, Zod v4 compatibility,
  Settings operation/retry lifecycle, finite lesson-provider deadlines, shared
  credential-worker lifetime, seven Settings browser cases and eleven dedicated
  provider cases, plus validation tests and evidence.
- `ff83662` and `560e2ed`: integration with newer dev and Machine B's work.
- Machine B's `9e68329`: list negation, unique citizen counts, construction
  wording and whole-word regions.
- Machine B's `fceecf9`: scenario interpretation/clarification. Unknown premises
  may now require the user to restate the request instead of accepting an abstract
  landmark. Preserve `can_commit`, warnings and unsupported notices.
- `28dee4f`: cyberpunk city/skyline rendering, addresses, buildings and population
  controls. Inspect current accessible labels and defaults; older handoff text
  and assertions about a fixed ten-person setup or 80-person default are stale.
  The inspected `defaultConfig` remains ten citizens/suburb; the UI now allows
  population changes up to capabilities. Demo tests must set population explicitly.

### Evidence boundary

Machine C's [report](reviews/machine-c-maintenance-2026-10-24.md) records green
maintenance-branch unit/build/contract checks, zero audit findings, seven Settings
browser passes, and a broader **18-pass/8-failure** browser run using test-only
polling. Its final merge was checked for syntax/conflicts/lock consistency but
**the merged application was not fully retested by Machine C**. Earlier counts
are historical evidence, not a release sign-off. Run the validation assignment.
The eight broad-browser failures and retention/endurance work were outside C's
maintenance scope; do not assume they were fixed by that merge.

### New assignments

| Owner | Branch | Assignment |
| --- | --- | --- |
| A / coordinator | `codex/tiger-release-integration` | [Tiger Data, deployment, coordination, release verification](prompts/machine-a-tiger-release.md) |
| B / analytics | `codex/snowflake-comparison` | [Snowflake ingestion and one grounded comparison](prompts/machine-b-snowflake.md) |
| C / narration | `codex/elevenlabs-narration` | [ElevenLabs using existing narration/playback](prompts/machine-c-elevenlabs.md) |
| Final validator | `codex/release-validation` | [Maintenance and functional release validation](prompts/release-validation.md) |

These are written assignments, not claims that chats have been launched or that
implementation has started. B's new assignment intentionally excludes scenario
fixes. A coordinates shared files, lockfiles, extension wiring and final merges.
All machines must add automated functional tests, not just a handoff description.

### Non-negotiable integration facts

- Local persistence remains authoritative; Tiger/Snowflake are optional read
  models. No vendor request or retry may hold the simulation writer lock.
- Keep one backend worker, default one concurrently running city, and the
  supported 10-100 population range. Multiple viewers do not imply multiple
  simulation owners. Do not deploy a multi-worker Gunicorn recipe unchanged.
- Preserve Machine A's session/WebSocket revocation, privacy/context freshness,
  cancellation-safe usage accounting, and Machine C's credentials/deadlines.
- Do not edit `contracts/v1/**` or core DTOs. The contract checker compares the
  **entire** core OpenAPI document: merely adding a normal parent-app route breaks
  it. Use the explicitly documented integration sub-application seam; do not hide
  routes or regenerate snapshots to obtain a pass.
- Existing narration POST is a 501 stub; playback already exists in
  `frontend/src/components/Narration.tsx`. A configured key alone is not an adapter.
- Existing `.env.example` has optional credential placeholders that the current
  app does not consume. Each implementation must document actual configuration.
- Snowflake must consume pinned existing exports directly and work independently
  of Tiger Data. Its summaries describe recorded differences, not causal proof.
- Use server-side credentials only; never log or commit `.env`, service-account
  keys, database connection secrets, cloud tokens or audio access tokens.
- Mock-based failure tests and real service verification are separate evidence.
  The validator must report an unavailable live test as unverified, not passed.
- Windows browser runs previously hit Vite watcher `EBUSY` on generated images.
  Test-only `CHOKIDAR_USEPOLLING=1` avoided that crash. Fix test setup/cleanup and
  current selectors; never remove behavioral assertions to green the suite.

Append an entry per handoff with commit, files, new configuration names (no
values), tests, known failures and the next machine's required action. Do not
rewrite another machine's historical evidence or push over its work.

### Handoff verification on the merged application

The assignment-writing task reran these checks on application `560e2ed`, with
only documentation and two new export acceptance cases added:

| Check | Actual result |
| --- | --- |
| Clean frontend lock install | `npm --prefix frontend ci` passed; installation audit reported zero vulnerabilities. |
| Frontend unit/consumer tests | `npm --prefix frontend test`: **147 passed**. |
| Production build/TypeScript | `npm run build`: passed. |
| Focused backend | `test_release_exports.py`, `test_lesson_provider_deadlines.py`, `test_simulation_correctness.py`: **61 passed**, no failures/skips. |
| Settings browser acceptance | `settings.spec.ts --reporter=line`, test-only `CHOKIDAR_USEPOLLING=1`: **7 passed**. |
| Core contract | All **43 frozen hashes**, DTO, OpenAPI and stream snapshots match. |
| New Python tests | Ruff lint and format checks passed. |
| Handoff links/diff | Local documentation links and `git diff --check` passed. |

New executable coverage in `backend/tests/test_release_exports.py` verifies
JSON/CSV/metrics/state consistency at a pinned revision across head advances and
restart, plus branch export identity and read-back after source deletion. It does
not assert physical garbage collection. Tiger/Snowflake/ElevenLabs cases are
written as required acceptance specifications; their machines must implement
the actual adapter tests alongside code. No external integration is claimed
complete from these specifications. This task did not rerun the full backend or
full browser suite and made no live vendor calls or deployment changes.

## 2026-10-24 — Machine B Snowflake comparison handoff

Implementation: `ef0aae2bc0e7519bc942a0252a50e099c8b6091b`, branch
`codex/snowflake-comparison`, based on fetched `origin/dev` at `2d22559`.
See [the Snowflake handoff](release/snowflake-handoff.md) for API/schema, SQL setup,
configuration, bounded Cortex selection, retry/crash policy and exact commands.

Delivered isolated `backend/app/snowflake/**`, a runnable real-core composition,
versioned bound SQL, durable separate request/model-budget ledger, a service-specific
frontend client/schema/component, controlled external HTTP fixtures, 30 backend
acceptance tests and two browser cases. JSON inputs come from the existing owned
export implementation at explicit revisions. Source/branch keys and citations
include simulation/revision identity; numeric differences come from verified
read-back. No Tiger dependency or scenario/lesson/provider/settings changes.

Actual results on this branch:

- Focused Snowflake backend: **30 passed** in 45.21s. Covers S-01–S-05, literal
  fixture deltas, inherited IDs, missing records, every citation resolving at its
  pinned revision, pending/completed/changed retries, response loss and restart,
  cost limits, blocked-vendor ticking, caller cancellation, SQL asynchronous
  polling/output bounds, key-pair signing and independent OpenAPI snapshot.
- Browser S-06 with the real composed application route and only the external
  Snowflake HTTP transport faked: **2 passed**. Displayed values match returned
  records, response-loss retry keeps the same key/body/result, disabled UI makes
  no integration request. This does not verify the default shared entry point.
- Frontend unit/consumer: **150 passed**; production build/TypeScript passed.
  All **43 core contract hashes**, DTO, parent OpenAPI and stream snapshots match.
- Ruff lint passed across backend; changed Python files pass Ruff format.
  Full format gate reports untouched `test_city_layout.py:96`.
- Full backend run: **325 passed, 1 failed** in 153.64s, collected before the final
  five Snowflake cases were added. The failure is
  `test_domain.py::test_repeat_evacuations_count_each_citizen_once`, `StopIteration`
  finding an unexposed shelter at line 449. Reproduced on an isolated untouched
  `git archive origin/dev` with no Snowflake files. Scenario fixes are excluded.
- Live opt-in SQL API smoke: **unverified**, HTTP 422 / insufficient privileges
  when creating the unique disposable schema. Key files/config existed, but real
  table setup/read-back and Cortex were not reached. No production cleanup or
  real Cortex success is claimed. `node scripts/snowflake-live-smoke.mjs --live`
  is the explicit rerun command after the operator grants suitable schema access.

New consumed server configuration names: `SNOWFLAKE_ENABLED`, `SNOWFLAKE_ACCOUNT`,
`SNOWFLAKE_USER`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`, `SNOWFLAKE_WAREHOUSE`,
`SNOWFLAKE_ROLE`, `SNOWFLAKE_PRIVATE_KEY_FILE`,
`SNOWFLAKE_PRIVATE_KEY_PASSPHRASE_FILE`, `SNOWFLAKE_CORTEX_MODEL`. Values remain local.
Existing pinned dependencies suffice; no shared manifests or locks changed.

**A's next action:** apply the checked
[minimal wiring patch](release/snowflake-wiring.patch) to coordinator-owned main,
capability and existing ComparePanel entry points; compose Tiger/narration routes
on the same child app, provision the dedicated runtime schema/grants, rerun real
SQL/Cortex smoke and combined public application gates. The branch provides
`app.snowflake.application:create_app` for executable adapter/browser evidence;
normal `app.main:app` wiring and full release acceptance are not claimed complete.
