# Machine A — Tiger Data and release integration

Date: 2026-10-24, America/New_York. Implementation branch:
`codex/tiger-release-integration`. Fetched starting application:
`2d22559368ffede1d0a5e500c487541a0120dda2` (newer than the original handoff).
Application candidate: `c724845a85368660fb5d13347bf76e9f5883f219`.
Final fully checked test tree: `0f6b3a9909aaf6babf69165fbf0acc0fa9ec302d`,
adding explicit source-deletion/restart assertions. Later documentation/evidence
commits do not change that application code.

## Delivered read model

Local storage remains authoritative and `PERSISTENCE_MODE=local`. Tiger is an
optional server-only PostgreSQL read model, disabled by default. No frozen core
DTO, `contracts/v1` file or core OpenAPI snapshot was changed.

`backend/app/integrations/tiger.py` reconciles the immutable committed journal,
projecting the same public records used by the existing owned JSON export at
explicit revisions. It does not call itself over HTTP or introduce another export
API. Tests compare SQL/fake read-back against the actual pinned export endpoint.

Exactly these records are ingested after `initialization.stage=ready`:

| Kind | Key in addition to simulation ID | Payload and meaning |
| --- | --- | --- |
| `metric` | metric revision + tick | Exact `MetricPoint`, including aggregate trust, cooperation/conflict/resource/exposure/evacuation fields. Same-tick committed metric versions are retained. |
| `decision` | decision ID | Exact public `Decision`; first observed committed revision is retained on identical redelivery. |
| `event` | observation revision + event ID | Exact public `EventReport` at each ready revision, including lifecycle/outcome changes and recorded lessons. |
| `movement` | observation revision + agent ID | Exact public `AgentSummary` at every ready revision whose tick is divisible by `TIGER_MOVEMENT_SAMPLE_TICKS` (default 2). Control revisions at sampled ticks are also sampled. |

Initialization revisions advance progress but contribute no metric, decision,
event or movement placeholder rows. Simulation metadata includes simulation ID,
parent/fork provenance, seed, engine and contract versions. Branches have separate
keys even when their inherited entity IDs and immutable source objects are shared.
Each record has its committed revision, tick, simulated seconds, and a separate
UTC `timestamptz` ingestion timestamp. Identical retries preserve the original
row/timestamp. Metrics' column revision is their actual metric revision; other
records use their first observation or snapshot revision.

Profiles, dialogue, private memories, relationship edges and complete directed
relationship history are **not ingested**. Trust is an aggregate metric. Vendor
rows are retained when a local simulation is deleted; external retention/deletion
is an operator responsibility, and progress/status only expose currently owned
local simulations. Do not represent this adapter as a full source-store replica.

For a revision-pinned metric projection, select the latest metric revision per
tick **at or before the requested revision**, rather than summing every stored
metric version. The payload values retain the existing metric semantics; fields
that are cumulative in an export must not be summed again across ticks.

## Durability, budgets and failure isolation

Publication only sets a coalesced event after the local manifest commit and head
publication succeed. Network work runs in its own background task, outside the
simulation writer lock. Pending work stays in durable history rather than an
in-memory payload queue. A failed optional write cannot roll back a local commit
or mark local persistence degraded.

One simulation is served per round-robin turn, at most 4 revisions per turn
(configurable 1–16), with one revision projection and one database connection in
flight. Projection limits are 2,000 records and 2 MiB encoded payload; SQL batches
contain at most 100 rows. An oversized projection reports `PROJECTION_LIMIT` and
does not advance its cursor. No record is silently truncated to obtain success.

The total database-operation budget defaults to 10 seconds (maximum 30), with
connection, 5-second statement, 1-second lock and 5-second idle-transaction limits.
One attempt is made before backoff (default 1 second, doubling to 60 seconds).
New publications cannot bypass outage backoff. Retries continue at this bounded
rate while the service runs. A private selector event loop supports psycopg on
Windows without changing the application's process-wide loop policy. Cancellation
drains its one bounded database operation before the local process lock is released.
Local progress-file writes also drain before shutdown.

`DATA_DIR/tiger-progress.json` is atomically replaced/fsynced, checksummed and tied
to each simulation's committed object digest. It advances only after SQL commit
acknowledgement. A missing/corrupt cursor or changed journal digest causes safe
idempotent replay. SQL progress and rows commit in one transaction; SQL progress
is diagnostic, never trusted to skip local history after a restore. Lost SQL
acknowledgements and crashes before saving progress replay without duplicate rows.
If SQL is independently restored/cleared, remove the local progress file while
stopped to reconcile retained history into it again.

## SQL, credentials and configuration

Versioned migration: `backend/app/integrations/migrations/001_read_model.sql`.
It creates `tiger_simulations`, `tiger_records`, and `tiger_progress`, with compound
simulation/kind/entity keys and indexes for revision and tick queries.
`tiger_migrations` stores version/checksum receipts; changed applied migrations
are rejected. Migrations/upserts use ordinary PostgreSQL, no owner-only extensions
or database-owner privileges. Provision the dedicated schema before startup.
The runtime role needs USAGE/CREATE in **that schema only** plus ownership or the
required SELECT/INSERT/UPDATE rights on these tables; it does not need CREATE on
the database. The disposable local test separately verifies a non-superuser role
that does not own the database can migrate and ingest successfully.

Queries bind all record values. Schema names use psycopg identifiers, never string
interpolation. A single TCP hostname and certificate-verified TLS are required:
the adapter enforces `sslmode=verify-full`, disables GSS encryption fallback, and
uses an explicit `sslrootcert` from the connection string or the locked certifi CA
bundle. Store server credentials outside Git/frontend and restrict the role/schema.

