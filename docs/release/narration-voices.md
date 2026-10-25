# Citizen voices and local ElevenLabs setup

Follow-up: 2026-10-24, America/New_York.

The local `backend/.env` now contains an enabled server-side ElevenLabs
configuration. The API key was created in the user's signed-in browser after
explicit confirmation: Text-to-Speech access, Voices read, Models access,
10,000 credits per refresh period, 30-day expiry, and leak auto-disable enabled.
The environment file is ignored by Git and has mode 0600. No key value is recorded
in this document, tests, frontend configuration, or source code.

The authenticated catalog returned **24 distinct account voices**. Their IDs are
configured in `ELEVENLABS_CHARACTER_VOICE_IDS` as a comma-separated list.
`ELEVENLABS_VOICE_ID` remains the event narrator. `ELEVENLABS_MODEL_ID` is
`eleven_flash_v2_5`, confirmed by the authenticated models endpoint.
`ENABLE_NARRATION=true` enables the existing narration integration on restart.

Decisions use the recorded decision agent's voice; dialogue uses its recorded
speaker's voice. Events use the narrator. Assignments are stored separately in
`narration/narration.sqlite3`, table `character_voices`, with a unique voice per
citizen in each owned simulation. The entire roster is assigned together, so
request order cannot change the voices. Assignments survive restart, reordered
configuration, and inherited branch records. New citizens use unassigned voices.
Cache and in-flight identity now include the actual selected voice ID.

The current local pool supports **up to 24 citizens with distinct voices**.
A larger city needs more authorized voice IDs in the configuration. Insufficient
voices produce an explicit 503 before synthesis; the app never silently reuses a
voice or pretends a changed setting creates a new voice. Removing an assigned
voice from the pool also produces an explicit configuration error. This does not
change the simulation's supported population range. No voice cloning is added.

Validation:

- `cd backend && .venv/bin/pytest tests/test_narration.py`: 34 passed.
  Combined rerun with the citizen-voice suite: 42 passed in 27.44s; frozen core
  contract hashes, DTOs, OpenAPI and stream snapshots match.
- `cd backend && .venv/bin/pytest tests/test_narration_voices.py`: 8 passed,
  including full 100-citizen allocation with 100 controlled voice IDs, two real
  application requests using different speaker voice paths, decision/dialogue
  consistency, branches, restart, additions and insufficient/changed pools.
- `cd frontend && npm exec -- playwright test --config playwright.narration.config.ts`:
  1 passed through the application's existing narration UI and controlled vendor.
- `node scripts/narration-live-smoke.mjs --live --save .tmp/elevenlabs/live-smoke.mp3`:
  **real ElevenLabs verified** at `2026-10-25T03:45:45Z` (October 24 locally).
  Core narration POST 200, authorized media GET 200 / `audio/mpeg`, 79,873 bytes,
  valid MP3, 67 recorded text characters, 0.651 seconds reported synthesis time,
  exactly one vendor attempt; repeat request returned cached audio. The disposable
  simulation was removed by the smoke runner. This evidence is separate from fakes.

The live smoke helper also now matches command request IDs to idempotency headers,
checks that its test city steps, and reports the selected citizen voice rather
than the event narrator. The sample MP3 is kept only under ignored `backend/.tmp/`.
To consume this updated environment, restart the backend through the normal project
launcher. Do not add these secrets to a `VITE_` setting or commit the environment.
