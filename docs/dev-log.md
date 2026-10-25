# Shared development log

Read this file and [the release handoff](release/integration-handoff.md) before
starting an integration. Dates use America/New_York. Entries distinguish code
inspection, earlier branch evidence, and tests rerun on the merged application.

## 2026-10-24 - Twelve-hour release handoff

### Verified remote baseline

Fetched `origin/dev`; latest application commit observed is
`560e2eda691c5fdbffe4d5d39b8153ddb2f123e5`, authored by
**Codex (Machine C)** at **22:20:15 EDT**. The clean local dev checkout was
fast-forwarded to that commit. This confirms commit authorship and included
changes; it does not prove that Machine B has finished every task on its machine.

Included work:

- Machine C's `f08b328`: patched frontend dependencies, Zod v4 compatibility,
  Settings operation/retry lifecycle, finite lesson-provider deadlines, shared
  credential-worker lifetime, seven Settings browser cases and eleven dedicated
  provider cases, plus validation tests and evidence.
- `ff83662` and `560e2ed`: integration with newer dev and Machine B's work.
- Machine B's `9e68329`: list negation, unique citizen counts, construction
  wording and whole-word regions.
- Machine B's `fceecf9`: scenario interpretation/clarification. Unknown premises
  may now require the user to restate the request instead of accepting an abstract
  landmark. Preserve `can_commit`, warnings and unsupported notices.
- `28dee4f`: cyberpunk city/skyline rendering, addresses, buildings and population
  controls. Inspect current accessible labels and defaults; older handoff text
  and assertions about a fixed ten-person setup or 80-person default are stale.
  The inspected `defaultConfig` remains ten citizens/suburb; the UI now allows
  population changes up to capabilities. Demo tests must set population explicitly.

### Evidence boundary

Machine C's [report](reviews/machine-c-maintenance-2026-10-24.md) records green
maintenance-branch unit/build/contract checks, zero audit findings, seven Settings
browser passes, and a broader **18-pass/8-failure** browser run using test-only
polling. Its final merge was checked for syntax/conflicts/lock consistency but
**the merged application was not fully retested by Machine C**. Earlier counts
are historical evidence, not a release sign-off. Run the validation assignment.
The eight broad-browser failures and retention/endurance work were outside C's
maintenance scope; do not assume they were fixed by that merge.

### New assignments

| Owner | Branch | Assignment |
| --- | --- | --- |
| A / coordinator | `codex/tiger-release-integration` | [Tiger Data, deployment, coordination, release verification](prompts/machine-a-tiger-release.md) |
| B / analytics | `codex/snowflake-comparison` | [Snowflake ingestion and one grounded comparison](prompts/machine-b-snowflake.md) |
| C / narration | `codex/elevenlabs-narration` | [ElevenLabs using existing narration/playback](prompts/machine-c-elevenlabs.md) |
| Final validator | `codex/release-validation` | [Maintenance and functional release validation](prompts/release-validation.md) |

These are written assignments, not claims that chats have been launched or that
implementation has started. B's new assignment intentionally excludes scenario
fixes. A coordinates shared files, lockfiles, extension wiring and final merges.
All machines must add automated functional tests, not just a handoff description.

### Non-negotiable integration facts

- Local persistence remains authoritative; Tiger/Snowflake are optional read
  models. No vendor request or retry may hold the simulation writer lock.
- Keep one backend worker, default one concurrently running city, and the
  supported 10-100 population range. Multiple viewers do not imply multiple
  simulation owners. Do not deploy a multi-worker Gunicorn recipe unchanged.
- Preserve Machine A's session/WebSocket revocation, privacy/context freshness,
  cancellation-safe usage accounting, and Machine C's credentials/deadlines.
- Do not edit `contracts/v1/**` or core DTOs. The contract checker compares the
  **entire** core OpenAPI document: merely adding a normal parent-app route breaks
  it. Use the explicitly documented integration sub-application seam; do not hide
  routes or regenerate snapshots to obtain a pass.
- Existing narration POST is a 501 stub; playback already exists in
  `frontend/src/components/Narration.tsx`. A configured key alone is not an adapter.
- Existing `.env.example` has optional credential placeholders that the current
  app does not consume. Each implementation must document actual configuration.
- Snowflake must consume pinned existing exports directly and work independently
  of Tiger Data. Its summaries describe recorded differences, not causal proof.
- Use server-side credentials only; never log or commit `.env`, service-account
  keys, database connection secrets, cloud tokens or audio access tokens.
- Mock-based failure tests and real service verification are separate evidence.
  The validator must report an unavailable live test as unverified, not passed.
- Windows browser runs previously hit Vite watcher `EBUSY` on generated images.
  Test-only `CHOKIDAR_USEPOLLING=1` avoided that crash. Fix test setup/cleanup and
  current selectors; never remove behavioral assertions to green the suite.

Append an entry per handoff with commit, files, new configuration names (no
values), tests, known failures and the next machine's required action. Do not
rewrite another machine's historical evidence or push over its work.

### Handoff verification on the merged application

The assignment-writing task reran these checks on application `560e2ed`, with
only documentation and two new export acceptance cases added:

| Check | Actual result |
| --- | --- |
| Clean frontend lock install | `npm --prefix frontend ci` passed; installation audit reported zero vulnerabilities. |
| Frontend unit/consumer tests | `npm --prefix frontend test`: **147 passed**. |
| Production build/TypeScript | `npm run build`: passed. |
| Focused backend | `test_release_exports.py`, `test_lesson_provider_deadlines.py`, `test_simulation_correctness.py`: **61 passed**, no failures/skips. |
| Settings browser acceptance | `settings.spec.ts --reporter=line`, test-only `CHOKIDAR_USEPOLLING=1`: **7 passed**. |
| Core contract | All **43 frozen hashes**, DTO, OpenAPI and stream snapshots match. |
| New Python tests | Ruff lint and format checks passed. |
| Handoff links/diff | Local documentation links and `git diff --check` passed. |

