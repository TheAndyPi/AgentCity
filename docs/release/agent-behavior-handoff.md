# Agent survival, personality and class behavior

Implemented on `codex/agent-survival-and-class-conflict`, starting at fetched
`origin/dev` `720ecab`. Gameplay rule version **2.0.0**. No paid provider calls are
needed by the new tests. The frontend retains dev's existing world, colors,
controls and audio components; this adds condition/evidence displays and strict
extension consumers.

## State and compatibility

`Citizen.condition` persists independent Mental (default 70), life transitions,
causes/evidence/tick, crisis episode/cooldown, rescue links, class beliefs, wealth
band and the last 120 meter contributions. Citizen `rest_lessons` stores bounded
structured personal-collapse lessons. `State.behavior` persists events, decisions,
fire and hospital state, counters and a separate crisis RNG stream. The original
world RNG continues to govern actor ordering. Crisis RNG is seeded from
`<world seed>:2.0.0:crisis`, then checkpointed; branches copy both streams.

Legacy parsing supplies neutral defaults without modifying stored objects or
running transitions. Rules activate at the next live physical tick, with an
explicit activation event. Existing inactive citizens are treated as dead without
retroactive death/grief events. Old checkpoints remain immutable. A legacy living
citizen already at a fatal boundary dies at that live evaluation, never at startup
or during a read. New worlds activate rules and redistribute/fund resources during
initialization; no names or occupations determine personality or wealth.

V1 schemas/enums/OpenAPI/streams remain frozen. The separate strict
[behavior v2 contract](../../contracts/v2/CONTRACT.md) exposes pinned conditions,
learned rules, events, physical actions, hospital inventories and analytics under
the existing authenticated integration mount. No unguarded `/api/v2` namespace or
new stream was introduced. Existing control writes retain ownership, Origin,
CSRF, idempotency and control-version checks. Incapacitated/care-state commands
are rejected. The current UI routes behavior evidence IDs to their own reader.

## Physical ordering and thresholds

Health is `needs.health`; Fullness `100-hunger`; Energy `100-fatigue`; Social
`100-social`. Social is never used as Mental.

1. Evaluate fatal/faint conditions before selection. Health <=0 OR Fullness <=0
   kills; cause order is health, fullness if simultaneous. One death event retains
   possessions and historical identity, invalidates plans/provider generations,
   ends interaction participation and releases transport/beds/reservations.
2. A living Energy <=0 citizen faints. Unconscious citizens remain observable and
   living but cannot select ordinary actions or move autonomously.
3. Seeded actor order applies safety, rescue, crisis, suppression/mutual aid and
   ordinary decisions through their respective Game Master checks. Recheck a
   target before aid/attack; a citizen killed earlier cannot act later.
4. Movement follows existing grid routes, entrances, speed and hazard checks.
   Consumption/rest happens **before** normal decay. Every living citizen,
   including patients, receives baseline decay (per 10 simulated seconds):
   Fullness -0.6, Energy -0.4, Social -0.2. Evaluate thresholds immediately.
5. Apply scenario/engine-fire exposure and functioning hospital care, evaluating
   fatal boundaries after effects. Refresh canonical derived metrics, freeze the
   coupling inputs, apply the single background phase, then check crisis recovery.

A raw 0.1 never rounds into death/fainting. Initial fatal state cannot be rescued
by eating/healing first. Unconscious passive Energy recovery is +1.5 per 10s before
normal decay/pressure, with waking only at Energy >=20. Hospital bed recovery is
+4 times rest quality per 10s. Hunger and hazards remain effective; there is no
starvation grace period or resurrection. All-dead worlds stop advancing physical
ticks and report zero survival, including when the death precedes selection.

## Metric interactions and attribution