Actual environment variables:

| Name | Default |
| --- | --- |
| `TIGER_ENABLED` | `false` |
| `TIGER_DATABASE_URL` | empty; required when enabled |
| `TIGER_SCHEMA` | `agentcity_tiger` (pre-provisioned identifier) |
| `TIGER_TIMEOUT_SECONDS` | `10` |
| `TIGER_REVISION_BATCH` | `4` |
| `TIGER_MOVEMENT_SAMPLE_TICKS` | `2` |
| `TIGER_POLL_SECONDS` | `5` |
| `TIGER_RETRY_MIN_SECONDS` | `1` |
| `TIGER_RETRY_MAX_SECONDS` | `60` |
| `TIGER_TEST_DATABASE_URL` | opt-in test connection, never read by the application |

The legacy `DATABASE_URL` name is not implicitly consumed. For the authorized live
smoke only, the existing root environment file's Tiger connection was passed in
memory as `TIGER_TEST_DATABASE_URL`; its value was not printed or committed.
Normal launchers read `backend/.env`, while production uses the supervisor's
environment file. Set the documented names in the actual launch environment.

Only new dependency: `psycopg[binary]==3.3.3`, with matching binary and Windows
`tzdata` pins in `backend/requirements.lock`. An isolated clean environment was
installed from this lock; Snowflake required no additional dependencies.

## Shared integration seam and B/C integration

One separately documented FastAPI child is mounted at `/api/v1/integrations`
before the frontend fallback. `app.state.integrations` references it; its state
shares the parent's service, security and cursors after startup. Child validation,
domain, HTTP and unexpected errors use compatible sanitized failure envelopes.
The parent enforces authentication, Origin, CSRF and canonical write keys; route
handlers still authorize owned resources. No core routes are hidden from OpenAPI.
The combined schema is [integrations-openapi.json](integrations-openapi.json),
independently snapshot-tested over the actual HTTP path.

Tiger status: authenticated `GET /api/v1/integrations/tiger/status`, with optional
owned `simulation_id`, `after`, and `limit` (1–100). Its standard success envelope
contains `enabled`, `state` (`disabled`, `unavailable`, `catching_up`, `healthy`),
safe `error_code`, `retry_in_seconds`, paginated simulation progress and
`next_after`. Progress includes published/ingested revisions and exact lag.
Unavailable integration does not fail local readiness. No connection strings,
vendor bodies, paths or credentials are returned or logged.

Machine B's `37c5fbc9064805fa98c810cfebb2c0004ce511ea` was normally merged, including
implementation `ef0aae2bc0e7519bc942a0252a50e099c8b6091b`. Its installer now composes
its route into the existing child and closes comparison tasks/receipts before
the core service releases storage ownership. Its capability reflects the enabled
implemented adapter. The default ComparePanel in History and the simulation Drawer
now renders B's comparison component. Dedicated default-app and History-browser
tests verify this wiring, exact values and coexistence with Tiger status.
See [Snowflake's handoff](snowflake-handoff.md) for configuration and live privilege
limitations. B's original standalone schema snapshot remains independently tested.

Machine C's `codex/elevenlabs-narration` branch/handoff was not available on the
remote at the last recorded fetch. No narration adapter has been invented or
claimed complete: core narration remains its honest 501 stub and capability false.
When C publishes, merge normally, wire its existing core handler and audio router
into this shared child (do not mount another child at the same prefix), then rerun
N-01–N-07 and all combined checks. No messages were dispatched to other chats.

## Verification and deployment evidence

The live Tiger test creates unique `tiger_test_<random>` schemas, executes migrations,
duplicate upserts and exact read-back, then drops **only those test schemas**.
It also exercises the configured public worker, branch provenance, persistent
restart progress, and a real query deadline. Existing application/vendor schemas
were not altered. The same tests run against a disposable local PostgreSQL 18.6
TLS cluster with a restricted role via:

```powershell
cd backend
.venv/Scripts/python.exe -m scripts.tiger_local_postgres --bin 'C:\Program Files\PostgreSQL\18\bin'
```

Offline cases, complete suite totals, initial failures/repairs, benchmark numbers,
exact commands and remaining release blockers are recorded in the accompanying
[validation report](validation-report.md). Full browser evidence includes the
initial failures, rather than substituting a focused pass for the full suite.

[Deployment files and runbook](../../deploy/README.md) prepare one supervised worker,
built frontend, verified same-origin HTTPS/WebSockets, persistent private DATA_DIR,
health/log checks, restricted credentials, offline backup/restore and rollback.
Local backup restoration verifies exact source/branch states and refuses a second
writer or overwriting a restore target. **Vultr/HTTPS deployment, supervisor and
host backup/rollback drills remain unverified** without authorized host access.
The measured configured 100-tick horizon is not a 10,000-tick endurance sign-off.

Publish/merge: fetch this branch, review its diff against current dev, and perform
a normal reviewed merge after the remaining C/live-service/host gates are satisfied.
Do not force-push or replace newer dev files with copies from another checkout.

After review and the remaining release gates, integrate with `git fetch origin`,
`git switch dev`, and `git merge --no-ff origin/codex/tiger-release-integration`.
Resolve against current dev, rerun `npm test`, `npm run build`, both browser suites
and the required real-service/host checks before a normal `git push origin dev`.

Implementation references: [psycopg async/cancellation](https://www.psycopg.org/psycopg3/docs/advanced/async.html)
and [PostgreSQL connection/TLS controls](https://www.postgresql.org/docs/current/libpq-connect.html).
