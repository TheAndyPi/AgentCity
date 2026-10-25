# Twelve-hour integration contract

Baseline: application commit `560e2ed`. Read [the shared dev log](../dev-log.md).
Goal: a reliable hosted demonstration with real optional service integrations,
not a marketplace, map editor, storage-engine rewrite or new distributed runner.

## Ownership and delivery

A owns composition in `backend/app/main.py`, `backend/app/service.py`,
`backend/app/infrastructure/config.py`, process lifecycle, backend dependency
manifests/locks, `.env.example`, root launch/deploy files and final dev integration.
B owns new Snowflake modules, its router, comparison UI and dedicated tests.
C owns new narration modules, its audio router, `Narration.tsx` and dedicated tests.
Each owner writes `docs/release/<service>-handoff.md` with exact wiring instructions.
Avoid shared frontend client/schema/Drawer edits: add service-specific modules
and give A a small final wiring change. Do not replace shared files with copies
from an older checkout. Dependency requests go to A for one coordinated lockfile.

A wires B/C modules into the real app promptly so their public-path tests can
run on integration branches. B/C must supply exact minimal wiring patches or
instructions when a shared edit is needed, and report acceptance tests blocked
on integration honestly. Test-only mounting is useful adapter coverage but does
not count as public application acceptance.

Start from latest fetched `origin/dev`; preserve user changes and inspect existing
assignment branches before reuse. Push focused implementation branches, no force
pushes or independent pushes to dev. A merges in sequence, reruns combined gates
and records actual commit IDs. Do not send other chats messages unless the user
has separately authorized that communication.

## API compatibility seam

Core v1 DTOs, wire schemas, fixtures and core OpenAPI stay frozen. A mounts a
separate FastAPI integration sub-application at `/api/v1/integrations` **before**
the frontend catch-all. It has its own documented OpenAPI and DTOs outside
`app/contracts.py`. Mounts are not included in the parent OpenAPI document;
therefore the core checker can still validate the unchanged normative API.
Document and test the extension schema independently, rather than silently
marking new routes `include_in_schema=False` or filtering the core check.

The existing parent security middleware checks the `/api/v1` prefix. Mounted
routes must additionally verify resource ownership, preserve auth/CSRF/origin
requirements, validate canonical idempotency keys on writes, and return compatible
error envelopes. Child exception handlers and validation responses require tests;
parent error handlers are not automatically the child's handlers.

Reserve these extension paths; document exact request/response schemas before use:

- B: `POST /api/v1/integrations/snowflake/comparisons`: exactly two owned
  simulation/revision pairs, bounded question and stable idempotency key. Return
  pinned provenance, computed differences, record citations, truthful provider
  source and a bounded grounded explanation. No arbitrary user SQL.
- A: `GET /api/v1/integrations/tiger/status`: authenticated, sanitized ingestion
  progress/availability; no connection string or vendor exception bodies.
- C: `GET /api/v1/integrations/narration/audio/{audio_id}`: same-origin authorized
  media delivery, optionally opaque expiring scoped access. An ID is not an
  authorization check; test cross-owner, expiry and path traversal explicitly.

C implements the existing **core**
`POST /api/v1/simulations/{sid}/narration` without changing its DTOs:
`{source_type: event|decision|dialogue, source_id}` -> `{audio_url, expires_at}`.
`audio_url` must be an absolute usable URL to satisfy the current frontend parser.
A wires the handler to C's service and updates the existing narration capability.
Core payload schemas remain unchanged. Capabilities `persistence` remains `local`;
Tiger ingestion is not a PostgreSQL-primary adapter. Optional integration flags
must reflect an implemented enabled adapter, with actual health separately visible.

## Shared data and failure behavior

Use the existing owned JSON export at an explicit `through_revision`; do not
create a competing export format. Pin revisions at request start and carry source
simulation ID, branch parent/fork references, engine/contract version, seed, tick,
simulated seconds and UTC ingestion time. Never confuse simulated time with wall
clock time. Metrics/evidence must refer to the exported revision, not a newer head.

Record identity must include the simulation ID even when a branch inherits stable
entity IDs. Re-ingesting the same export is idempotent; different branches never
overwrite one another. Use parameterized SQL and bounded payloads. Publish only
durably committed records. No external operation runs under the simulation writer
lock, and optional outages must not invalidate a successful local commit or tick.

Tiger uses durable progress/reconciliation from committed history, bounded batches
and bounded retry/backoff. Snowflake can ingest directly from exports, so Tiger
availability is not a prerequisite. Neither system may invent records or metric
totals when unavailable. Narration reads recorded text, not unrestricted caller
text, and avoids duplicate billable calls after idempotent retries.

## Deadline and evidence

At the start verify credentials/access without exposing secrets. Aim for adapter
code by hour 5, merged application behavior by hour 7, demo rehearsal by hour 9,
then feature freeze and release checks. If blocked by credentials, complete the
adapter, mocked failure tests and operator instructions; label live status
unverified and report the exact missing service access. Do not claim mock success
as a real service integration.

Required evidence is in [acceptance cases](acceptance-cases.md). Each implementation
must commit executable tests for its cases. The validator checks the actual merged
routes and browser behavior, not only isolated helper functions.
