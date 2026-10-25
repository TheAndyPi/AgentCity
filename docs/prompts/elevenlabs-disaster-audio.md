# Task: ElevenLabs disaster soundscapes, scary music and agent screams

Implement this assignment in AgentCity with executable functional tests. Read
applicable instructions, `docs/dev-log.md`, current narration/voice/media code,
the audio UI and the linked assignments before editing. Fetch latest dev and start
`codex/disaster-audio`; inspect an existing branch before reuse. Preserve dev's
frontend design, manual narration, security, budgets and the existing simulation.

Coordinate with [disaster controls and lasting damage](disaster-controls-persistent-damage.md),
[live conversation voices](live-conversation-voices.md),
[survival/personality/class conflict](agent-survival-personality-class-conflict.md)
and [relationship learning](relationships-learning-snowflake.md).

## User outcome

When a committed disaster happens in the viewed simulation, hear a related
environmental sound and tense/scary instrumental music. Earthquakes rumble and
crack; tornadoes roar with wind/debris; floods rush; fires crackle; storms have
wind/rain/thunder appropriate to actual conditions. Threatened agents can audibly
scream or cry for help in their own distinct assigned voices. Sound follows the
event and agent state and stops/fades appropriately instead of looping forever.

This is an extension of the existing audio system. It must coexist with focused
conversation playback, not introduce another independent audio player that fights
it. The live-voices assignment's single page coordinator is the shared owner of
playback, focus generations, mute and browser audio unlock.

## 1. Verify capabilities and reuse the existing service

`backend/app/narration/` already provides ElevenLabs TTS, source authorization,
stable `VoiceAssignments`, signed expiring media, caching, rate limits, deadlines
and idempotency. Extend those boundaries. The current narration transport is TTS;
sound-effect and music generation require distinct provider requests/capabilities,
not passing environmental descriptions to a narrator voice.

Official API references checked 2026-10-25; verify the configured account/model at
implementation time and record the result:

- [Sound effects API](https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert):
  `POST /v1/sound-generation`, text prompt, optional loop and duration. The current
  documented duration range is 0.5..30 seconds. Use an account-supported model and
  output format rather than assuming a TTS model can generate effects.