The tuning data is `backend/app/behavior/rules.py`; pure deterministic
`coupling()` returns attributed simultaneous outputs. Coefficients match the task's
initial table without balance changes. For H/S/T/R, `bad=max(0,min(1,(40-x)/40))`
and `good=max(0,min(1,(x-60)/40))`; Stress uses
`strain=max(0,min(1,(Stress-40)/60))`. Multiply all background rates by
`tick_seconds/10` exactly once.

| Input | Mental good / bad or strain | Social loss | Energy loss |
| --- | --- | --- | --- |
| Happiness | +0.12 / -0.30 | 0.15 bad | 0.12 bad |
| Safety | +0.10 / -0.35 | 0.10 bad | 0.20 bad |
| Trust | +0.08 / -0.20 | 0.15 bad | 0.10 bad |
| Resources | +0.06 / -0.30 | 0.10 bad | 0.18 bad |
| Stress | 0 / -0.55 strain | 0.20 strain | 0.30 strain |

Caps per 10s: Mental [-1.50,+0.30], Social loss 0.50, Energy loss 0.60. Aggregate
clamping happens once; component attribution is scaled to the actual final meter
change, avoiding intermediate clamp errors. Reasons retain phase/tick/evidence;
base decay, activity, environment, care and metric pressure are separate. Safety
already includes health/hazard deficit, so there is no duplicate background pain
charge. Attack distress and witnessed/heard grief are separate acute events.

Friendly accepted conversation's base Social +5 uses exactly the task's directed
partner-trust multiplier (0.50..1.60). Unknown partner trust is neutral 50. Hostile
contact gets no friendly support restoration. Accepted support gives Mental +3
and Stress -3; explicit accepted comfort restores base Social +6. Invitations
alone do not restore social needs. Quiet rest gives Mental +0.5 and base Energy
+6 using the task's 0.50..1.40 rest multiplier. A Resources recovery bonus requires
actual food/water holdings and hunger <45; unused supplies never feed anyone.
Movement/work produce no positive Energy. Metrics refreshes, rendering, saves,
exports and drawers run no coupling/learning phase.

## Crises, violence and fires

Mental <=10 OR Stress >=80 enters one episode. Both causes share a mode roll;
a second crossing adds evidence without replacing the episode. Selection weights
combine existing sociability, empathy, cooperation/risk, own hunger/stress,
perceived safety, own grief memories and known directed conflict. Without a
specific grievance (conflict >=30), aggression/fire weights are zero. With one,
low empathy/cooperation and high risk increase violence weight; wealth alone
cannot cause an attack.

Modes: withdrawal to a known safe home (including leaving work), panic/flight,
support seeking, aggression, and destructive ignition. Nutrition/immediate safety
still take precedence. Active crisis behavior lasts at most 60 ticks; afterwards
only recovery behavior runs within the same episode. It does **not** falsely mark
recovery while a trigger remains. Ending requires Mental >=25 AND Stress <=60
for three distinct full ticks, followed by a 12-tick cooldown.

New actions have separately persisted decisions; rejected attempts have no
physical effects. Attack requires a conscious actor, an aggression episode,
specific grievance, perceived same-room target within 3m and its budget/cooldown.
Damage is capped at 12 per accepted attack, at least three ticks apart, and fatal
health loss is handled immediately. Local witnesses/victims retain evidence.

Ignition requires a destructive episode and visible local entrance access within
3m. Home/work/shop/community furnishings are eligible; hospital/shelter are not.
One ignition per episode, at most three live fires, radius 3m, severity 60, lifetime
12 ticks, **zero spread**. Exposure costs Health 1.2 per 10s and raises stress.
Safe cooperative, compassionate citizens with sufficient risk tolerance can
suppress a visible nearby fire using one actual water unit. Cautious citizens warn
from safety; exposed citizens use the existing legal evacuation policy. Expiry and
suppression resolve actual hazards. Scenario hazards remain on their existing
mechanics; this does not implement the separate persistent-disaster assignment.

## Rescue and hospital care

