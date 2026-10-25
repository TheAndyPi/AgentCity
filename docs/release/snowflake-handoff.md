# Snowflake comparison handoff — Machine B

Date: 2026-10-24 (America/New_York). Base: `origin/dev` at
`2d22559368ffede1d0a5e500c487541a0120dda2`, fetched before starting.
Branch: `codex/snowflake-comparison`. Implementation commit: `ef0aae2bc0e7519bc942a0252a50e099c8b6091b`.

## Delivered and integration boundary

New modules in `backend/app/snowflake/` implement the reserved
`POST /api/v1/integrations/snowflake/comparisons` extension. The runnable composition
is `app.snowflake.application:create_app`; it wraps the real core application,
including its existing authentication, exports, storage, controls and SPA serving.
It does not replace core DTOs, lesson/scenario behavior, provider deadlines,
Machine C's dependencies or the Settings lifecycle. No Tiger Data dependency exists.

The coordinator-owned default entry point, capability value and ComparePanel have
**not** been edited. A must apply [snowflake-wiring.patch](snowflake-wiring.patch),
which passed `git apply --check`, before claiming default-app integration. The patch
adds two backend imports, configuration, the capability value and installation
before the SPA, plus two UI imports and a component using the existing branch
selection. It leaves the existing chart present when disabled. No lock changes
are needed: `httpx` and `cryptography==50.0.2` already exist in the backend lock.

```sh
git apply --check docs/release/snowflake-wiring.patch
git apply docs/release/snowflake-wiring.patch
```

`install_snowflake(app, config)` exposes its child at `app.state.integrations`.
A can register Tiger/narration extension routes on that same child before serving;
do not mount a second competing application at the same prefix. The helper wraps
the parent's lifespan so active comparisons finish before transports/receipts close.
For development before A's merge, run from `backend/` with environment loaded:

```sh
.venv/bin/uvicorn app.snowflake.application:create_app --factory --workers 1 --host 127.0.0.1
```

This composition serves the extension but deliberately leaves the core Snowflake
capability false until A applies the patch. The production UI entry point is the
existing ComparePanel in both History and the simulation Drawer after that patch.
The browser acceptance HTML is a test harness, not a production route registration.

## Configuration and database setup

Server-only variables actually read:

| Name | Meaning |
| --- | --- |
| `SNOWFLAKE_ENABLED` | Explicit `true` enables the adapter; default false. |
| `SNOWFLAKE_ACCOUNT` | Account host identifier without scheme/suffix. |
| `SNOWFLAKE_USER` | Snowflake service user; JWT subject uppercased. |
| `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA` | Dedicated read-model namespace. |
| `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_ROLE` | Operator-controlled execution context. |
| `SNOWFLAKE_PRIVATE_KEY_FILE` | PEM RSA private key file; relative to backend working directory. |
| `SNOWFLAKE_PRIVATE_KEY_PASSPHRASE_FILE` | Optional file containing key passphrase. |
| `SNOWFLAKE_CORTEX_MODEL` | Default `llama3.1-8b`; verify account/region model availability. |

The supported authentication method is Snowflake SQL API **key-pair JWT**,
matching the supplied account's `SNOWFLAKE_JWT` configuration. Passwords, PATs,
OAuth and browser token inputs are not used. Signing happens server-side with a
five-minute JWT. Keep existing key/passphrase files out of source control. A may
add these names to the shared `.env.example`; B did not edit it.

The schema owner executes `backend/app/snowflake/sql/001_setup.sql` once in a
dedicated selected database/schema. Runtime performs no DDL. Grant the service role
USAGE on its database/schema/warehouse, INSERT and SELECT on
`AGENTCITY_COMPARISON_EXPORTS_V1`, and appropriate Cortex/model access. Use one
backend worker and a dedicated schema per deployment; standard Snowflake primary
keys are informational. Configure warehouse auto-suspend/resource limits as an
operator policy. The app serializes comparisons and MERGE writes; stable SQL API
request IDs plus `retry=true` cover repeated ingestion after ambiguous submissions.
No production cleanup or destructive DDL is provided.

