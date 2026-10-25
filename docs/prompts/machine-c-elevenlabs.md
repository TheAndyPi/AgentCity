# Machine C - ElevenLabs narration

Implement ElevenLabs narration through AgentCity's existing narration endpoint
and playback component. Read `docs/dev-log.md`,
`docs/release/integration-handoff.md`, `docs/release/acceptance-cases.md`, and
applicable repository instructions. Your previous maintenance is already present
in observed dev `560e2ed`; this is a separate implementation assignment.

Fetch latest `origin/dev`; start `codex/elevenlabs-narration`. Preserve updated
dependencies, Settings operation snapshots, bounded provider/credential handling,
scenario interpretation and the new city UI. Do not redo scenario fixes.

## Deliverables

1. Implement a server-only ElevenLabs adapter with finite total deadline,
   bounded response size, concurrency, rate limits and retry behavior. Configure
   a supplied voice/model; do not introduce voice cloning. Read credentials from
   server configuration and never send them to browsers or include them in errors.
2. Resolve `event`, `decision` and `dialogue` source IDs within the authenticated
   owner's simulation. Build speech from the actual recorded summary/rationale/
   dialogue. Reject absent or mismatched records before any vendor call. Keep
   audio generation outside simulation writer locks and physical ticks.
3. Implement existing core POST `/api/v1/simulations/{sid}/narration`, preserving
   request and response DTOs exactly. Deduplicate same-key retries, concurrent
   identical work and repeated requests for the same versioned text/voice/model.
   Bound audio cache size/TTL, persist enough operation/cache metadata for defined
   restart behavior, and account for revoked/expired access. Do not introduce a
   long network await inside generic `Service.mutate`'s writer lock.
4. Return an absolute audio URL plus actual expiry. Implement authorized media
   delivery under the shared extension namespace. A cache filename or guessable
   audio ID is not authorization. Enforce ownership or a scoped expiring token,
   validate expiry and prevent traversal; serve correct audio content type and
   browser-compatible responses. Avoid public static access to private narration.
5. Reuse `frontend/src/components/Narration.tsx` and its existing call sites.
   Add clear loading, playback failure and retry behavior; protect against stale
   results when a selected source changes. Do not auto-play or regenerate audio
   on every tick/rerender. Disabled capability keeps existing UI hidden and the
   endpoint's honest unavailable behavior.
6. Work in dedicated narration modules/router/client helpers/tests. A owns
   shared main/service/config/lock files: deliver exact wiring for the existing
   endpoint, capability, lifecycle and media router, and integrate with A promptly
   so public-path acceptance tests execute. Use existing HTTP libraries where
   adequate; request coordinated dependency changes from A.

## Required executable tests and evidence

Implement N-01 through N-07 in the acceptance matrix. Assert actual source text
   sent, valid audio bytes returned/fetched, exact cache/provider call counts,
   repeated/concurrent/response-loss behavior, expiry, cache boundaries, restart,
   missing source/ownership rejection, traversal rejection, timeouts/429/5xx/
   malformed bytes and provider-disabled capability. Block the provider in a test
   and prove controls/ticks continue. Include a browser test that clicks the
   existing narration button and validates the delivered audio source; hidden UI
   or merely HTTP 200 JSON is not playback validation.

Default tests use controlled fake transport and known small valid audio; they
must never call a paid service. Supply an explicit opt-in live speech smoke
command and, when access is available, sanitized evidence of actual synthesis
and browser playback. Do not claim live verification from a fixture.

Push the focused branch, write `docs/release/narration-handoff.md` with exact
configuration, tests, limits, wiring and live status, and append the shared dev
log. Do not change frozen core contracts, general Gemini behavior, scenario
semantics or unrelated dependencies.