Helpers require consciousness, Health >60, Energy >25, Fullness >25, Mental >25,
mobility >=20 and immediate safety. Empathy/cooperation >=65 increases willingness;
directed ties and perceived class affinity affect selection/refusal. Victims must
be locally perceived, unconscious or Health <=45. A conscious escort requires a
trusted (trust >=50), cooperative (>=40) patient. Unconscious pickup needs no
fabricated consent/action.

Atomic rescue claim -> physical pickup -> transport -> real indoor admission ->
stock-consuming treatment -> release. One helper/patient link and one hospital
reservation per patient. Pickup precedes synchronized transport; no snap from a
remote position. Transport uses existing entrances/routes at half the slower
participant's speed, with an explicit shared-position transport exception.
Cooperative neighbors can accept an actual aid-team role and consume their own
supply for stabilization once per membership, while the carrier transports.

Reservations also block ordinary visitors from consuming a promised bed. Closed,
full or unreachable hospitals reject the claim; safe local first aid is a fallback.
Carrier faint/death/cancellation drops an already transported patient at the real
carrier position; an unpicked patient remains at their own position. Closure or
new danger releases the claim. No fabricated capacity, healing, stock or reward.

Each hospital is funded once by transferring up to six food, water and supply units
from actual public depots; funding is logged as a conserved transfer. Per 10s,
treatment consumes 0.25 supplies for Health +3, Mental +1 and Stress -2; food/water
care consumes 0.25 actual units each as needed and restores Fullness 12/unit.
With no supplies/nutrition stock, only real bed rest remains. Consciousness plus
Health >=75 releases the patient/bed. Death/closure releases capacity once.

## Class, grief and learning

Raw wealth is food + water + 2*supplies, independent of the capped Resources
meter. Nominal poor/rich boundaries are 10/24, with two-unit hysteresis: starting
from middle, enter poor below 8/rich at 26; leave poor at 12/rich below 22.
New household pools are redistributed by repeating spawn-index weights
0.4/0.8/1.8, normalized over the existing fixed total. Hospital funding draws from
public depots, separately. Existing legacy inventories are not redistributed.

Others' class is learned only from observed public gather/trade/work signals;
records cite actual committed decisions and disclose a band, not raw inventory.
Private remote changes do not update beliefs. Signals/affinity changes have a
12-tick cadence. Rich-to-poor contempt is capped at -3 directed affinity; empathy,
cooperation and supportive ties can outweigh it. Perceived affinity affects local
encounter scoring, trust/respect/affection/conflict and aid/trade willingness.
Observed large allocations while personally deprived can produce a specific poor
citizen's grievance; cooperative poor neighbors can build solidarity. Sharing
transfers a real food unit and never substitutes for subsequent eating. No theft
or new currency/law powers were added.

Grief costs Mental 8 once when a close person's death is witnessed or learned
through a real local recorded report. Unrelated discussion of death cannot reveal
a remote death. Unconscious listeners do not acquire ordinary speech knowledge.
Accepted support/rest/care can aid recovery; memories do not broadcast globally.

The companion learning addition on dev is supported by canonical versioned
outcomes, changing class beliefs/directed preferences, and a structured personal
collapse lesson. After waking from an actual recorded faint, voluntary rest Energy
threshold increases from the existing 35 to 40, then at most 45. Actual Energy and
fatal/faint boundaries never change. The lesson stores source, learner, confidence,
before/after, tick/revision, rule version and last application. Rules choose rest
or home earlier; provider context gets bounded lesson retrieval. A recorded
`lesson_applied` cites the validated decision. Neutral legacy state has no lessons;
reads/replay never learn. The companion assignment owns broader topic-specific
learning, contradiction/decay, relationship progression and Snowflake social
projection; those are not claimed implemented here.

## Analytics, balance and verification

