# Live conversation voices

Branch: `codex/live-conversation-voices`, based on fetched `dev` `720ecab`.
Implementation and evidence: October 25, 2026 (America/New_York).

## Using it

Configure `ENABLE_NARRATION=true`, `ELEVENLABS_API_KEY`, an event narrator
`ELEVENLABS_VOICE_ID`, a distinct authorized `ELEVENLABS_CHARACTER_VOICE_IDS`
pool, and `ELEVENLABS_MODEL_ID` on the backend. Restart through the normal launcher.
Credentials never belong in a `VITE_` setting. Existing narration rate, concurrency,
deadline, audio size, cache and URL settings continue to apply. The default
10 requests/minute also covers authorization checks and can limit continuous
conversation; rate failures pause the affected line and provide Retry/Skip.

Select a citizen on the map, open their profile, or choose **See them up close**
in Conversations. **Enable live voices** plays subsequent committed lines. A
watched interaction takes precedence over a member's profile; inspecting another
citizen or selecting another map citizen changes scope immediately. A pair chosen
before any committed interaction listens to its primary citizen, without inventing
an interaction ID. No selection means no automatic speech. Camera panning alone
does not choose an audio subject.

Mute, volume, audio pause/resume, Retry, Skip and Catch up live are independent of
physical simulation controls. Only mute/volume preferences persist. Enabling uses
a 10 ms generated silent WAV inside the actual button gesture to unlock the one
media element; permission failure still requires Resume. No stored preference
auto-enables sound. Hidden tabs stop audio, abandon queued turns, require explicit
resume and baseline the first fresh visible snapshot. Pausing the simulation does
not interrupt an already playing line. Audio never pauses the simulation itself.

## Scope, ordering and bounds

`LiveVoiceProvider` owns one `LiveVoices` coordinator per simulation page and
subscribes directly to WorldStore. It also arbitrates existing manual narration
players: starting one pauses the others and the automatic queue. Source changes,
page exit, history changes and session-revocation notifications stop all players.
HTTP and WS authentication failures notify the same revocation path.

The coordinator compares committed `(tick, numeric persisted dialogue ID)` cursors,
including same-tick ties. Entering a scope baselines its current committed position;
repeated frames, control revisions, reconnect snapshots and React remounts cannot
start old turns. Citizen scope admits the citizen's own speech and directly
addressed replies; `audible_to_ids` never qualifies background speech. Explicit
interaction scope admits only that interaction ID. Each branch has its own scope.

- Queue: at most **10 lines / 45 estimated seconds**, including the current line.
  Estimate is words / 2.6 + 0.5 seconds, minimum one second per line.
- At most **two next utterances** prefetched, with **two requests in flight**.
- Overflow retains the admitted queue, stops further prefetch and displays missed/
  backlogged status. Unadmitted sentences are never quietly skipped: Catch up live
  explicitly abandons that interval and baselines the latest frame.
- A gap beyond the 25-line stream window reconciles through the existing owned,
  revision-pinned paginated dialogue API: at most **3 pages / 300 records**. An
  unreconciled gap requires explicit catch-up. New frames arriving during a slow
  reconciliation are reconciled again against the advanced cursor.
- Timeline scrubbing disables automatic consumption. **Replay this conversation**
  is explicit and pins its selected revision. Replay uses the same 300-record
  history scan and queue bounds; older/larger transcripts may require choosing a
  later revision. Returning live never rewinds the cursor.

Captions and speaker/conversation identity reflect `playing` events, not synthesis
completion or advancing world captions. Generation checks and abort signals isolate
late POST/page results. Playback tokens also isolate late media promises after
Skip/Pause. Authorized media URLs are used directly; no public directory, blob or
object URL is created. Expired ready URLs are renewed with a new operation key.
Response-loss retries keep the exact source/revision body and operation key.

## Backend extension and compatibility

`POST /api/v1/integrations/narration/v1/simulations/{sid}/dialogue` accepts only
`{"source_id":"dialogue_...","revision":123}` and returns the existing success
envelope containing `audio_url` and `expires_at`. It needs the existing session,
Origin/CSRF and canonical UUID idempotency header. Sources resolve inside the
owned committed revision; client text and undeclared fields are rejected.
The extension OpenAPI is documented in `narration-openapi.json`. Frozen core v1
DTOs, hashes and snapshots are not edited or regenerated.

Live speech uses the recorded utterance without a speaker-name prefix. Oversized
utterances fail explicitly instead of silently truncating the caption's sentence.
Manual event, decision and dialogue text semantics remain unchanged. Cache identity
includes owned simulation, live mode/record ID, text, assigned voice, model and
format. Existing receipts, single-flight synthesis, authorized signed media,
expiry/revocation and restart persistence remain in use. Cache-byte reservation
is serialized across concurrent syntheses. Cache cleanup excludes active temporary
and final files until their metadata is committed, avoiding a concurrent sweep
deleting another request's recording. Restart cleanup still removes real orphans.