New executable coverage in `backend/tests/test_release_exports.py` verifies
JSON/CSV/metrics/state consistency at a pinned revision across head advances and
restart, plus branch export identity and read-back after source deletion. It does
not assert physical garbage collection. Tiger/Snowflake/ElevenLabs cases are
written as required acceptance specifications; their machines must implement
the actual adapter tests alongside code. No external integration is claimed
complete from these specifications. This task did not rerun the full backend or
full browser suite and made no live vendor calls or deployment changes.

## 2026-10-24 — Machine B Snowflake comparison handoff

Implementation: `ef0aae2bc0e7519bc942a0252a50e099c8b6091b`, branch
`codex/snowflake-comparison`, based on fetched `origin/dev` at `2d22559`.
See [the Snowflake handoff](release/snowflake-handoff.md) for API/schema, SQL setup,
configuration, bounded Cortex selection, retry/crash policy and exact commands.

Delivered isolated `backend/app/snowflake/**`, a runnable real-core composition,
versioned bound SQL, durable separate request/model-budget ledger, a service-specific
frontend client/schema/component, controlled external HTTP fixtures, 30 backend
acceptance tests and two browser cases. JSON inputs come from the existing owned
export implementation at explicit revisions. Source/branch keys and citations
include simulation/revision identity; numeric differences come from verified
read-back. No Tiger dependency or scenario/lesson/provider/settings changes.

Actual results on this branch:

- Focused Snowflake backend: **30 passed** in 45.21s. Covers S-01–S-05, literal
  fixture deltas, inherited IDs, missing records, every citation resolving at its
  pinned revision, pending/completed/changed retries, response loss and restart,
  cost limits, blocked-vendor ticking, caller cancellation, SQL asynchronous
  polling/output bounds, key-pair signing and independent OpenAPI snapshot.
- Browser S-06 with the real composed application route and only the external
  Snowflake HTTP transport faked: **2 passed**. Displayed values match returned
  records, response-loss retry keeps the same key/body/result, disabled UI makes
  no integration request. This does not verify the default shared entry point.
- Frontend unit/consumer: **150 passed**; production build/TypeScript passed.
  All **43 core contract hashes**, DTO, parent OpenAPI and stream snapshots match.
- Ruff lint passed across backend; changed Python files pass Ruff format.
  Full format gate reports untouched `test_city_layout.py:96`.
- Full backend run: **325 passed, 1 failed** in 153.64s, collected before the final
  five Snowflake cases were added. The failure is
  `test_domain.py::test_repeat_evacuations_count_each_citizen_once`, `StopIteration`
  finding an unexposed shelter at line 449. Reproduced on an isolated untouched
  `git archive origin/dev` with no Snowflake files. Scenario fixes are excluded.
- Live opt-in SQL API smoke: **unverified**, HTTP 422 / insufficient privileges
  when creating the unique disposable schema. Key files/config existed, but real
  table setup/read-back and Cortex were not reached. No production cleanup or
  real Cortex success is claimed. `node scripts/snowflake-live-smoke.mjs --live`
  is the explicit rerun command after the operator grants suitable schema access.