The v2 export reports living (including unconscious), unconscious and dead counts,
survival denominator = all retained citizens, per-cause deaths and event counters
for rescues/admissions/crises/ignitions/class aid/conflict/learning. A death with
both causes appears in both cause buckets but is one death. Zero population yields
zero survival. Mean core metrics use living citizens, with composition change
explicitly labeled. Dead citizens never count as successfully evacuated.
Tiger/Snowflake retain their old projections and explicitly do not claim v2
behavior/learning analytics support. No live vendor/deployment verification is
claimed by these deterministic tests.

Seed **42** and rate table are preserved in
`backend/artifacts/behavior-balance.json`; 300 real supported ticks are in
`backend/artifacts/behavior-engine-balance.json`. Neutral background preserves
Mental 40; deprived and stressed fixtures reach 0 with bounded curves; recovering
background reaches 100 without passive Social/Energy creation. In the real
supported routine, Mental rises from 30.574 to 100, Energy from 31.321 to 65.183,
Social from 80.465 to 99.4, Health remains 100; conserved resource loss exactly
matches consumption. No initial coupling coefficients were changed.

Executable coverage is in `backend/tests/test_behavior.py`, strict consumer tests
in `frontend/tests/behavior.test.ts`, and real browser flows in
`frontend/behavior-e2e/behavior.spec.ts`. These exercise independent fractional
fatal/crisis boundaries, killed-before-turn, passive wake/drop/starvation,
consent/cooldowns/bounded fires, actual rescue travel/admission/recovery, competing
helpers/beds/blocked routes/no stocks, local grief, public wealth beliefs,
conservation, immutable reads, restart/branch/source deletion, security, exact
canonical coupling/time scaling, long-run recovery, learned rest, visible UI and
v2 evidence navigation. Existing backend/frontend/contract/browser suites remain
part of the gate.

Implementation commits: engine/contracts/tests `4bca86b`; UI/consumers/browser
`4e198a2`; upstream documentation merge `4267187` (dev `bf3be19`). Final verification:

| Command | Result |
| --- | --- |
| `npm test` on the committed integrated tree | 156 frontend; 446 backend passed, 2 opt-in SQL skips; 43 frozen v1 hashes/DTO/OpenAPI/streams; Ruff lint/format passed. |
| `npm run build` | TypeScript/production build passed. |
| `npm run test:e2e -- --output=../backend/.tmp/behavior-core-final` | 26 core browser cases passed. |
| `npm exec --prefix frontend -- playwright test --config=frontend/playwright.behavior.config.ts` | 4 behavior browser cases passed. |
| `npm exec --prefix frontend -- playwright test --config=frontend/playwright.snowflake.config.ts --output=../backend/.tmp/behavior-snowflake-final` | 3 controlled Snowflake browser cases passed. |
| `npm exec --prefix frontend -- playwright test --config=frontend/playwright.narration.config.ts --output=../backend/.tmp/behavior-narration-final` | 1 controlled narration browser case passed. |

The broader run exposed a preexisting Tiger publication race: a committed source
deletion could precede in-memory head removal, and an ingestion pass with no
progress returned pending=true, starving publication in a tight loop. Reconciliation
now returns whether it actually advanced. The deterministic publication-gap
regression and full source-delete/branch/restart suite pass. The first affected
full run was stopped; it is not counted as a pass.

Earlier failing runs also caught/fixed a low-stock redistribution trade fixture,
missing hospital-ledger event key, bypassed stale-proposal invalidation and the
intentionally changed child OpenAPI snapshot. Test-only setup corrections covered
checkpoint revision appends, a valid idempotency key in an Origin negative case,
GPU selection readiness/overlapping SVG hit targets and independent browser
artifact directories. Functional assertions were retained. The primary screenshot
`backend/artifacts/behavior-recovery.png` was visually inspected for separate
Mental/Social/Energy, actual recovery contributions, care status and population
labels. Full logs remain in the ignored backend `.tmp` directory; reproducible
curves and the feature screenshot are committed. Browser setup routes live only in the
test-only application; production exports no setup or arbitrary state mutation
route. Runtime configuration adds no environment variables or dependencies.
