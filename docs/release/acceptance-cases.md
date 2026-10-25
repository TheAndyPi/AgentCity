# Functional acceptance cases

These are required executable test specifications, not claims of implementation
or passing status. A/B/C add tests with their adapters. Default execution uses
disposable storage and controlled external fakes; opt-in real-service tests use
dedicated schemas/voices and sanitized evidence. Test real routes after wiring.

## A - Tiger Data

| ID | Setup/action | Observable acceptance |
| --- | --- | --- |
| T-01 | Commit a ten-agent city and known steps, ingest its pinned export. | SQL rows match exact exported IDs, revisions, ticks, metrics, event/decision values and movement samples; no initialization-placeholder rows. |
| T-02 | Deliver the identical export twice and retry after a lost success acknowledgement. | Stable row count and values; no duplicate actions or double-counted aggregates. |
| T-03 | Ingest a source and a branch sharing entity IDs. | Separate simulation keys and correct lineage; one cannot overwrite the other. |
| T-04 | Restart after publishing a local revision and before recording external progress. | Reconciliation catches up exactly once; committed cursor survives restart and never skips uncommitted work. |
| T-05 | Inject local manifest failure; separately block/fail the external database. | Uncommitted records never leave the app; database outage leaves local state/controls usable, reports lag and permits bounded retry. |
| T-06 | Call status unauthenticated or with invalid access; inspect logs/errors and migration on disposable PostgreSQL. | Auth/envelope rules hold, no secrets leak; migration and parameterized upsert execute in a real compatible database. |

## B - Snowflake

| ID | Setup/action | Observable acceptance |
| --- | --- | --- |
| S-01 | Export two fixed revisions with known metric differences, ingest/query them. | Exact SQL values and calculated deltas match the exports; revisions and endpoint ticks appear in response/UI. |
| S-02 | Ingest twice, including inherited branch entity IDs. | Deduplicated records, separate branch/source provenance and unchanged totals. |
| S-03 | Ask a bounded comparison question; external fake adds an invented number or citation. | Numbers remain query-derived; invalid evidence is rejected/marked unavailable; every accepted citation resolves in the pinned history. |
| S-04 | Compare unequal horizons, unrelated cities, absent/invalid revisions and an unowned simulation. | Explicit horizon/lineage labeling; invalid access/revisions rejected before vendor calls; no manufactured zero baseline. |
| S-05 | Retry same key/body after response loss; then reuse key with changed body; inject rate limit/timeout. | One logical result/ingestion, conflict for changed request, bounded failure and truthful fallback provenance. |
| S-06 | Use comparison UI through real app API with controlled external transport, then opt-in Snowflake smoke. | Visible values/evidence match returned records; disabled service remains honest; actual SQL/AI execution is independently evidenced. |

## C - Narration

| ID | Setup/action | Observable acceptance |
| --- | --- | --- |
| N-01 | Request narration of an owned event, decision and dialogue. | Correct recorded text and configured voice/model reach provider; valid audio URL/expiry and audio bytes are returned. |
| N-02 | Repeat/concurrently request same content; retry same key after response loss. | Defined deduplication/cache behavior prevents duplicate vendor synthesis and preserves exact operation result; changed body under used key conflicts. |
| N-03 | Request missing/cross-owner source, invalid type, guessed ID or traversal-style media path. | Rejected before synthesis/media disclosure; compatible safe error envelope and no secret/path leakage. |
| N-04 | Advance expiry, exceed bounded cache, restart, revoke session and fetch media. | Defined retention/restart behavior; expired or unauthorized access denied; bounded disk/memory and no broken public URL advertised as valid. |
| N-05 | Provider returns timeout, 429, 5xx, malformed/oversized audio; subsequent request succeeds. | Total deadline/retry/size limits hold; capacity released, useful safe error and successful later recovery. |
| N-06 | Block speech generation while stepping/pausing a simulation; disable adapter. | Controls/ticks remain functional; no writer-lock network wait; disabled capability hides playback and endpoint reports unavailable. |
| N-07 | Click existing playback UI, fetch valid fake audio, change selected source and retry failure. | Correct media loads with no autoplay or cross-source stale playback; browser reports usable media; opt-in live synthesis separately verified. |

## M - Maintenance regressions already implemented

Run the existing executable coverage, not the historical bug-reproduction assertions:

- `frontend/e2e/settings.spec.ts`: successful save -> save/create, exact retry
  snapshots after connection/JSON/contract response loss, queued edits and stale
  version recovery. Assert mutation counts/versions and resulting navigation.
- `frontend/tests/dependency-validation.test.ts`: Zod migration preserves core
  validation boundaries, numeric/UUID semantics and rejection of malformed data.
- `backend/tests/test_lesson_provider_deadlines.py`: bounded queue/auth/HTTP/
  backoff/usage paths, released reservations, surviving credential thread,
  cancellation-safe durable usage and deterministic fallback with continued ticks.
- `backend/tests/test_stream_authorization.py` and `test_provider_context.py`:
  active/blocked-send revocation and context freshness/privacy must remain intact.
- Scenario/domain suites: preserve merged negation, region, acceptance, safety,
  lesson counts and new clarification behavior. New services must not modify them.

## R - Combined release execution

| ID | Setup/action | Observable acceptance |
| --- | --- | --- |
| R-01 | Fresh install/build, rules mode, all optional services disabled, disposable DATA_DIR. | Readiness succeeds; create ten agents, confirm flood, observe movement/decisions, resolve/acknowledge, save/replay/branch. No vendor calls, no fabricated success flags. |
| R-02 | Pin a revision, compare JSON/CSV/metrics/state; advance head and restart. | Export totals/IDs remain equal to that committed revision and never drift with later ticks. Executable baseline: `backend/tests/test_release_exports.py`. |
| R-03 | Delete an archived source after creating a branch; export branch before/after/restart. | Branch's owned history/projections remain readable and identical at the pinned revision. Shared referenced objects survive cleanup. |
| R-04 | Full browser suite in isolated preferences/storage; force WebSocket fallback, failed save and navigation. | Real UI/API behavior passes; settings cleaned up, running cities paused/removed even on failure, no stale selectors or road-only assumptions. |
| R-05 | Exercise app on deployed HTTPS origin with valid/invalid session, Origin and CSRF; revoke active socket. | HTTP/WS security stays correct; direct SPA reload and media work; second writer is refused. |
| R-06 | Restart deployed service; restore backup into a separate directory; rehearse rollback. | Previously committed state and branch remain correct, loaded cities paused, no writes to production data during restore drill. |
| R-07 | Run 10/30/100 agents plus supported-horizon soak and blocked optional integrations. | Record actual p95 latency, achieved cadence, RAM/disk, lag and errors against agreed limits; no unsupported performance claim. |
| R-08 | Enable each real service separately and together, with explicit authorized test credentials. | Real rows/audio/grounded results demonstrable and attributable to vendor, core ticking survives outages, sanitized evidence records exact release commit. |

## Test quality and reporting

Assert persisted/read-back state, exact values, ownership, call counts and user
outcomes, not merely a non-null object, mock invocation or HTTP 200. Control time
and failure stages with events/fake clocks where practical. Use known valid media
for browser tests. No test should need a previous test's settings or a running
city left behind. Do not add credentials to fixtures.

Maintain a result table with ID, automated test path, exact command, commit,
pass/fail/blocked/unverified, evidence and owner. Missing credentials may skip an
explicit opt-in live test, but must not silently skip offline adapter assertions.
An implementation is not done until its functional cases are written and pass.
