# Machine C handoff: ElevenLabs narration

Branch `codex/elevenlabs-narration`, based on `dev` at `2d22559`. Implementation
lives in `backend/app/narration/`; the browser side reuses
`frontend/src/components/Narration.tsx` at its existing call sites. Core DTOs,
`contracts/v1/**`, scenario semantics, Gemini behavior and dependencies are
unchanged (all 43 frozen contract hashes match).

## Coordinator wiring (A owns these files)

`backend/app/main.py` is already wired on this branch; the identical diff against
`dev` is [narration-wiring.patch](narration-wiring.patch). It:

1. imports `install_narration, narrate` from `app.narration.router`;
2. adds `narration_config=None, narration_transport=None` to `create_app` (tests
   inject a fake transport; production passes nothing);
3. reports `narration=request.app.state.narration.enabled` in capabilities;
4. replaces the 501 stub body of `POST /simulations/{sid}/narration` with
   `return await narrate(request, sid, body)` (route, DTOs and errors unchanged);
5. calls `install_narration(app, narration_config, narration_transport)` after
   `app.openapi = openapi`.

Install order relative to Snowflake does not matter: the narration media mount
places itself ahead of any enclosing mount (such as Snowflake's generic
`/api/v1/integrations`) at install time and again at application startup.

Replace the narration placeholders in `backend/.env.example` with:

```dotenv
# ElevenLabs narration (server-side only; never use a VITE_ variable)
ENABLE_NARRATION=false
ELEVENLABS_API_KEY=
# Existing account voice used for events; no cloning.
ELEVENLABS_VOICE_ID=
# Optional comma-separated distinct account voices, one per citizen.
ELEVENLABS_CHARACTER_VOICE_IDS=
# Model ID available to your account, e.g. eleven_flash_v2_5.
ELEVENLABS_MODEL_ID=
ELEVENLABS_OUTPUT_FORMAT=mp3_44100_128
# Absolute browser origin for audio_url when behind a proxy (no path).
NARRATION_PUBLIC_ORIGIN=
NARRATION_DEADLINE_SECONDS=20
NARRATION_MAX_CONCURRENCY=2
NARRATION_REQUESTS_PER_MINUTE=10
NARRATION_MAX_CHARACTERS=2500
NARRATION_MAX_AUDIO_BYTES=4194304
NARRATION_CACHE_MAX_BYTES=67108864
NARRATION_CACHE_MAX_ENTRIES=256
NARRATION_CACHE_TTL_SECONDS=86400
NARRATION_URL_TTL_SECONDS=900
```

Also drop ElevenLabs from the "unavailable" sentence in `README.md` line 82 and
from the "placeholders only" comment in `.env.example` when merging.

## Behavior

- **Sources.** The request is resolved inside the caller's own simulation head:
  events speak `title. summary`, decisions `name. rationale. outcome`, dialogue
  `speaker: text`. Whitespace is normalized and text is cut at a word boundary to
  `NARRATION_MAX_CHARACTERS`. Absent or mismatched sources return `NOT_FOUND`
  before any vendor call. Text is read without the writer lock; synthesis never
  runs inside `Service.mutate` or ticks.
- **Voices.** Events use `ELEVENLABS_VOICE_ID`. With
  `ELEVENLABS_CHARACTER_VOICE_IDS`, decisions and dialogue use a stable,
  distinct voice per citizen (see [narration-voices.md](narration-voices.md));
  too few voices is a 503 before synthesis.
- **Deduplication.** Content key = sha256 of simulation, voice, model, format and
  text. Concurrent identical requests share one vendor call; repeats are cache
  hits that issue fresh URLs. A reused `Idempotency-Key` replays the exact stored
  response; a different body under it is `IDEMPOTENCY_CONFLICT`; a replay after
  the cache TTL is `INVALID_STATE` ("request narration again").
- **Persistence.** `<data dir>/narration/narration.sqlite3` (WAL, synchronous
  FULL) stores audio metadata, operation receipts (≤10,000), the URL-signing
  secret and voice assignments. Audio files have random 32-hex names and are
  written with fsync + atomic rename. On restart, committed audio and receipts
  survive; damaged, orphaned and temporary files are removed.
- **Media.** `GET`/`HEAD /api/v1/integrations/narration/audio/{audio_id}` needs
  the owning session **and** a valid HMAC `expires`/`signature` pair. Every
  failure (wrong owner, guessed ID, traversal, bad or expired signature, deleted
  simulation, revoked session) is the same 404. Responses are `audio/mpeg`,
  `Cache-Control: private`, `nosniff`, same-origin resource policy, and support
  single byte ranges (206/416). There is no static mount.