Rows are keyed by `(owner_id, simulation_id, revision)`. Each row contains all
exported metric points and a selected evidence projection in VARIANT, its SHA-256
and UTC Snowflake ingestion timestamp. Projection metadata includes simulation,
seed, parent/fork, endpoint tick and simulated seconds. The response's
`export_sha256` identifies this staged projection, not the complete multi-frame
JSON download. Projection schema/SQL version is V1; engine and contract versions
are the existing application's `1.0.0`. MERGE never overwrites an existing pinned
row; conflicting/corrupt read-back becomes an explicitly local fallback.

## Schema, truth and limits

The explicit DTOs are in `dto.py`; the independent OpenAPI snapshot is
[snowflake-openapi.json](snowflake-openapi.json). The child publishes authenticated
`/api/v1/integrations/openapi.json` and `/docs`. The frozen parent OpenAPI stays
unchanged. Writes require the existing cookie/local identity, allowed Origin,
CSRF token and UUID `Idempotency-Key`. Child errors use the standard failure
envelope, including validation and disabled-service errors.

Request body (exactly two explicit revisions; no SQL field):

```json
{
  "a": {"simulation_id": "sim_a", "revision": 12},
  "b": {"simulation_id": "sim_b", "revision": 14},
  "question": "What recorded differences accompany lower cooperation in B?"
}
```

Both pairs are authorized and pinned before any vendor request. The service calls
the **existing owned JSON export endpoint implementation** locally with explicit
`through_revision`, without an HTTP loopback or simulation writer lock. Snowflake
staging uses bound values; query shapes are fixed files, never generated SQL.
Read-back must match the staged hash before its values or evidence are used.

Response data includes both simulation/revision pairs, endpoint and metric ticks,
metric revision, simulated seconds, lineage, source values and `B - A` deltas for
happiness/safety/trust/resources/stress and recorded cooperation/conflict,
resources-consumed, evacuation and exposure counts. Counts retain the original
metric semantics; they are not reconstructed cumulative totals. Absent values
remain null; absent endpoint records fail before ingestion. Unequal horizons are
explicitly labeled and not time-normalized. Unrelated histories are labeled.
Every citation contains the owning simulation, pinned revision, kind, original
record ID, tick, excerpt and existing event/decision API URL.

Cortex uses supported `AI_COMPLETE` structured output to select/order approved
facts for the question. The UI renders server-authored factual sentences for that
selection. It does not render free-form model claims, arithmetic, invented IDs or
causal language. The honest source label is `cortex_selection`. Malformed,
unsupported or uncited selections become `deterministic` / `unavailable` while
keeping the queried numbers. Database outages label values `local_export`,
never Snowflake. Two histories support descriptive associations only.

Fixed default bounds: one active comparison; 12-second overall vendor deadline;
4-second HTTP timeout; 8-second Snowflake statement timeout; at most 20 status
polls per statement, 0.2 seconds apart; **no submission retry for Cortex**;
question 500 characters; revision <=2000; <=5000 metric points; <=1 MB staged
payload; latest 16 events and 32 decisions per history. Cortex sees a balanced
sample of at most 12 records per side inside 24 KB total context, outputs at most
256 tokens / 6 accepted fact IDs, and consumes a durable maximum of 20 model calls
per UTC day per deployment. Response/selection byte limits are enforced.

A separate SQLite WAL ledger under DATA_DIR stores canonical body fingerprints,
pending operations, exact results and model reservations. Identical completed
retries survive restart/response loss without additional vendor calls. Changed
bodies under a used key return 409. Pending duplicate requests return 503; another
operation during active work returns 429. Disconnection does not release capacity
until the shielded task persists its receipt. A crash with a pending receipt
requires operator investigation; the same key never automatically resubmits an
ambiguous model call. Keep receipts for the retry lifetime. Back up this ledger
with SQLite's backup facility or while the app is stopped, not by copying only
an active main database file without its WAL. No automatic retention/cleanup is
implemented in this assignment.

## Executable evidence

All commands below ran on this branch; source commit: `ef0aae2bc0e7519bc942a0252a50e099c8b6091b`.

