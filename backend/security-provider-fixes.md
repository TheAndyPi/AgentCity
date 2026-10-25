# Machine A: security and provider fixes

Branch: `security-provider-fixes`, based on `e3dedc8`.

## Behavior changes

- Established streams recheck their session before each protected send. An
  independent 100 ms authorization watcher also closes idle streams and cancels
  backpressured sends after logout or expiry, using WebSocket policy code 1008.
  Revoking one session leaves other sessions authorized. Authorization reads the
  current durable session table; a failed logout commit does not pretend to revoke it.
- Provider proposals carry a fingerprint of the citizen's profile, location,
  inventory, goals, plan, emotion, beliefs, directed relationships, new memories,
  perceived observations/messages, known places, event status, policies, and
  control/actor/lineage generations. Health changes invalidate exactly. Routine
  hunger/fatigue/social changes use five-point bands plus action thresholds,
  allowing small noncritical decay without invalidating every call.
- Proposals are checked both when selected and when the engine requests each
  actor's intent. The second check catches event activation, personal-space
  movement and earlier actors' observations/social changes within the tick.
  Game Master legality remains authoritative; discarded proposals use rules and
  become eligible for replanning.
- The twelve-facility context now prioritizes current plan targets, urgent
  shelter/medical/food/rest destinations, and nearby remembered facilities.
  Known locations and resource locations are likewise ordered by relevance.
  A remote facility's current functionality/capacity is not supplied without
  observation. Context includes a copy of goals/plans and omits hidden overhearer IDs.
- Decision requests have an overall elapsed-time deadline of
  `2 * LLM_REQUEST_TIMEOUT_SECONDS + 0.25` seconds, covering queueing, credential
  refresh and at most two HTTP attempts. Completed results have a delivery window
  of two scheduling intervals, bounded to 2–10 real seconds. The old four-tick
  expiry is removed, so increasing simulation speed does not itself invalidate a
  useful result. Meaningful context changes still invalidate it.
- Usage persistence is protected from cancellation and joined during gateway
  shutdown before the repository closes. A blocked usage writer does not defeat
  the inference deadline or silently lose the request's measured/conservative counts.
  Deleted worlds also drop completed provider results retained in memory.

## Integration notes for Machine B

Application changes are confined to `app/main.py`, `app/api/security.py`,
`app/infrastructure/gemini.py`, and `app/service.py`. No simulation module,
frontend file, shared contract, schema, dependency lock, or credential changes
are required. Tests are in `tests/test_provider_context.py`,
`tests/test_stream_authorization.py`, and the existing provider test file.

`Service.provider_results` is runtime-only and now contains `ProviderResult`
objects instead of three-tuples. `take_proposals` returns a dictionary-compatible
`ProviderProposals` mapping whose `get(actor_id)` performs final validation and
returns the engine's existing `(intent, tag)` shape. The current engine already
uses that interface. Do not convert this mapping to a plain dictionary before
the tick, or move its `get` before activation/per-actor resolution: that would
remove the second validation boundary. No persistent-state migration is needed.

Memories are treated as immutable, append-only records. If another workstream
adds in-place memory editing, extend the fingerprint beyond its memory count and
last ID to include that edit version. Likewise, update the documented need
thresholds if simulation rules introduce different decision boundaries.

## Additional findings addressed

The original context exposed the complete list of message overhearers and shared
the goals list by reference. Both are fixed. Timeout/cancellation could also
interrupt or indefinitely delay usage bookkeeping; usage tasks are now protected
and drained at shutdown. These changes have dedicated regression checks.

## Verification

Final verification: **229 backend tests passed in 87.72 seconds**. All **43 frozen
contract hashes**, DTO/OpenAPI/stream snapshots, Ruff lint, Ruff formatting and
`git diff --check` passed. Tests use disposable stores
and mock providers; they make no live Gemini calls. The existing real-Uvicorn
HTTP/WebSocket smoke test remains part of the full backend suite.

Security tests exercise logout, expiry, reconnect denial, another active session,
and cancellation of a stalled send. Provider tests exercise relevant context
changes, harmless clock/need decay, facility selection/privacy, valid results
beyond four ticks at multiple speeds, elapsed-time expiry, within-tick changes,
Game Master rejection, bounded inference, and persistence after cancellation.