- **Disabled.** Capability `narration=false` hides the UI; the POST and media
  routes return `FEATURE_UNAVAILABLE` 501 and nothing is opened on disk.
- **UI.** Idle → loading → ready / failed / unplayable. No autoplay, no
  regeneration on ticks, in-flight dedupe only, and responses for a source that
  is no longer selected are discarded. Failures show a "Try again" button.

## Limits

| Limit | Default | Result when exceeded |
| --- | --- | --- |
| Total deadline (all attempts) | 20 s (≤60) | 503 `SERVICE_UNAVAILABLE` |
| Attempts / per-attempt timeout | 3 / 15 s | retries only 429, 5xx and connect errors |
| Concurrent syntheses / queue | 2 / 8 | 429 `RATE_LIMITED` |
| Vendor requests per minute | 10 | 429 `RATE_LIMITED`, no vendor call |
| Characters per request | 2500 | truncated at a word boundary |
| Audio bytes | 4 MiB | 503, stream aborted |
| Cache | 64 MiB / 256 entries / 24 h | least-recent eviction; live URLs never evicted; 429 if full |
| Audio URL lifetime | 15 min (60 s ≤ ttl ≤ cache TTL) | 404 |

Configuration errors name the setting, never its value. The API key never
reaches responses, logs, errors, the browser or the evidence files.

## Tests

Default tests use an in-process fake ElevenLabs transport and never call the
paid service.

| Case | Command | Result |
| --- | --- | --- |
| N-01..N-06 | `cd backend && .venv/bin/pytest tests/test_narration.py tests/test_narration_voices.py` | **42 passed** |
| N-07 | `node scripts/narration-e2e.mjs` (real button, real app, fake vendor, Playwright) | **1 passed** |
| Frontend unit | `npm --prefix frontend test` | 150 passed (3 narration) |
| Contracts | core contract check | 43 hashes match |
| Full backend | `cd backend && .venv/bin/pytest` | 1 failure, `test_domain.py::test_repeat_evacuations_count_each_citizen_once`, which also fails on clean `dev` |

Mapping: N-01 `test_owned_event_decision_and_dialogue_…`, media ranges; N-02
`test_repeated_content_…`, `test_concurrent_identical_…`, `test_same_key_retry_…`;
N-03 `test_missing_mismatched_…`, `test_cross_owner_guessed_and_traversal_…`,
`test_unauthenticated_…`; N-04 `test_expiry_…`, `test_bounded_cache_…`,
`test_restart_…`, `test_revoked_session_…`; N-05 `test_provider_failures_…`,
`test_transient_failure_…`, `test_local_rate_and_concurrency_…`; N-06
`test_blocked_synthesis_never_holds_simulation_locks_…`,
`test_disabled_adapter_…`. N-07 covers loading, playable media with the fake
vendor's marker, no regeneration across ticks, switching sources mid-request
(no stale audio), provider failure and retry, and an unplayable-media retry.
Screenshots: `frontend/artifacts/narration/`.

**Live (opt-in, spends credits):**
`node scripts/narration-live-smoke.mjs --live [--save .tmp/elevenlabs/x.mp3]`.
Without credentials it prints `unverified` and exits 2. Recorded live evidence:
real ElevenLabs verified at `2026-10-25T03:45:45Z`, with POST 200, media 200
`audio/mpeg` (79,873 bytes, valid MP3), one vendor attempt and a cached repeat
(details in [narration-voices.md](narration-voices.md)). This is separate from
the fixture results above.

## Integration with Snowflake (Machine B)

With both extensions installed, every narration test passes in either order.
Two of B's tests,
`test_s05_blocked_vendor_allows_ticks_and_holds_single_comparison_gate` and
`test_s05_disconnected_caller_keeps_gate_and_receipt_until_completion`, look
up the Snowflake child with `app.routes[0]`. That lookup breaks whenever another
mount is first. Replacing `app.routes[0].app.state.comparison` with
`app.state.integrations.state.comparison` (B's documented handle) makes all 30
Snowflake tests pass in the combined app. That one-line test change belongs on
B's branch; this branch does not touch it.

## Known limitations

- The UI has no dialogue call site yet; dialogue narration is API-tested only.
- Cross-owner denial is tested with simulated identities in one process.
- A crash during synthesis, before the audio is committed, can cause one
  repeated vendor call on the retry.
- Behind a proxy that rewrites the host, set `NARRATION_PUBLIC_ORIGIN` so
  `audio_url` is absolute and correct.