| Cases/check | Command | Actual result |
| --- | --- | --- |
| S-01–S-05 | `cd backend && .venv/bin/pytest tests/test_snowflake_comparison.py` | 30 passed in 45.21s; literal deltas, unequal ticks, inherited IDs, exact SQL HTTP read-back, event/decision citation resolution, missing records/revisions, ownership, response loss/restart, changed-body conflict, malformed model output, 429/outage/deadline, blocked-vendor ticking, disconnected caller, JWT signature, schema snapshot. |
| S-06 controlled external fake | `cd frontend && npm exec -- playwright test --config playwright.snowflake.config.ts` | 2 passed. Real application/core security/export/extension route; only Snowflake's external HTTP transport is faked. Actual displayed metric cells match returned values, citations resolve, response-loss retry keeps key/body/result. Disabled component makes no integration request. |
| Frontend unit/consumer | `npm --prefix frontend test` | 150 passed, including 3 new extension client/schema tests. |
| TypeScript/build | `npm run build` | Passed. New modules typechecked; default bundle requires A's wiring patch to include the component. Existing Rollup PURE-comment warnings only. |
| Frozen core | `cd backend && .venv/bin/python -m scripts.contracts --check` | 43 hashes plus DTO/OpenAPI/stream snapshots match. |
| Full backend regression | `cd backend && .venv/bin/pytest` | 325 passed, 1 failed in 153.64s; this run collected 25 Snowflake tests before the final 5 were added. See baseline failure below. |
| Ruff | `.venv/bin/ruff check app scripts tests` from backend | Passed. Changed Python files also pass Ruff format. Full format gate has one untouched baseline file below. |
| Wiring patch | `git apply --check docs/release/snowflake-wiring.patch` | Passed against the fetched baseline; default-app integration acceptance remains A's gate after application. |
| Live Snowflake SQL/Cortex | `node scripts/snowflake-live-smoke.mjs --live` | **Unverified: blocked by supplied role privileges**, described below. |

Known baseline gates, deliberately outside this scenario-excluding assignment:

- `test_domain.py::test_repeat_evacuations_count_each_citizen_once` fails with
  `StopIteration` looking for an unexposed shelter at line 449. Reproduced with the
  same interpreter on an isolated `git archive origin/dev` checkout, without any
  Snowflake files: 1 failure. The corresponding core files were not changed.
- Full `ruff format --check app scripts tests` reports unchanged
  `backend/tests/test_city_layout.py:96`. Changed Snowflake files pass formatting.
- Full pre-existing browser suite and deployment/HTTPS checks were not rerun;
  this handoff is not a combined release sign-off.

## Opt-in live status and remaining work

The local account/user/database/schema/warehouse/role settings and encrypted key
files were present/readable. A real SQL API request authenticated far enough to
receive HTTP **422**, classified as **insufficient privileges**, while creating a
unique `AGENTCITY_SMOKE_<uuid>` schema. Setup, MERGE/read-back and AI_COMPLETE were
not reached. No real Cortex completion is claimed; offline fakes do not verify
Snowflake SQL syntax/account model access. No production tables were changed.
Only sanitized status/category output was retained; no credentials, account
identifiers, file contents, raw vendor bodies or signed JWTs are recorded here.

An operator must authorize schema creation in the configured database for the
smoke role (and ensure the execution context is usable), then rerun:

```sh
node scripts/snowflake-live-smoke.mjs --live
```

This command loads `backend/.env` using the existing launcher parser, requires
explicit paid opt-in, creates a unique disposable schema, runs versioned setup,
repeated MERGE and exact read-back, then one AI_COMPLETE structured selection.
It intentionally retains the disposable schema for inspection and performs no
DROP/cleanup. Final deployment still needs A's patch, operator-created runtime
schema/grants, successful real SQL/AI smoke, then combined public-route/UI gates.

References used to choose the supported APIs:
[SQL API authentication](https://docs.snowflake.com/en/developer-guide/sql-api/authenticating),
[bound statements and request IDs](https://docs.snowflake.com/en/developer-guide/sql-api/submitting-requests),
[AI_COMPLETE single-string structured output](https://docs.snowflake.com/en/sql-reference/functions/ai_complete-single-string).