- [Music API](https://elevenlabs.io/docs/api-reference/music/compose): `POST /v1/music`
  accepts a prompt or composition plan. A prompt can request length through
  `music_length_ms` and set `force_instrumental=true`. Keep those request variants
  valid; do not send mutually exclusive prompt/plan/seed combinations.
- [TTS capabilities](https://elevenlabs.io/docs/overview/capabilities/text-to-speech):
  expressive delivery/audio-tag support depends on the model. Test the actual
  assigned voices with a supported expressive model; a tag is not a guaranteed
  nonverbal scream and must not be read aloud as stage directions.

Expose separate capability states for disaster effects, music and agent reactions,
including unconfigured/unavailable/ready status. A key that works for TTS does not
prove music access. Keep API keys/models server-side; no browser provider calls or
secret-bearing logs. Extend `.env.example` with names/defaults, never credentials.
Failure of one category does not disable working conversation speech or simulation.

## 2. Generate a bounded reusable sound library

Prepare/cache original disaster-specific assets by type and low/medium/high
intensity band. Do not make a paid generation call every tick, slider movement,
agent frame, reconnect or waveform loop. Use a bounded preparation job when audio
is enabled or a validated live event needs a missing asset. Prewarming must be
explicit/budgeted, and default development/tests remain provider-disabled.

| Disaster | Environmental generation direction | Music direction |
| --- | --- | --- |
| Earthquake | Low ground rumble, building vibration, intermittent cracking; no narrator, words or baked-in human screams. | Dark instrumental drones, tense low pulses, restrained percussive tension. |
| Tornado | Swirling wind roar and intermittent debris impacts; avoid unrelated explosions. | Fast anxious instrumental pulse and rising tension. |
| Flood | Rushing/surging water and relevant distant impacts. | Slow tense instrumental swell with uncertainty. |
| Fire | Fire crackle and occasional structural creak appropriate to exposure. | Uneasy rhythmic instrumental tension. |
| Storm | Wind/rain and bounded thunder cues matching active conditions. | Brooding atmospheric instrumental suspense. |

Initial asset defaults: 8-second seamless environmental beds, short bounded
impact/stinger clips, and a 30-second instrumental music bed with tested loop or
crossfade handling. Use provider limits valid for each category; these are not
TTS character-length limits. Cache model/prompt/version/output format/duration,
intensity band and a content hash. Retain authorized asset references so history
can reuse the exact recording; provider seeds do not guarantee identical audio.

Use structured server-owned prompts derived from validated disaster parameters,
not arbitrary client prompts, private memories or instructions hidden in scenario
text. Intensity changes select/mix approved bands with hysteresis; they do not
continuously regenerate assets. Scary music is an original instrumental score,
not a spoken announcement or a sound-effect prompt mislabeled as music.

Keep generation asynchronous and outside the simulation tick/control lock. Bound
jobs, retries, concurrency, bytes, decoded duration, cache size and total provider
spend across TTS/effects/music. Document separate long-job deadlines if needed;
do not silently extend the speech request deadline or starve conversation audio.
Handle 401/403/422/429/timeouts, truncated/non-audio responses, cancellation,
malformed formats and retry-after safely. Coalesce requests for the same asset;
do not blindly retry an uncertain billable generation after a disconnect.

Validate format/duration and audition loudness/loop points. Slow/failed generation
must leave the world responsive, show the category as pending/unavailable and use
an already cached suitable asset if one exists. Never claim provider-generated
disaster music from a silent stub, narrator reading "rumbling", or an unlabelled
unrelated local track. Late assets cannot start after their event/scope has ended.

## 3. Committed event lifecycle, locality and focus

Consume the disaster assignment's versioned committed lifecycle/exposure contract:
stable event/phase/damage/episode IDs, simulation/revision/tick/time, type,
parameters/units, normalized intensity, current geometry/origin/track and source
evidence. Agree on exact route/schema with that owner; do not add ad hoc enums to
frozen v1 streams. Typed local fixtures allow both branches to work independently.

- Preview, queued or cancelled-before-start events never create disaster playback
  or agent screams. Start once on committed activation. Joining an already active
  city starts at its current ambient phase after audio unlock, without replaying
  the onset stinger or old screams.
- Background music may reflect active disasters in the currently viewed city.
  Environmental sound follows the camera/listening location or focused agent,
  using the current hazard footprint and distance; a tornado moves audibly along
  its actual track. Do not hear every distant city/agent at full volume.
- Multiple disasters share one music bed chosen deterministically by current
  relevant intensity, with hold/crossfade hysteresis. Initially allow at most two
  environmental beds and one transient effect. Do not multiply music players.
- Resolution/cancellation stops the active bed and fades music over about 1 second.
  Persistent aftermath may have a quieter bounded crackle/creak if the engine says
  a residual hazard exists; broken concrete alone cannot sound like an ongoing quake.
  End-of-event outcome pause must not leave a disaster loop running forever.
- Pause fades/stops continuous loops; resume rebuilds current phase without replaying
  onset. Switching city/page/live-replay mode invalidates all old generation tokens,
  stops audio, removes listeners/nodes/object URLs and ignores stale completions.
- Timeline scrubbing is silent. Explicit historical audio playback may use stored
  assets and recorded cues at the pinned revision, without new reactions, provider
  synthesis or changes to the simulation. Missing archived audio is explicit.
- Hidden tabs stop/pause all channels; returning to a visible view reconciles the
  current event phase without a burst of old impacts/screams or queued dialogue.

Existing focus selection still governs ordinary dialogue. Disaster ambience does
not change the watched conversation or cause unrelated conversations to be read.

## 4. Agents scream because they perceive danger

Implement a small deterministic reaction selector coordinated through the disaster
owner's single committed perception hook. Keep it separate from conversation
acceptance and the survival task's crisis modes. Screaming can be an acute fear
response; it does not itself imply a mental break or require changing health.

Eligible reactions include a short nonverbal scream, startled gasp or cry for
help/warning. At least the scream and cry-for-help cases must produce actual
audible expressive vocalizations, not only a caption or thought bubble. Use the
citizen's existing unique assigned voice, including after save/restart/branch.
Do not substitute one shared crowd scream or alter pitches to fake unique people.

Base eligibility on actual perceived danger, abrupt local onset/impact/injury or
a credible nearby warning. Initial strong-threat trigger is normalized perceived
local intensity >=0.65 or a directly observed collapse/acute injury; use versioned
personality weights and seeded choice. Low risk tolerance/distress may favor a
scream; empathetic/cooperative citizens may issue a useful warning or call for
help; composed/high-risk-tolerance agents need not scream. Record the cause,
selected reaction, delivered text if any, audience/location and stable source ID.

Only alive, conscious, capable agents vocalize. No screams from dead/unconscious
citizens or from an unseen event across the city. Fear reactions must not require
an accepted conversation or force a target to accept one. Any gameplay effects
of a warning use existing audibility/perception and one evidence-backed event;
audio playback success/failure itself cannot alter stress, beliefs or relationships.

Bound reactions to at most one per agent/threat episode per 30 simulation seconds,
with a separate documented exception for a genuinely new acute cause. Deduplicate
the same cause across injury, collapse and hazard handlers. The listener additionally
caps live reaction playback at 3 clips per 10 wall-clock seconds, prioritizing the
focused agent, then nearby/highest-threat sources. At most one foreground voice
plays at once. Expire background reaction clips after 3 wall-clock seconds rather
than queueing an entire city's screams behind a long conversation.
Request missing reaction assets only for bounded audible candidates; recording
80 agents' reactions does not authorize an immediate burst of 80 synthesis jobs.

A focused emergency reaction may interrupt/preempt at a documented boundary;
coordinate with the live-voices queue so interrupted speech has an explicit
caption/status and no duplicate replay. Unfocused reactions cannot drown out a
watched conversation. If an agent dies/loses consciousness or the threat/scope
ends before a queued live reaction starts, discard it; historical replay retains
what actually happened at its original time.

Use a verified supported expressive model/delivery prompt with the same assigned
voice ID. Cache a small bounded set of suitable vocal variants per voice/style;
select deterministically and retain source/asset provenance. If nonverbal output
is unreliable, test a brief in-character shouted cry such as "Aah! Help!" with
the same identity, and document the audible result. Tags spoken literally are a
failed acceptance case. Unsupported voices show unavailable reaction audio while
preserving captions; do not silently swap identities or claim screams work.

## 5. One mixer and clear user controls

Extend the shared page audio coordinator with master, music, environmental and
voice buses. Keep the live-conversation task's serialized foreground voice channel;
additional background buses are centrally owned, not independent React players.
Duck music/effects while dialogue, warnings or screams play, with a smooth return.
Normalize/limit clips and avoid sudden full-scale peaks; increasing disaster danger
changes timbre/arrangement and bounded mix, not unlimited playback volume.

Provide Enable sound, master mute/volume and separate music/effects/voices toggles
in the existing design. Honor mute immediately for every bus, including in-flight
jobs and future scream playback. Unlock AudioContext/playback through a user gesture;
stored preferences cannot bypass autoplay policy. Handle rejected play promises
with one clear resume control. Keep captions/visible disaster cues usable when muted.

Preserve manual event/decision narration and conversation pacing. One provider
failure cannot break Play/Continue or trigger unhandled browser errors. Respect
reduced-motion settings for any synchronized camera/visual effects; sound controls
are independent of simulation speed and never speed voices into unintelligibility.

## 6. Media authorization, persistence and observability

Reuse the existing owner/source validation, signed expiring media, origin checks,
session revocation and cache protections for all three media types. New asset
routes need auth, ownership, CSRF where applicable, bounded request bodies and
versioned DTOs. Never create public sound URLs or permit arbitrary upstream URLs.
Renderers request known committed source IDs, not free-form generation prompts.

Record manifests linking source ID, actor/event ID, phase, recorded time, asset
hash, voice/model/prompt version and provider/local availability. Shared cached
bytes must not bypass simulation ownership. Refresh expired media signatures
without resynthesizing content or replaying already heard cues. Branches preserve
voice and inherited asset provenance but own independent playback cursors.

Keep cache cleanup, simulation deletion, logout/revocation and cancelled jobs safe;
already billable work can finish into a bounded cache but cannot trigger playback
for an obsolete/deleted/unauthorized source. Save/restart preserve source records,
asset references and reaction cooldown/deduplication. Do not store API keys or
private provider responses in exports. Track cache hits, actual generation attempts,
latency/failures, dropped-expired reaction counts and active buses for diagnosis.

## Required automated functional tests

Implement real tests plus browser audio assertions; HTTP 200 or finding a Play
button is insufficient. Default suites use fake transport/audio clocks and no
paid provider calls.

| ID | Case | Required acceptance |
| --- | --- | --- |
| DA-01 | Each disaster -> effects/music provider payload. | Correct category endpoint/model, bounded duration, instrumental music and no narrator-as-rumble substitution. |
| DA-02 | Capability missing/denied for music only or expressive voice only. | Truthful separate states, working categories preserved and no simulation failure. |
| DA-03 | Repeated frames/jobs/slider changes/reconnect and concurrent identical asset requests. | No preview generation, one admitted generation per cache key, bounded paid work and correct idempotency. |
| DA-04 | Provider 401/403/422/429/timeout/non-audio/oversize/late completion. | Safe bounded failures/retries, responsive world, no stale playback or unbounded queue/spend. |
| DA-05 | Queued -> active -> resolve/cancel; join mid-event; pause/resume. | One appropriate onset, correct phase/loop/fade, no historical scream burst or permanent outcome loop. |
| DA-06 | Moving tornado, focused agent, distant/overlapping disasters. | Correct locality, at most two beds/one music/one transient, deterministic priority and hysteresis. |
| DA-07 | Contrasting personality/perception with fixed seeds. | Actual eligible scream/cry/warning choices; no remote, dead or unconscious speaker and no forced conversation. |
| DA-08 | One collapse reported through multiple handlers; repeated threat and cooldown boundary. | Stable reaction source and one causal update, exact simulation cooldown, no fear/stress feedback from playback. |
| DA-09 | Two citizens scream with distinct assigned voices; model rejects tags. | Voice IDs remain unique/stable; audible verified expression or explicit unavailable, never literal stage-direction success. |
| DA-10 | Watched dialogue plus nearby screams, 80-agent threat and expired clips. | One foreground voice, bounded listener rate/queue, focused priority, proper ducking and no backlog flood. |
| DA-11 | Master/category mute, user gesture unlock and rejected autoplay. | All buses honor controls immediately, captions remain and stored preferences never force autoplay. |
| DA-12 | Focus/simulation/page/visibility/replay switch during requests/playback. | Old nodes/URLs/listeners/queues stop, stale generations ignored and no leaked playback after navigation. |
| DA-13 | Save/restart/branch/replay/expired signed URL. | Exact source/voice/cooldown provenance; no new provider work while scrubbing, correct ownership and independent cursors. |
| DA-14 | Unowned source, forged media signature, logout, deletion and arbitrary provider prompt/URL. | Authorization/revocation enforced for effects/music/reactions; no secrets or public media bypass. |
| DA-15 | Long-run loop/queue churn, louder assets and music/voice overlap. | Bounded memory/jobs/buses/cache, no duplicate media, limiter/duck envelope and cleanup verified. |
| DA-16 | Real browser event + local threat + dialogue + outcome + reload. | Starts actual decoded audio after enable, correct clips/voices and visible states, preserved simulation controls and no console errors. |

Add an opt-in live ElevenLabs smoke check that generates one disaster effect,
one short instrumental bed and two distinct assigned-voice reactions. Validate
actual media bytes/duration and listen to the clips for related sound, scary music,
expressive screams, distinct identity, no spoken tags and acceptable levels. Save
nonsecret provenance and report any unavailable category honestly. Automated fake
transport tests do not prove generated audio sounds correct.

## Ownership and delivery

Own narration extensions, generation jobs/media manifests, reaction selector module
and shared mixer integration. The disaster instance owns source lifecycle,
geometry/damage and wiring its single perception hook. Coordinate shared frontend
and schema files with both it and the live-voices owner; provide typed fixture
adapters early so each branch can run before the final integration.

Run focused backend/frontend/mixer tests, existing contract/lint/build gates and
relevant browser suites. Write `docs/release/disaster-audio-handoff.md` with exact
configuration/routes, current account capability, budgets, prompts/models, sample
provenance, tests/seed/commit and remaining limits. Update the dev log and push the
focused branch. Do not claim this file itself implements sounds, music or screams.
