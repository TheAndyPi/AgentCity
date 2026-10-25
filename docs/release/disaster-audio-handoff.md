# Disaster audio and shared live voices

Implemented on `codex/disaster-controls-damage`, retaining the branch's scoped live
conversation voices. October 25, 2026, New York.

## Configuration and account status

Keep existing narration configuration and unique authorized character voice IDs.
Separately enable `ENABLE_DISASTER_EFFECTS`, `ENABLE_DISASTER_MUSIC`, and/or
`ENABLE_DISASTER_REACTIONS`. All default false. Models default to
`eleven_text_to_sound_v2`, `music_v1`, and `eleven_v3` respectively.
`DISASTER_AUDIO_DEADLINE_SECONDS=60` covers a long sound job independently of the
existing speech deadline. Keys and upstream configuration stay server-side.

Configuration-only smoke on this machine: narration is configured, **24** character
voice IDs are supplied, and all three disaster categories are disabled. This is
not proof of account entitlement, voice authorization, music access or expressive
quality. No paid requests were made for verification. Default automated tests use
valid marked MP3 bytes through the real HTTP transport and private media routes.

The provider payloads follow the official [effects API](https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert),
[music API](https://elevenlabs.io/docs/api-reference/music/compose), and
[expressive TTS capabilities](https://elevenlabs.io/docs/overview/capabilities/text-to-speech)
checked during implementation. Effects are 8-second loop requests; music requests
30 seconds with `force_instrumental=true`, never a prompt/plan/seed mixture.
Reactions request shouted/screamed delivery in the assigned citizen's voice with
`eleven_v3`. Unsupported reaction models fail explicitly. Literal spoken tags,
relatedness, scary arrangement, loop quality and perceived voice identity still
require live audition; fake tests cannot establish those properties.

## Ownership, sources and budgets

`LiveVoiceProvider` owns the existing one foreground voice player and one
`Soundscape`. Background media passes through a shared Web Audio compressor;
there are at most two environmental beds and one music bed. Reactions enter the
existing foreground channel only when ordinary dialogue is idle; they never
interrupt or silently discard an accepted conversation sentence. Music/effects
are ducked to .22 of their current mix while foreground speech plays. Background
volume is capped at .45; increasing danger selects a timbre band, not unlimited
volume. Music choice holds within a 20% relevance-score margin to avoid flapping.
Resolution/cancel fades backgrounds toward silence over roughly a second; pause,
master mute, visibility/scope/replay switches and revocation stop immediately.

Listening follows the focused citizen or current camera target, and ranks active
committed disasters by intensity and distance. New views join current ambience
without an onset/stinger or historical scream burst. No separate generated impact
stinger bus is implemented in this release. Environmental prompts contain bounded
cracking/debris/thunder appropriate to each hazard. Historical disaster scrubbing
is silent; there is no historical disaster-audio replay control. Existing explicit
conversation replay remains available.

Reaction selection is engine-owned and deterministic (`reactions-1` seed domain),
with local threat >=.65 or an unsafe occupied structure, personality weights and
alive/conscious checks. Captions retain cause, episode, location and evidence.
Cooldown is strictly 30 simulation seconds per citizen/event, including acute
structural causes; this release deliberately has no extra acute-cause bypass.
Playback admits at most three reactions per 10 wall seconds, one pending audible
candidate at a time, prioritized by focused citizen then threat within 20m. Clips
expire after three wall seconds of preparation instead of flooding a dialogue
queue. Recording 80 captions does not request 80 syntheses. Death/consciousness
and event state are checked again after generation; playback itself has no effect
on stress, memory, beliefs or simulation timing.

Enable sound is a user gesture. It unlocks browser playback and the AudioContext;
remembered mute/volume never auto-enable sound. **Sound mix** provides category
switches. Master mute/volume also govern existing manual narration. A measured
mobile dock offset keeps conversations, camera and roster controls reachable.
Cancelled unlock promises cannot masquerade as autoplay denial. Category failures
are independent and leave simulation controls/captions usable.

The shared narration transport rate/concurrency/queue and byte/cache limits apply
across all categories. One background provider job is admitted at a time, leaving
one default transport slot available for speech. Default global budget is 10
provider/voice-check requests per minute, queue 8, transport concurrency 2, response
4 MiB, cache 64 MiB/256 entries, TTL 24h, signed URL 15 min. Effects/music have one
attempt, no uncertain billable retry. Persistent job reservations prevent resending
ambiguous work after restart. Cache expiry after an attempted generation can make
that library item explicitly unavailable rather than silently rebill; restore its
cache or change the curated model/prompt version to prepare it again.

Cache identity includes owned simulation, payload/model/duration/band/format,
assigned voice and prompt version. Concurrent identical work shares a flight;
repeated exact operation keys replay durable receipts. Inherited branch manifests
can reuse still-cached parent recordings into independently authorized branch
entries. No media route accepts a client prompt or upstream URL. Existing owner,
Origin/CSRF, signed expiring media, session revocation and deletion checks apply.
Late or obsolete jobs can populate the bounded cache but cannot start old audio.

## Routes, provenance and verification

The existing narration mount adds:

- `GET /api/v1/integrations/narration/v2/disaster-capabilities`: separate
  unconfigured/unverified/pending/ready/unavailable category states.
- `POST /api/v1/integrations/narration/v2/simulations/{sid}/disaster-audio`:
  `{source_id, category, revision}`, with category effects/music/reactions.
  Only an owned committed currently active source can generate new media.
- Existing signed `/api/v1/integrations/narration/audio/{id}` serves all MP3s.

Durable SQLite manifests retain source/event/phase, tick/revision/time, assigned
voice, model, prompt version, band, content hash, provider and inherited provenance.
They contain no keys or private provider responses. Cache counters retain actual
synthesis starts/hits/failures and single-flight joins. The UI exposes category
availability, actual foreground captions and listening status.

Run `node scripts/disaster-audio-smoke.mjs` for configuration-only status.
With explicitly authorized access, `--live` may bill for **one effect, one music
bed and two committed assigned-voice reactions** in a disposable seeded city.
It saves MP3s and nonsecret provenance to `backend/artifacts/disaster-audio/`.
Audition those clips for relatedness, scary instrumental music, actual expressive
cries, distinct identity, absence of spoken tags and acceptable levels. Results
remain `audition_required` until that listening check; no real audition was claimed
in this delivery.

Backend HTTP/media tests cover independent category rejection, duplicate requests,
cache/receipts, 401/403/422/429/timeouts/non-audio/oversize, source/lifecycle rejection,
CSRF, forged signatures and assigned voices. Mixer tests cover bounded buses,
queues, mute/categories, late completions, scope/replay/pause and reaction bursts.
The browser suite plays decoded valid media with advancing playback time and checks
cancellation/reload, plus the existing complete live-voice/manual narration suite.
Final counts and tested commit are in the development log.

Tested implementation commit: **`b10701f`**. Final controlled audio tests: **19
passed**; frontend unit suite: **174 passed**; combined browser audio/disaster
suite: **8 passed**, followed by **3** final disaster browser passes. A single
unavailable citizen voice does not disable another assigned citizen's reaction.
No real paid-provider audition is included in these results.