Assignments allocate deterministically in roster order, retaining all persisted
and inherited identities, including removed/deceased historical citizens. A short
pool leaves unassigned citizens unavailable while established speakers continue.
Removed configured voices fail for their own speaker, never remap known citizens.
Live requests check each requested voice through ElevenLabs' documented
[Get voice endpoint](https://elevenlabs.io/docs/api-reference/voices/get), server-side
only. Successful access checks cache for five minutes, at most 1,000 entries;
concurrent checks share work and respect the transport admission budget. Voice
discovery does not clone voices, purchase access or claim subscription entitlement.
Successful synthesis remains the final verification of model/voice availability.

## Validation and limitations

Default tests inject a controlled ElevenLabs HTTP transport serving known valid
MP3s with a text digest marker. Browser assertions compare those media markers,
recorded captions and the distinct speaker voice paths; these are functional
playback checks, not evidence of real ElevenLabs voice quality or cold latency.
Dedicated tests cover LV-01 through LV-10 across queue, backend and browser layers.
Existing narration, voice-identity and merged cross-adapter tests remain enabled.

Final checks (Windows, installed Chrome; no default paid calls):

- `cd frontend; npm exec -- vitest run tests`: **165 passed**, including **12**
  dedicated queue/scope tests. Root `npm run build` passed TypeScript and the
  production build; only existing dependency annotation warnings remain.
- `cd backend; .venv/Scripts/python.exe -m pytest tests/test_narration.py tests/test_narration_voices.py tests/test_live_voices.py tests/test_integration_composition.py -q --junitxml=.tmp/live-voices-tests.xml`:
  **54 passed** on the final narration sources, including **11** new backend cases.
- `cd frontend; npm exec -- playwright test --config playwright.narration.config.ts`:
  **5 passed**, including four-turn MP3 playback, WS → polling → WS, unrelated
  speaker exclusion, focus/profile changes and returning to the original citizen,
  denied autoplay, mute, mobile replay/overflow and legacy manual narration.
- Root `npm run test:e2e`, with `CHOKIDAR_USEPOLLING=true`: **26 passed**.
  `cd frontend; npm exec -- playwright test --config playwright.snowflake.config.ts`:
  **3 passed**. Both use disposable stores and controlled/disabled external services.
- Backend `python -m scripts.contracts --check`: **43 hashes**, DTO, OpenAPI and
  stream snapshots match. `python -m ruff check app scripts tests` and
  `python -m ruff format --check app scripts tests`: passed, **106** files formatted.
- A broad root `npm test` run also passed **403 backend / 2 opt-in SQL skips**
  during implementation. The final cache/permission refinements and two additional
  backend cases were subsequently covered by the final **54-case** focused gate;
  the frontend final count above includes the additional overflow-draining test.

Controlled cached transitions measured **75.1 / 35.7 / 46.8 ms** from the previous
line's ended event to the next playing event, below 250 ms; all four playing events
had exactly one active player. Raw sanitized measurements are in
`frontend/artifacts/narration/live-voices-playback.json`; desktop/mobile screenshots
are beside it. This measures local ready/cached playback, not cold ElevenLabs
latency. The tested source commit is recorded in the following verification note.

Real provider status: **unverified on this machine**. Configuration-only
`node scripts/live-voices-smoke.mjs` reported `configured=false` and **0** configured
character voices; no paid requests were made. Historical live evidence from another
setup in `narration-voices.md` does not verify this implementation. With supplied
authorized access, `node scripts/live-voices-smoke.mjs --live` may synthesize two
short committed lines, check distinct voice identities and signed MP3 delivery,
and report actual cold latency and cached repeats. This opt-in helper uses a
disposable city and is excluded from default suites.

Earlier verification caught and corrected a test-only missing lock for a newly
created city, overlapping map hit targets (now exercised through the actual
keyboard selection), cross-test fake request history, Chrome idle activation,
and a cache sweep racing an active audio write (exposed by Windows file locking).
No design replacement, core contract
change, mortality/crisis work or public deployment is part of this branch.

## Verification note

Tested source and executable test commit: **`c12e898`**. The final **165 frontend,
54 focused backend and 34 browser** passes, build and contract/lint gates listed
above cover these source files. Subsequent reporting changes affect documentation
only. The remaining external acceptance gate is real ElevenLabs synthesis and
cold-latency verification with supplied authorized credentials/voice access.
