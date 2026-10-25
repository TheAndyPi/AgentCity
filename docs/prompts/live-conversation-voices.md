# Task: live conversation audio and unique citizen voices

Implement this feature in AgentCity, not just a design proposal. Read applicable
repository instructions, `docs/dev-log.md`, `docs/release/narration-handoff.md`,
`docs/release/narration-voices.md` and the current code before editing. Fetch latest
dev and create `codex/live-conversation-voices`; inspect an existing branch before
reusing it. Preserve the current frontend design, merged integrations, media
authorization, provider budgets and manual event/decision narration.

## User outcome

When the user watches a specific citizen or a specific conversation, hear the
agents' committed dialogue automatically, in order, with a distinct voice for
each speaker. Speech must follow the selected subject, not the whole city. Keep
captions visible and identify the current speaker. No repeated Listen click per
line, overlapping voices, surprise historical playback or stale-source audio.

## Existing implementation to extend

- `backend/app/narration/{service,transport,speech,store,voices,router}.py` already
  implements recorded-source speech, authorized signed media, deadlines, caching,
  idempotency, voice assignments and restart behavior. Extend it rather than
  introducing a competing synthesis service or public audio directory.
- `VoiceAssignments` already maps each agent to a distinct configured ElevenLabs
  voice ID and can inherit assignments from a parent simulation. The missing
  feature is automatic dialogue consumption/playback and robust view scoping.
- `frontend/src/components/Narration.tsx` supports manual event/decision playback.
  `frontend/src/narration/results.ts` only deduplicates in-flight requests.
- Live frames expose recent committed dialogue; the paginated dialogue API has
  older records. `LifeHUD`, the conversation feed, the citizen inspector and the
  simulation's focus state identify the subject being watched.
- Local narration is disabled unless configured. Enabling a button is not proof
  that an account has enough authorized voices or can synthesize audio.

## 1. Resolve exactly one listening scope

Create one page-level audio coordinator, shared by every narration surface. Its
scope includes simulation ID, live/replay mode, selection generation and either
an agent ID or an interaction/conversation ID. Resolve precedence explicitly:

1. An explicitly watched conversation/pair takes precedence over its individual
   members. Filter by that interaction ID, including all of its speakers.
2. A citizen inspector or map focus listens to that citizen's direct conversation:
   lines spoken by the selected citizen and direct replies addressed to them.
   Overheard/background conversations must not enter this queue.
3. No focused citizen/conversation means no automatic speech. Panning the camera
   or merely having people on screen does not select them for audio.

Wire all actual ways of watching a citizen/conversation, including map selection,
profile inspection and the conversation feed's Watch action. Resolve conflicting
surfaces once, not in separate component effects. Distinguish two people selected
before a conversation exists from a committed active interaction.

Switching citizen, interaction, simulation, live/replay mode or leaving the page
must immediately stop current audio, clear queued lines, revoke object URLs and
ignore results from the previous generation. Abort obsolete client requests where
possible; completion of already billable server work may populate its bounded
cache but must never cause stale playback. Do not make network completion a
condition for changing the user's focus.

## 2. Consume committed dialogue exactly once

Subscribe to the current WorldStore/stream. Only committed dialogue records may
be spoken. Do not generate new dialogue from thought bubbles, future intentions,
Gemini proposals, captions assembled in React or another citizen's private state.
Preserve server turn ordering and speaker IDs, including simultaneous-tick ties.

On entering a live scope, establish a cursor at the current committed position;
start with subsequent lines. Do not automatically read the last 25 old messages.
An explicit Replay this conversation control may opt into historical playback.
Repeated frames, React remounts/StrictMode, same-tick control revisions, reconnect
snapshots and polling fallback must not replay an already handled utterance.
Use bounded ID/cursor tracking. If a reconnect gap exceeds recent-frame history,
use the owned, revision-pinned paginated dialogue API to reconcile it, with a
bounded catch-up policy and visible missed/backlogged status.

During historical timeline scrubbing, automatic live audio is off. Historical
speech requires an explicit replay action and stays tied to its selected revision.
A branch has its own playback cursor even when it inherits the same dialogue IDs.
Paused simulation: finish an already playing line unless audio is explicitly
paused; no invented new turns. Hidden-tab behavior must stop/pause playback and
resume only according to the visible listening state, without a burst of backlog.

## 3. Playback, pacing and browser permission

Provide a compact Enable live voices / mute / volume / pause control within the
existing UI design. A browser user gesture must unlock automatic audio; handle
`play()` rejection with a clear resume control. Never auto-enable sound on initial
page load. Retain the user's mute/volume preference without pretending a stored
preference bypasses a new browser's autoplay policy.

Use one playback channel: the next line starts after the previous line finishes
or is explicitly skipped. Prefetch at most two next utterances. Bound queue length
and estimated speech duration, initially 10 lines / 45 seconds, with measured
configuration documented in the handoff. At ordinary speed, preserve all four
turns of a watched conversation; do not drop replies merely because React rerenders.
At high simulation speed, show listening lag and a Catch up live choice. At the
queue limit, stop further prefetch and present a clear catch-up/pause choice;
never silently discard sentences, overlap them, or create unlimited paid work.

