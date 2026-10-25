# Scenario, survival and live-voice integration — 2026-10-25

Timezone: America/New_York. Final application source candidate: **`7c3815a`**.
This records verification of the combined application, rather than adding together
the individual branches' earlier results. Subsequent reporting changes are docs only.

## Included branches and explicit exclusion

| Requested branch | Verified tip | Integration |
| --- | --- | --- |
| `scenario-engine` | `0164bf920b15ecf6e3ab2cd699bfadd5a1c18e51` | Normal merge `9209756`. |
| `codex/agent-survival-and-class-conflict` | `e062bcf505b2e959200d113f79feb58f84a8f099` | Normal merge `d2be594`. |
| `codex/live-conversation-voices` | `97cdf120aa47f974b22c78fa928b68dd5bdf7330` | Normal merge `43d3591`. |

The user explicitly withdrew `codex/disaster-controls-damage`. Its fetched tip
`16bed9821a477897cde654384b2e99dcbf55a5f3` is **not an ancestor** of the final
candidate. That tip contained live-voice integration rather than a disaster-controls
implementation. An initial unpublished trial merge in an isolated checkout was
discarded before restarting from dev with only the three requested branches.
No disaster slider/earthquake/tornado/persistent structural-damage implementation
is claimed by this integration.

The newer dev design remains the base. Existing controls, world rendering and
theme were extended for scenario editing, life/mental evidence and live voices;
no older frontend snapshot replaced them. Scenario CSS additions and new panels
are intentional feature changes. Frozen core v1 files remain unchanged.

## Integration changes and important issues fixed

- The scenario interpreter needs a longer HTTP timeout; live voices need request
  cancellation. Their conflicting transport signatures now preserve both, with
  regression tests for the 95-second scenario timeout and actual abort propagation.
- Registered both scenario and behavior routes on the existing authenticated
  integration child. Updated only its extension OpenAPI snapshot, preserving the
  parent contract and its 43 frozen shared-file hashes.
- Combined scenario start/decision/tick/outcome hooks with survival evaluation,
  rescue, crises and one time-scaled need-decay phase. Kept both scenario policy
  responses and the survival Game Master's consciousness/helper checks. Provider
  context invalidation retains the wallet and Mental threshold bands from both.
- Scenario systems previously allowed unconscious shopping, personal reviews,
  norm adoption, organization joining and information acceptance. These active
  responses now require consciousness. Living citizens may still experience
  passive financial/environmental pressure.
- Scenario illness/environmental health changes now use canonical attributed
  impacts and evaluate fatal boundaries immediately. A terminal hospital occupant
  cannot be healed before the death check, or act after crossing that threshold.
- Removed duplicate hospital healing for admitted patients. Physical treatment
  remains the single stocked care phase; conscious walk-in treatment also debits
  actual hospital supplies. Actual admitted treatment contributes to the scenario
  care counter. City-system effects precede care and the frozen meter-coupling
  inputs, so later unaccounted pressure does not bypass the end-of-tick checks.
- Preserved the existing uncommitted crowd/doorway recovery, physical facility-slot
  checks and post-scenario liveness work in `1279297`. The original nine modified
  files and one untracked browser test were snapshotted, reconciled with the feature
  changes and tested. The original diff remains recoverable in safety stash
  `feaf1679c18de7b274e0635b2ee8a43615a8cf63` and the ignored local snapshot directory;
  it is already integrated and should not be blindly reapplied.
- Existing browser scenarios now explicitly choose the keyword catalog when the
  AI interpreter is unavailable. Kept the new manual-composer flow and added a
  real browser test that creates a policy operation, validates/commits it, observes
  its live effect and verifies reversal after the measurement interval.
- The behavior browser configuration now uses installed Chrome by default on
  Windows, matching the existing core configuration. New scenario Python files
  were formatted to the repository's required Ruff gate.

## Executed verification

Tests use disposable stores, rules mode, disabled providers or controlled
transports. No billable API requests or public hosting changes were made.
Windows commands used the existing Python 3.13 environment through
`AGENTCITY_PYTHON`; browser runs used `CHOKIDAR_USEPOLLING=1` and installed Chrome.

| Gate | Result |
| --- | --- |
| Clean frontend lock install, `npm --prefix frontend ci` | 176 packages installed; zero audit findings reported. |
| Final root `npm test` | **175 frontend tests; 483 backend passed, 2 opt-in SQL skips**; no failures. Backend duration 376.96 seconds. |
| Frozen core contract check | All **43** hashes plus DTO/OpenAPI/stream snapshots match. |
| Ruff lint and formatting | Passed; **132** Python files formatted. |
| `npm run build` | TypeScript and production build passed; existing upstream annotation warnings only. |
| Core browser | **28/28 passed**, no flaky/skipped cases; includes production same-origin serving, scenario composer and movement liveness. |
| Behavior browser | **4/4 passed**: physical rescue/recovery, fatal fullness, crisis/class encounter and historical behavior evidence. |
| Narration browser | **5/5 passed**, including live scope, turn order, reconnect, abort, mute/autoplay, overflow and existing narration. |
| Snowflake browser | **3/3 passed**, using the real application and controlled warehouse transport. |
| Combined browser total | **40 passed**. |

Browser commands were run from `frontend/` using
`node node_modules/@playwright/test/cli.js test`, with the respective
`playwright.behavior.config.ts`, `playwright.narration.config.ts` and
`playwright.snowflake.config.ts` options for the dedicated suites. Separate output
directories under `backend/.tmp/` prevented artifact collisions.

Initial failures are retained in the local evidence: four core cases still
assumed implicit catalog fallback, behavior tests lacked a configured installed
browser, and the first full gate found unformatted scenario source. New fixture
repairs corrected minimum population, isolated medical supply consumption and
matched the actual editor's labels/minimum measurement duration. Functional
assertions were retained; the final results above are fresh executed gates.

Sanitized logs, backend JUnit, the final browser JSON and generated screenshots
were copied to the original checkout's ignored
`backend/.tmp/three-branch-merge-2026-10-25/`. Generated baseline artifacts were
restored rather than committing unrelated screenshot/report churn.

## Remaining external and feature boundaries

Real ElevenLabs voice quality/access/cold latency and new Gemini interpretation
were not verified with a live account. Local default configuration has these
providers disabled. Controlled transport playback is distinct from real synthesis.
Snowflake live privileges/SQL/Cortex, hosted deployment/HTTPS/restore and long-run
production retention/endurance remain separate gates. Tiger/Snowflake still use
their existing projections and do not yet claim the new behavior/learning schema.

The complete relationship progression, broader learned-outcome analytics and
disaster-audio/damage assignments are separate work; this merge does not claim
their task specifications have been implemented.
