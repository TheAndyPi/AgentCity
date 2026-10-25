# Machine A - Tiger Data and release integration

Implement Tiger Data ingestion, deployment preparation, integration coordination
and final release verification for AgentCity's twelve-hour release. Read
`docs/dev-log.md`, `docs/release/integration-handoff.md`,
`docs/release/acceptance-cases.md`, and applicable repository instructions.

Start from latest `origin/dev` on `codex/tiger-release-integration`. Baseline
observed was `560e2ed`, including C maintenance, B scenario fixes/clarification and
the newer frontend. Fetch before assuming any issue is still open. Do not redo B's
scenario behavior or C's completed maintenance. No subagent/chat dispatch is
required by this written assignment.

## Deliverables

1. Add a server-only Tiger/PostgreSQL read-model adapter. Keep local storage
   authoritative and `PERSISTENCE_MODE=local`. Start with committed metric points,
   decisions, events and bounded movement samples needed for the demo. Describe
   exactly which records are ingested; do not claim complete relationship-history
   capture if only aggregated trust is stored.
2. Supply versioned SQL migrations, indexes and idempotent upserts. Every key
   includes simulation identity plus revision/entity identity as appropriate.
   Preserve branch provenance and both simulated and UTC ingestion times. Use
   TLS and parameterized queries. Do not rely on database-owner privileges.
3. Ingest only after successful local publication. Reconcile durable committed
   history with persistent per-simulation progress after restart. Batches, pending
   work, queue memory, HTTP/database operations and retries must be bounded. A
   failed optional write must not roll back a published local simulation or hold
   its writer lock. Report unhealthy integration state and lag honestly.
4. Implement the shared integration sub-app seam and sanitized Tiger status.
   Coordinate B's Snowflake router and C's narration handler/audio router. Own
   central main/service/config/lockfile/deployment changes. Add only required
   adapter dependencies, pin the tested lock and document actual environment vars.
5. Prepare reproducible Vultr deployment: one application worker, production
   frontend build, HTTPS reverse proxy with WebSocket support, supervised process,
   restricted credentials, persistent DATA_DIR, readiness, logs, backup and restore,
   restart/rollback steps. Do not open the dev server publicly. Never change cloud
   billing, permissions, DNS or infrastructure destructively without authorization.
   Preparation can finish without live host access; label deployment unverified
   until it is actually exercised.
6. Integrate focused B/C branches without overwriting newer dev work. Run the
   merged verification prompt; record actual commit, test and deployment results
   in `docs/release/tiger-handoff.md` and append a shared dev-log entry.

## Required executable tests

Implement T-01 through T-06 and the relevant R cases in the acceptance matrix.
Use disposable PostgreSQL/Tiger schema for the opt-in integration test and a
failure-controllable fake for deterministic offline coverage. A fake alone does
not prove SQL migrations/upserts execute in PostgreSQL. Verify exact persisted
rows/totals, duplicate delivery, branch identity, restart progress, failed local
commit exclusion and outage isolation. Prove ticks/HTTP controls remain usable
while ingestion is blocked, using synchronization/bounded waits rather than
arbitrary sleeps. Test child-route auth, ownership and error envelopes.

Run focused tests while implementing, then full backend/frontend/contract/build
checks on the final merged tree. Full browser results must be reported with
failures, even if a focused demo is green. Benchmark 10/30/100 agents and record
actual latency/cadence/storage; do not assume existing performance numbers are
unchanged. Preserve startup/recovery and credential cancellation guarantees.

## Delivery boundaries

No marketplace, imports, general policy engine, distributed runner or source-store
rewrite. New external integrations stay optional and disabled by default in tests.
Do not regenerate frozen core contracts or weaken existing assertions. Publish
the implementation branch and report its commit, tests, real-service status,
missing host/account access and merge instructions. Final dev integration must
be a normal reviewed/verified merge, never a force push.