Synchronize the Now speaking indicator and spoken caption to the audio actually
playing, even if the world has advanced. Display speaker and conversation identity.
Vendor latency may introduce a visible delay; do not promise zero latency or fake
speech completion. An optional Pause simulation while listening control must be
explicitly chosen; audio itself must never block the simulation writer or tick.

Cached/ready audio should begin within 250 ms of becoming the next playable line
in a controlled browser test. Measure real cold synthesis latency separately;
an unavailable provider must leave text conversations and controls functional.

## 4. One stable, unique voice per character

Reuse persisted voice assignments. Distinct citizens in a simulation must have
distinct real ElevenLabs voice IDs; changing speed/pitch on one shared voice does
not satisfy this requirement. Keep assignments stable across focus changes,
requests, refreshes, restarts and inherited branches. New citizens cannot steal
existing assignments. Retain the voices of dead citizens for historical replay;
do not recycle an established identity for a different character.

Validate the configured pool and make shortages understandable. Existing assigned
speakers should remain usable when a new unassigned citizen exhausts the pool;
show that citizen's voice as unavailable, preserve captions, and never silently
reuse a voice or stop physical simulation. Removed/unauthorized assigned voices
need a clear operator error; do not silently remap known characters.

Use authorized existing account voices or an explicitly supplied pool. Do not
clone voices, purchase access, or claim voice availability without verifying it.
Keep any voice discovery server-side and cached/bounded. Separate the event
narrator from citizen dialogue. Speak the actual utterance with the speaker's
voice; avoid saying "Name:" before every live conversational line. Preserve
manual event/decision text semantics or version a distinct live-dialogue mode.

## 5. Backend contracts, cache and reliability

Prefer the existing narration POST with recorded dialogue source IDs and existing
authorized media delivery. If a live-only mode or batch/prefetch route is needed,
document a bounded extension schema; do not add undeclared fields to strict frozen
core v1 DTOs, hide routes from checks or regenerate frozen snapshots. Preserve
all existing manual consumers and tests.

Tie cache identity to owned simulation, record/text version, assigned voice, model
and output format. Generate one logical synthesis for concurrent identical work.
Lost-response retries retain the exact operation key/body; changed requests get
new keys. Preserve finite total deadlines, cancellation-safe cleanup, queue and
byte limits, TTLs, restart behavior, authorization and secret-safe errors.
Keep credentials exclusively on the backend. HTTP/WS revocation and signed-media
expiry remain effective during live playback. No vendor call may hold simulation
writer locks or delay physical ticks.

## Required automated functional tests

Default tests use a controlled ElevenLabs HTTP transport and known valid MP3 whose
marker proves the text/speaker used. Add actual backend, queue and browser tests:

| ID | Case | Required observable result |
| --- | --- | --- |
| LV-01 | Watch a four-turn conversation between two citizens. | Four committed lines play automatically, in order, with correct distinct voice IDs and no overlap or per-line click. |
| LV-02 | Watch one citizen while multiple unrelated conversations occur. | Their direct exchange plays; unrelated/background lines never synthesize or play. |
| LV-03 | Repeat frames, remount, reconnect and switch WS to polling. | Each eligible new dialogue ID is handled once; no historical snapshot burst or duplicate vendor charges. |
| LV-04 | Change focus/simulation while synthesis or playback is pending. | Old audio stops immediately; delayed old responses never play in the new scope. |
| LV-05 | Mute, pause audio, hide/show tab and deny autoplay. | No surprise playback; correct visible resume state; simulation controls remain independent. |
| LV-06 | Deliver lines faster than speech, with a slow/failed vendor. | Bounded queue/prefetch, visible lag/catch-up behavior, no overlap, coherent ordinary-speed four-turn exchange and recovery. |
| LV-07 | Restart/branch/add citizens/remove a pool voice/exhaust the pool. | Stable inherited identities; no collisions or reassignment; existing voices continue and shortages are explicit. |
| LV-08 | Retry after response loss, concurrent requests, expiry and logout. | Defined idempotency/cache counts, fresh authorized URLs when needed, denied unauthorized media and no key leaks. |
| LV-09 | Scrub old history then return to live. | Historical lines play only when explicitly requested; live cursors do not rewind or cross branches. |
| LV-10 | Real UI: enable voices, watch exchange, inspect other citizen, return. | Valid browser media really loads/plays; caption/speaker match audio marker; one active player and no stale sound. |

Run existing narration/voice tests, merged cross-adapter regression, frontend unit
tests/build, core contract checks and appropriate browser suites. Add opt-in real
voice verification separately from mocked tests, using supplied authorized access;
report missing credentials and actual latency honestly. Never bill incidentally
from the default test suite.

## Ownership and delivery

Own narration backend/frontend modules and dedicated tests. Coordinate minimal
focus wiring in `Simulation`, `LifeHUD` and the conversation feed with the agent
behavior task; preserve dev's design. Do not implement mortality/crisis mechanics
in this branch. Push the focused branch, document configuration/limits and exact
tests in `docs/release/live-voices-handoff.md`, and append `docs/dev-log.md`.
Report tested commit, live-provider status and any unresolved acceptance case.