New consumed server configuration names: `SNOWFLAKE_ENABLED`, `SNOWFLAKE_ACCOUNT`,
`SNOWFLAKE_USER`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`, `SNOWFLAKE_WAREHOUSE`,
`SNOWFLAKE_ROLE`, `SNOWFLAKE_PRIVATE_KEY_FILE`,
`SNOWFLAKE_PRIVATE_KEY_PASSPHRASE_FILE`, `SNOWFLAKE_CORTEX_MODEL`. Values remain local.
Existing pinned dependencies suffice; no shared manifests or locks changed.

**A's next action:** apply the checked
[minimal wiring patch](release/snowflake-wiring.patch) to coordinator-owned main,
capability and existing ComparePanel entry points; compose Tiger/narration routes
on the same child app, provision the dedicated runtime schema/grants, rerun real
SQL/Cortex smoke and combined public application gates. The branch provides
`app.snowflake.application:create_app` for executable adapter/browser evidence;
normal `app.main:app` wiring and full release acceptance are not claimed complete.

## 2026-10-24 — Machine A Tiger and combined integration handoff

Branch: `codex/tiger-release-integration`, from fetched dev
`2d22559368ffede1d0a5e500c487541a0120dda2`. Tiger/deployment implementation:
`a20e964`; normal merge of B's `37c5fbc` followed by shared default-app/UI wiring:
`c724845a85368660fb5d13347bf76e9f5883f219`. Final full test tree:
`0f6b3a9909aaf6babf69165fbf0acc0fa9ec302d` (additional branch deletion/restart
assertions). Subsequent handoff commits contain documentation and measured evidence.
No force push or direct dev push was used.

Delivered `backend/app/integrations/**` with versioned PostgreSQL migration,
parameterized idempotent upserts, verified TLS, bounded committed-history
reconciliation, persistent checksum/digest-bound progress, safe lag/error status
and a shared independently documented integration sub-app. Local persistence stays
authoritative. Metrics, decisions, event snapshots and sampled public agent summaries
are ingested; full relationship history/private memories/dialogue are not claimed.
Writer-lock publication precedes optional ingestion; controlled failures prove local
commits, ticks and HTTP controls survive vendor outages.

Merged B's implementation without replacing newer dev files. Snowflake and Tiger
share one mount; capability and the default History/Drawer comparison UI are wired.
Added default-app/public UI tests, isolated browser settings/city cleanup, safe
offline backup/restore tooling, one-worker systemd/Caddy configuration and operator
restart/restore/rollback steps in `deploy/`. Details:
[Tiger handoff](release/tiger-handoff.md), [validation report](release/validation-report.md).

Actual results on the combined application:

- Fresh locked frontend and isolated backend installs passed; `pip check` passed.
- Final `npm test`: **150 frontend passed; 351 backend passed / 2 opt-in skips**
  in 185.93s; all **43 frozen hashes**, DTO/OpenAPI/stream snapshots, Ruff lint and
  full format gates passed. The skipped SQL cases were executed separately below.
- Production build/TypeScript passed. Full and production npm audits: **zero**.
- Full core browser: **26 passed**, no skips/flaky/failures; test-only polling
  avoided the documented Windows Vite watcher issue. All 7 Settings cases passed.
  Snowflake browser: **3 passed**, including the default production History dialog
  and exact numeric read-back with controlled external transport.
- Real Tiger SQL/public-worker tests: **2 passed**, exact rows/totals, repeated
  delivery, branch provenance, restart and query deadline. Disposable schemas only;
  no credentials or vendor bodies were printed. The same tests on disposable local
  PostgreSQL 18.6 with verified TLS and a non-owner/non-superuser role: **2 passed**.
- Explicit source deletion -> actual app restart/read-back: focused **3 passed**;
  local backup/restore exact state tests also passed in the full suite.
- Benchmarked 10/30/100 agents and completed a configured 100-tick horizon under
  blocked Tiger. At 100 agents, normal 40-tick workload: step/control p95
  **426.72/240.14 ms**, **1.84 ticks/s**, **20.37 MiB** store. The 100-tick blocked
  workload: **539.85/335.55 ms**, **1.76 ticks/s**, **53.79 MiB**, honest **119-revision
  lag**. Full raw results and RAM/cadence limits are in the report. No 10,000-tick
  endurance or hosted SLO pass is claimed.

Initial full-browser evidence was **22 passed / 4 failed** on stale selectors and
fixed-population assumptions; all behavioral checks were retained while adapting
to the actual controls. The existing unique-evacuee test's unsafe-region fixture
was repaired without changing scenarios, and the city-layout test was formatted.
B's two route-index assumptions were updated to the shared child; cancellation and
blocked-vendor assertions remain. The report preserves these failures and reruns.

Actual new Tiger environment names: `TIGER_ENABLED`, `TIGER_DATABASE_URL`,
`TIGER_SCHEMA`, `TIGER_TIMEOUT_SECONDS`, `TIGER_REVISION_BATCH`,
`TIGER_MOVEMENT_SAMPLE_TICKS`, `TIGER_POLL_SECONDS`, `TIGER_RETRY_MIN_SECONDS`,
`TIGER_RETRY_MAX_SECONDS`; opt-in tests use `TIGER_TEST_DATABASE_URL`.
`.env.example` now documents consumed Snowflake names and stops advertising unused
password/token fields. Dependency addition is only pinned `psycopg[binary]==3.3.3`
and its matching lock entries; all vendor credentials remain server-side.

**Remaining release blockers:** C's `codex/elevenlabs-narration` branch/handoff was
still absent at the last fetch, so narration remains honestly disabled/501 and
N-01–N-07 are blocked. B reported real Snowflake smoke HTTP 422 / insufficient
schema privileges; A did not claim a fresh real SQL/Cortex pass. Vultr/HTTPS host
access, supervision, deployed security/media and host restore/rollback remain
unverified. Review and normally merge this branch after those service/host gates;
do not treat the passing local/Tiger scope as a three-service release sign-off.
Automatic review blocked cleanup of one stopped temporary PostgreSQL bootstrap
folder; it remains outside the workspace and has no effect on the app/tests.
Generated browser screenshots were retained as evidence after cleanup review
also rejected their deletion.
### Machine C: ElevenLabs narration

Branch `codex/elevenlabs-narration` (commits `e418385`..HEAD on `dev` `2d22559`).
Files: `backend/app/narration/**`, narration tests/fake/fixture, browser test
(`frontend/narration-e2e/`, `scripts/narration-e2e.mjs`), opt-in live smoke
(`scripts/narration-live-smoke.mjs`), `Narration.tsx` states, and the `main.py`
wiring also delivered as `docs/release/narration-wiring.patch`.
New configuration names: `ENABLE_NARRATION`, `ELEVENLABS_API_KEY`,
`ELEVENLABS_VOICE_ID`, `ELEVENLABS_CHARACTER_VOICE_IDS`, `ELEVENLABS_MODEL_ID`,
`ELEVENLABS_OUTPUT_FORMAT`, `NARRATION_PUBLIC_ORIGIN`, `NARRATION_*` limits.
Tests: narration backend 42 passed; N-07 browser 1 passed; frontend 150 passed;
43 contract hashes match. Live ElevenLabs verified once at 2026-10-25T03:45:45Z
(separate from fixtures). Known failure: `test_repeat_evacuations_count_each_citizen_once`
also fails on clean `dev`. Combined with Snowflake, B's two S-05 tests must use
`app.state.integrations` instead of `app.routes[0]`.
Next (A): apply wiring, `.env.example` lines and README note from
[narration-handoff.md](release/narration-handoff.md); B: the one-line test fix.

## 2026-10-25 - All assignment branches integrated with current frontend

User authorized merging A, B and C into dev, with the frontend design already
on dev taking precedence. Fetched dev/frontend tip was `e6fbc39`; A/B/C tips
were `b35bd45`, `37c5fbc` and `dc894e6`. A already contained B. Normal merges
`8761ac2` and `291a1db` preserve all branch history and both shared integrations
and authorized narration media. No force push or old frontend replacement.

All existing pages, theme/styles, world rendering/palette, gears, HUD, city art
and controls remain byte-identical to `e6fbc39`. New comparison styles use those
theme variables. Narration and Drawer receive only functional integration work.
Server/deploy environment examples now include the consumed narration settings.

`6649d1a` adds a real default-app cross-adapter regression and fixes test-only
assumptions about decimal output and removed neighbor controls. Do not restore
the removed neighbor strip to fix tests. Core browser tests disable all optional
providers explicitly; adapter acceptance uses controlled transports. The final
merged gates and remaining live/deployment limitations are recorded in
[the combined dev merge report](release/dev-merge-2026-10-25.md). Earlier branch
reports and their outdated 'C absent' status remain dated historical evidence.

Final verification on `6649d1a`: clean frontend lock install and `pip check`
passed; `npm test` passed **153 frontend tests**, **394 backend tests / 2 opt-in
SQL skips**, all **43 frozen core hashes/DTO/OpenAPI/stream checks**, Ruff lint
and **104** Python files' formatting. Production build passed. Full core browser
passed **26/26** with no flaky/skipped cases; Snowflake browser **3/3**, narration
playback **1/1**. Full and production npm audits both zero. No new paid/live
vendor calls, cloud configuration or hosting changes. Prior branch live evidence
is preserved; Snowflake schema privileges and Vultr/HTTPS verification remain
external release gates. Updated tracked test reports/screenshots show this merged
frontend. Fetch/recheck current dev before starting new work; do not reapply the
old service wiring patches, as all three are now integrated.

## 2026-10-25 - New feature-refinement assignments

The user requested written implementation tasks for live conversation voices and
richer character survival/personality/class behavior. These are specifications;
no new simulation or audio behavior is implemented by this documentation change.

- [Live conversation voices](prompts/live-conversation-voices.md): scoped automatic
  dialogue playback for the watched citizen/conversation, stable unique voice IDs,
  one bounded audio queue, browser permission, focus/replay/reconnect isolation,
  and LV-01 through LV-10 executable acceptance requirements. Extend the existing
  narration service/voice store rather than rebuilding them.
- [Survival, personality and class conflict](prompts/agent-survival-personality-class-conflict.md):
  death, fainting, a new independent Mental meter, weighted crisis modes including
  aggression/fire/withdrawal, physical hospital rescues, extra trait/need
  combinations, conserved wealth classes and knowledge-bound class hostility.
  AB-01 through AB-17 require actual engine/API/persistence/browser coverage.

**User clarified death semantics:** either Health <=0 OR Fullness <=0 is fatal
independently. Existing Fullness is `100-hunger`; Energy is `100-fatigue`.
Current HUD's fourth meter is Social, not Mental; do not silently rename it.
Unconscious citizens remain living/observable but cannot act; death takes
precedence. Compassion can overcome class bias; new aggression/fire still passes
physical Game Master legality. Preserve current dev frontend design.

Audio owns narration modules; behavior owns engine/state and coordinated contract
evolution. Coordinate shared focus/HUD hooks instead of replacing one another's
files. Core v1 snapshots remain frozen: new action/life schemas need an explicit
versioned API/migration and matching consumers/security. Existing secrets, runtime
data and the running dev server are unchanged by these task files.

### Stress-triggered crises added to the behavior assignment

The user requested high stress (~80%) to cause the same effects as low Mental.
The [behavior task](prompts/agent-survival-personality-class-conflict.md) now
specifies **Mental <=10 OR Stress >=80**, each sufficient independently, with
one shared personality-weighted crisis episode. Simultaneous triggers do not
duplicate effects; cause evidence identifies one or both. Initial recovery
requires Mental >=25 AND Stress <=60 for three consecutive ticks.

Current code has a Stress metric but no independent Mental value, so there is
no existing stress-to-Mental mechanism. The implementation task now explicitly
requires bounded sustained-stress Mental loss plus recovery, without treating
Mental as `100-stress`. AB-05 adds independent threshold boundaries; new AB-18/19
cover combined triggers, exit hysteresis and persisted stress/Mental interaction.
This update changes task specifications only; concurrent implementation edits
are outside this documentation commit.

## 2026-10-25 - Recover citizen activity after scenarios

Reproduced a physical movement deadlock in saved worlds: simulation ticks and
stream updates continued while citizens held unchanged paths at shared doorways.
The indoor collision bypass rejected room floors as walls, and a nonempty path
suppressed new autonomous choices indefinitely. Routine destinations also checked
declared building capacity instead of the remaining physical room slots.

Movement now plans around current crowds, supports collision-free indoor detours
within authorized rooms, and preserves explicit doorway crossings. Tangential
escape tolerates floating-point rounding. Six consecutive nonmoving attempts
release the stale route and room reservation, invalidate pending deliberation,
and allow a new choice. Routine visits select facilities with physical space.
`Citizen.blocked_movement_ticks` defaults to zero for existing checkpoints; public
v1 contracts and frontend design are unchanged. Scenario outcome pauses remain
intentional: Continue restores prior play intent, while manual stepping stays
paused.

Regression coverage includes sustained post-event activity in 10-person suburbs,
10-person urban worlds and 80-person cities, tangential crowd escape, bounded
stalled-route recovery, wall constraints and physically full facilities. The
liveness checks require continued travel across the population and useful
completed actions for citizens staying put to eat, rest or work. A new real
browser test verifies Play, outcome, Continue, later autonomous movement and
rendered map coordinates received through the live stream. Conversation UI tests
now bring their participants together through normal movement before inviting
them, independently of their autonomous errands.

Restarted the local dev application with the fix. In a disposable branch of the
user's existing 80-agent city, **all 80 citizens moved** while advancing from tick
27 to 67, with a LIVE connection and no browser errors. Removed the temporary
branch; the original city remains saved and paused at tick 27. No vendor calls
or history rewrites were needed.

Final validation: `npm test` passed **153 frontend tests**, **401 backend tests**
with **2 opt-in Tiger SQL skips**, all **43 frozen contract hashes/DTO/OpenAPI/
stream checks**, Ruff lint and formatting. The full core browser suite passed
**27/27**. Local evidence is retained under `backend/.tmp/movement-validation/`
and `backend/.tmp/movement-recovery-live/`; generated baseline reports and
screenshots are not part of this source change.

### Intuitive metric-to-need coupling specified

The user requested Happiness, Safety, Trust, Resources and Stress to affect
Mental, Social and Energy. The behavior assignment now includes a causal matrix,
initial versioned per-tick coefficients/caps, trusted-contact Social multipliers,
rest-only Energy multipliers and per-contribution explanations. Social fulfillment
remains `100-needs.social`; Energy remains `100-needs.fatigue`; Mental is separate.

No passive social satisfaction, free working stamina or nutrition from unused
supplies. Derived Safety/Resources/Trust use canonical causes and local directed
ties; one frozen-input coupling phase executes per physical tick, never per frame
or read. New AB-20 through AB-23 cover exact effects, directions, neutral bands,
real interactions/rest/nutrition, time scaling, feedback/deduplication, restart and
long-run recovery. Existing Mental <=10 OR Stress >=80 crisis thresholds and
Health/Fullness death precedence remain unchanged. This is a task-specification
update, not implementation or validation of the new engine model.

## 2026-10-25 - Relationship progression, learned outcomes and Snowflake task

Added the [relationship and learning assignment](prompts/relationships-learning-snowflake.md)
on proposed branch `codex/relationships-learning-analytics`, linked from the
survival/personality/class-conflict task. Required progression is strangers ->
acquaintances -> friends -> best friends, with optional mutual lovers -> married
and arguing -> enemies paths. Friendship, romance/commitment and conflict are
separate axes so an argument does not erase a marriage. The prompt specifies
directed feelings, threshold/cooldown defaults, consent, kinship, reconciliation,
legacy migration and preservation of frozen v1 contracts.

Survival/rescue/crisis/hazard/class experiences must create evidence-backed,
persisted lessons that change later choices in both rules and Gemini paths.
The reference collapse fixture changes voluntary rest from Energy <=20 to <=25,
without altering real Energy or the Energy 0 fainting rule. Learning stays bounded,
knowledge-based and subordinate to life state, consent and physical action rules.

Snowflake currently projects metrics plus bounded recent events/decisions, not a
complete relationship/learning history. The task requires a versioned export/SQL
read model, idempotent ingestion, correct pair versus directed counts, learning
opportunity/application/outcome statistics, branch/revision provenance and cited
comparisons. Missing warehouse coverage must remain explicit, with truthful local
fallback. RL-01 through RL-18 specify required executable tests plus an opt-in live
warehouse check. This change writes task specifications only; it does not implement
the new mechanics, run their future tests or claim live Snowflake verification.

## 2026-10-25 - Disaster controls, persistent damage and ElevenLabs audio tasks

Two new assignments are ready for implementation instances:

| Assignment | Proposed branch | Ownership |
| --- | --- | --- |
| [Disaster size/intensity and lasting map damage](prompts/disaster-controls-persistent-damage.md) | `codex/disaster-controls-damage` | Scenario controls/preview, canonical geometry/exposure, building/terrain/service damage, routing, repair, versioned source events and exports. |
| [ElevenLabs effects, music and screams](prompts/elevenlabs-disaster-audio.md) | `codex/disaster-audio` | Effects/music capabilities and jobs, agent reaction selector, authorized media/assets and shared mixer integration. |

Size and danger are independent. The first assignment specifies earthquake
magnitude, tornado wind speed/track, existing flood/fire/storm controls and lasting
building/road/terrain consequences. Resolution removes only its temporary effects;
it cannot blindly restore `infrastructure_before` over real structural damage or
another event's restrictions. Agent routing, hospitals, claims, occupancy, repair,
save/replay/branch and Tiger/Snowflake evidence must use actual committed state.

The second assignment uses ElevenLabs sound-effect/music endpoints separately
from TTS, with official API references checked on 2026-10-25. Generate/cache bounded
disaster assets, mix one scary instrumental bed with local effects, and preserve
each agent's assigned identity for eligible fear screams/cry-for-help reactions.
No dead/unconscious/remote screams, preview-triggered generation or whole-city
playback flood. The live-conversation task now explicitly shares one coordinator
with serialized foreground voices and centrally mixed/ducked background buses.

Coordinate the typed lifecycle/perception source contract early: disaster owner
publishes committed event/phase/geometry/intensity/evidence records and wires one
reaction hook; audio owner supplies a deterministic selector plus fixture adapter.
Neither branch may mutate frozen v1 enums or create a competing fear/crisis/audio
loop. These tasks integrate with the survival and relationship-learning assignments.

DS-01 through DS-18 and DA-01 through DA-16 specify required executable functional
tests. The audio task also requires an opt-in real-provider generation/listening
check; fake bytes cannot prove a rumble, scary score or distinct scream sounds
correct. This commit writes prompts and coordination notes only; it implements
none of these mechanics and does not claim the future tests or paid calls ran.

## 2026-10-25 - Live conversation voices

Implemented `docs/prompts/live-conversation-voices.md` on
`codex/live-conversation-voices`, based on fetched dev `720ecab`. One page-level
coordinator follows the selected citizen's direct replies or an explicitly watched
interaction, consumes committed WorldStore dialogue and plays one line at a time.
New controls provide gesture-based enable/resume, mute/volume, audio pause,
explicit replay, Retry/Skip and bounded catch-up. Focus, branch, history, page exit
and session revocation invalidate pending audio immediately. The existing design
and manual event/decision narration remain in use.

The strict versioned narration extension pins sources to owned revisions and
speaks dialogue without name prefixes. Voice assignments remain persisted and
inherited, reserve historical identities, and keep assigned speakers usable when
the pool runs short. Server-side bounded voice access checks, exact operation-key
retries and existing authorized signed media/cache paths remain enforced. Tests
exposed and fixed a concurrent cache sweep deleting an in-progress recording;
active files are protected through metadata commit. Cache reservations are also
serialized across concurrent syntheses.

Final verification: **165 frontend tests**, **54 narration/voice/cross-adapter
backend tests**, **5 narration browser tests**, **26 core browser tests**, **3
Snowflake browser tests**, production build, all **43 frozen core hashes/DTO/
OpenAPI/stream checks**, Ruff and formatting passed. A broad implementation-stage
run additionally passed **403 backend tests / 2 opt-in SQL skips**; final cache
and browser-permission refinements were covered by the final focused gates.
Controlled cached transitions were **75.1 / 35.7 / 46.8 ms**, with one active player.

Current machine has **zero configured ElevenLabs character voices**, so real
synthesis and cold latency remain unverified. The opt-in live helper reports this
honestly and never calls a paid vendor without `--live`. No mortality/crisis
mechanics, frozen contract changes, secret changes or public deployment were made.
Configuration, limits, acceptance evidence and commands:
[live voices handoff](release/live-voices-handoff.md).

## 2026-10-25 - Survival, personality, care and class behavior v2

Branch `codex/agent-survival-and-class-conflict`, based on fetched dev `720ecab`.
Implementation `4bca86b` (engine/state/contracts/tests) and `4e198a2`
(UI/consumers/browser evidence). Merge `4267187` preserves dev's subsequent
`61f286c`/`bf3be19` assignment documentation. No force push or direct dev push.
Rules **2.0.0**, balance seed **42**, no dependency/environment additions.
Detailed formulas, limits, migration, API and integration ownership are in
[the behavior handoff](release/agent-behavior-handoff.md).

Delivered independent persisted Mental; raw independent fatal and crisis
thresholds; life/episode/care transitions; once-per-physical-tick attributed
metric/need coupling; deterministic passive wake and bounded crisis behavior;
Game Master attacks/real bounded fires/suppression; observed physical pickup,
transport, reservations, cooperative first aid, hospital stock/treatment/release;
conserved unequal inventories, public class beliefs, directed hostility/solidarity,
local communicated grief and a structured collapse lesson that changes later rest
choices. Death preserves identities/possessions/history and invalidates actor work.
The existing voluntary rest baseline remains Energy 35; personal collapse lessons
raise it to 40 then at most 45, independently of the physical Energy 0 boundary.
The companion learning task owns broader topics/progression and its 20->25 reference.

The strict behavior extension is under the existing guarded integration mount,
with a separate `contracts/v2` producer/consumer schema and pinned export.
Core DTO/enums, v1 snapshots/hashes and streams remain unchanged. Mental is a
fifth life meter; Social keeps its existing inverse-need meaning. World markers,
care/cause/explanation displays, population labels, impossible-command guards and
v2 evidence navigation use the existing design. Narration/audio coordination,
voices, scenarios and provider powers are preserved; providers receive own bounded
condition/learning context only.

Final commands/results on the committed integrated source:

- `npm test`: **156 frontend passed; 446 backend passed / 2 opt-in SQL skips**;
  all **43 frozen v1 hashes**, DTO/OpenAPI/stream snapshots, Ruff lint and full
  formatting passed. The extra indoor pickup case traverses a real room floor
  before the existing doorway route. No external paid providers were used.
- `npm run build`: TypeScript and production bundle passed.
- `npm run test:e2e -- --output=../backend/.tmp/behavior-core-final`:
  **26/26 core browser passed**.
- `npm exec --prefix frontend -- playwright test --config=frontend/playwright.behavior.config.ts`:
  **4/4** actual faint/rescue/hospital/recovery, fatal Fullness, seeded crisis/class
  displays and v2 memory-evidence navigation passed.
- Same Playwright invocation with `playwright.snowflake.config.ts`
  (`--output=../backend/.tmp/behavior-snowflake-final`): **3/3** passed; with
  `playwright.narration.config.ts`
  (`--output=../backend/.tmp/behavior-narration-final`): **1/1** passed. External
  transports are controlled fixtures, separate from live vendor verification.
- Pure and actual-engine **300-tick** curves, unchanged initial coupling weights,
  rate table and seed are committed under `backend/artifacts/behavior-*.json`.
  Supported routines recover Mental/Energy/Social while resource consumption is
  conserved. The feature screenshot was visually inspected. `git diff --check`
  and focused schema, persistence/branch/source-delete/security cases passed.

Issues found and resolved: initial poor-household weights left less than one
food unit (redistribution adjusted from 0.3/0.8/1.9 to 0.4/0.8/1.8 without changing
total stock); conserved hospital ledger needed the shared event-key shape; urgent
safety routing bypassed the old stale-proposal discard hook; v2 routes required an
updated **non-frozen child** OpenAPI snapshot. Test setup errors in checkpoint
revision numbers/idempotency and browser selection/artifact locations were fixed
without weakening behavioral assertions.

A later full run exposed a Tiger journal-deletion/publication race. Reconcile
could return pending=true without reading any revision, spinning before the
service could remove the deleted head. It now returns actual advancement; a
controlled publication-gap regression and the full Tiger branch/restart/deletion
suite pass. That hung run was stopped and is not claimed as a passing gate.
The final fresh full gate above passed after the fix.

**Handoff limits:** Tiger and Snowflake continue their existing v1 read models;
they explicitly do not claim new v2 behavior/learning analytics. The versioned
local export has the new records. The relationship/learning assignment should
consume these IDs/outcomes and extend its own structured learning, relationship
stages and warehouse ingestion; no complete marriage/enmity/learning-decay system
is claimed here. Fire spread is deliberately zero, simultaneous fires are capped
at three and active destructive behavior is time bounded. Existing opt-in live
SQL, warehouse privilege and deployed-host gates remain external/unverified by
this task. No live ElevenLabs/Tiger/Snowflake verification or deployment was run.

## 2026-10-25 - Merge scenario, survival and live conversation branches into dev

Integrated `scenario-engine` (`0164bf9`),
`codex/agent-survival-and-class-conflict` (`e062bcf`) and
`codex/live-conversation-voices` (`97cdf12`) through normal merges. The user
explicitly excluded `codex/disaster-controls-damage`; its `16bed98` tip is not
an ancestor of the resulting integration. That tip contained voice integration,
not implemented disaster controls. Existing dev design and frozen v1 contracts
remain the base.

Candidate `7c3815a` combines scenario lifecycle/decision hooks with survival
ordering, one need-decay phase, consciousness checks and canonical care. Resolved
the shared transport's timeout-versus-cancellation conflict. Fixed unconscious
scenario shopping/reviews/social decisions, immediate scenario-health death
evaluation and duplicate/free hospital healing. Kept the existing crowd recovery
changes in `1279297`, with a retained safety snapshot of the original working diff.
Added eight backend and two transport integration cases plus a real manual-policy
composer browser flow. Updated the integration-child OpenAPI, not frozen v1.

Final root `npm test`: **175 frontend, 483 backend passed, 2 opt-in SQL skips**;
all 43 frozen hashes/DTO/OpenAPI/streams and Ruff checks passed. Production build
passed. Browser suites: **28 core + 4 behavior + 5 narration + 3 Snowflake = 40
passed**. Tests use disposable stores and controlled/disabled providers. No paid
provider, public hosting or live warehouse verification is claimed.

See [combined feature merge evidence](release/feature-merge-2026-10-25.md) for
branch/merge commits, resolved conflicts, initial failures, exact test boundaries,
preserved local evidence and remaining external gates.

### Launcher recovery allowance after the feature merge

Actual local restart with 18 saved worlds/9,703 objects/2.97 GiB compressed history
exceeded the old 300-second launcher timeout. Follow-up `866662a` adds validated
`BACKEND_STARTUP_TIMEOUT_SECONDS` to both Node launchers: default 600 seconds,
allowed 30..1800, with a startup message and environment/README documentation.
It preserves integrity checks and HTTP deadlines; storage compaction/endurance
remain separate work. Configuration boundary/invalid-input and syntax checks pass.
Both real launch commands also passed fresh-store readiness, frontend and new
scenario/behavior API smoke checks; the temporary test servers were stopped.

The full original store then recovered successfully. The merged app is running on
5173 with 18 restored worlds, 15 scenario operations and the behavior extension.
A read-only Chrome visit to the existing city was LIVE with no page/API errors
or mutation requests; smoke JSON/screenshot evidence is in the ignored merge
evidence directory. Cold-history recovery remains slow, despite the larger allowance.
## 2026-10-25 — persistent disasters and shared soundscapes

Continued `origin/codex/disaster-controls-damage` at `16bed98`; its scoped live
voices were already present. Implemented independent typed earthquake/tornado/
flood/fire/storm controls, clipped/revision-bound previews, origin/track editing,
late-request generations and exact commits/repeats. The versioned disaster
extension leaves frozen core v1 contracts unchanged and projects newer types
compatibly. A live activation bridge preserves existing flood/fire/storm scenarios.

Added one deterministic physical hook after movement, persistent integrity and
terrain/stock damage, service derivation across concurrent closures, obstruction
routing, trapped/egress evidence, timed supply-consuming repairs and separate
occupied-doorway clearing. Zero-health actors cannot receive actions through a
provider proposal or be counted as safely evacuated. Conditions, causes, service
transitions, reactions, repairs and parameters persist through checkpoints/history
and independent branches. Both map modes and inspectors expose real condition;
exports and additive Tiger/Snowflake projections retain canonical records.

Extended existing narration transports, cache, receipts, voice assignments and
signed private media for distinct ElevenLabs effects/music/expressive reactions.
The page coordinator retains one foreground voice, mixes bounded background beds,
ducks them, follows the listener, honors mute/visibility/replay/focus and discards
obsolete results. Citizen voice failures stay local to their assigned identity.
Provider-disabled tests use real marked/decoded MP3 transport and browser playback.
Added a four-sample opt-in live helper; it never bills by default.

Verification on this implementation:

- Broad root `npm test`: **448 backend passed / 2 opt-in SQL skips**, **174 frontend
  tests**, all **43 frozen hashes/DTO/OpenAPI/stream checks**, Ruff and format passed.
- Final physics/action/routing refinements: **127 backend functional cases** passed;
  final provider/identity/audio refinements: **19 backend audio cases** passed.
  The extra assigned-voice rejection case was added after the broad collection.
- `npm run build`: TypeScript and production bundle passed on final frontend sources.
- Narration/browser suite: **8 passed** (existing live/manual voice cases plus
  disaster controls/damage, decoded environmental/music playback and preview races).
  The **3 disaster browser cases** were rerun after final source changes and passed.
- Existing core browsers: **26 passed**; Snowflake browsers: **3 passed**.
  Run latency-sensitive voice tests separately from the GPU-heavy core suite.
- Configuration-only smoke: narration configured, **24** supplied character voice
  IDs, disaster effects/music/reactions all disabled. **No paid verification calls**.
  Real music entitlement, expressive delivery, voice quality, loop quality and
  loudness audition remain unverified; the helper reports `audition_required`.

Testing caught and fixed aborted unlock promises incorrectly disabling sound,
mobile audio/control overlap, disappearing condition controls between live frames,
late preview response races, zero-health agency/evacuation counting, truncated MP3
acceptance and a single unavailable reaction voice affecting other citizens.
Screenshots are in `frontend/artifacts/disasters/`.

Configuration, exact routes/rules, compatibility, measured bounds and remaining
limits: [disaster controls handoff](release/disaster-controls-handoff.md),
[disaster audio handoff](release/disaster-audio-handoff.md). The separate survival
state machine and live SQL/provider audition are not claimed as shipped here.
The tested source commit is recorded in the following verification note.

### Disaster verification note

Tested implementation commit: **`b10701f`**. Final source checks after the broad
448-case collection passed the **127** physics/action/routing regressions and
**19** controlled audio cases (including one unavailable voice while another
assigned voice remains usable). Final frontend build and all **174** unit tests
passed. The **8** combined narration/disaster browser cases passed; the **3**
disaster cases passed again with the final cancellation/scenery and voice-error
isolation code. All **43** frozen core checks and Ruff/format gates passed.
The following evidence update waits for the reloaded damaged map before taking
its screenshot; it changes test readiness and reporting only.

### 2026-10-25 — Machine A: disaster controls/damage/audio merged with current dev

User explicitly requested merging `codex/disaster-controls-damage` (`0d60ed5`) and
restarting the local app. Read controls/audio handoffs and shared log. Normal merge
`5fc0083`, service composition fix `5f9575c`, and browser readiness fix `664df38`
preserve current scenario, survival, care/rescue, behavior and live voice systems.
Added eleven cross-feature regressions. Final gates: 184 frontend and 538 backend
passes (2 opt-in skips); both real disposable PostgreSQL cases separately passed;
43 browser passes (28 core, 8 narration/disaster, 4 behavior, 3 Snowflake); production
build, 43 frozen core hashes and Ruff/format passed. Initial failures and fixes,
10/30/100-agent performance measurements, evidence paths and external limitations
are recorded in [the disaster merge report](release/disaster-merge-2026-10-25.md).
No paid provider calls or real disaster-audio listening audition claimed.

Disaster merge restart follow-up: verified merge/report `25e1883` pushed normally
to dev and the integration branch. User-authorized original-store restart reached
readiness; **20/20** saved cities restored paused. UI `http://127.0.0.1:5173`,
same-origin capabilities and new disaster state/OpenAPI returned 200. Current
Gemini/narration enablement was preserved; no paid provider call or smoke mutation.
Original production build passed, and unrelated local README edits remain intact.
See the merge report and ignored before/after restart evidence for details.

### 2026-10-25 — Floating character name and neighborhood navigation

Moved the selected citizen's full name and explicit **Back to neighborhood**
control into a floating header above the agent card. Header and card share a
responsive vertical layout so the title/navigation remain outside the scrolling
card on desktop and mobile. Conversation details, close, invitations and building
visits retain their behavior. Existing close-up browser expectation follows the
visible external heading. Production build and all **3** focused close-up/setup/
building-walk browser cases passed; desktop/mobile screenshots were visually
checked. Evidence: ignored `backend/.tmp/floating-agent-header-browser/` and its
sibling build/browser logs. The running dev frontend updates through Vite; no
backend restart or paid provider call was needed. Unrelated README edits preserved.

### 2026-10-25 — Ground-level camera panning and clipping

Reproduced vertical screen-space panning lowering the camera target 22.18 meters
below the ground. OrbitControls now pans parallel to the ground. The orthographic
camera also fits city depth after orbit, follow and close-up transitions: it moves
the eye backward along its viewing direction when the near plane would intersect
the city and expands far depth as needed. Orthographic framing/zoom and the user's
target remain unchanged; fog distances follow the eye so this adjustment cannot
fade out the neighborhood. Bounds include the ground and tallest building/spire.

Added two geometry regressions proving a previously clipped city fits the depth
range with unchanged screen coordinates and distant panning retains its target.
Added actual mouse orbit/pan browser regressions in dark desktop and light mobile
views, checking ground-plane target height and the map's near/far depths. Updated
the existing large-city selection expectation for the preceding floating name UI.
Final checks: **186 frontend tests passed**, production build passed, **30/30 core
browser cases passed** with no skips/flakes. Low-angle desktop/mobile screenshots
were visually checked. Evidence: ignored `backend/.tmp/camera-ground-evidence/`
plus `backend/.tmp/camera-ground-final-core/`. No backend restart, saved-city
mutation or paid provider request was needed; unrelated local README preserved.
