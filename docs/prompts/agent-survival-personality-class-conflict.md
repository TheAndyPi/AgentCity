# Task: survival, crises, rescue, personality interactions and class conflict

Implement these mechanics in AgentCity, with executable functional tests. Read
applicable instructions, `docs/dev-log.md`, the current engine/Game Master,
navigation/building visits, perception, state, contracts, metrics and UI. Start
from latest fetched dev on `codex/agent-survival-and-class-conflict`; inspect an
existing branch before reuse. Preserve the current frontend design and working
Gemini, Tiger, Snowflake, narration, history, security and scenario behavior.

## Confirmed user requirements

- **Health <= 0 OR fullness <= 0 independently causes death.** The user explicitly
  confirmed either threshold is fatal; do not require both or substitute a long
  starvation grace period. Thresholds use canonical numeric state, not rounded UI.
- Energy <= 0 causes fainting/unconsciousness for a living citizen.
- Mental stability <=10 **OR stress >=80** independently triggers the same
  personality-dependent crisis system. Use raw percentages and configurable,
  versioned thresholds, initially 10 and 80 respectively.
  Behaviors must include withdrawal at home, aggression that can kill another
  citizen, and starting a fire, with real bounded simulation consequences.
- Compassionate/cooperative citizens help unconscious or badly injured people,
  including physically taking them to a functioning hospital.
- Wealth/resource inequality creates class hostility, including wealthier citizens'
  negative attitudes toward poorer citizens, moderated by personality/history.
- Expand combinations of needs, emotions, personality and interactions so behavior
  has understandable causes and consequences beyond repeated generic routines.
- Happiness, Safety, Trust, Resources and Stress must each affect Mental, Social
  fulfillment and/or Energy through the explicit intuitive interaction model
  below. These cannot remain unrelated cosmetic dashboard values.

## 1. Canonical meters and state model

Current HUD values are Health = `needs.health`, Fullness = `100-needs.hunger`,
Energy = `100-needs.fatigue`, and Social = `100-needs.social`. **There is currently
no independent Mental meter.** Keep those inverse relationships explicit; do not
make hunger 0 mean starvation or fatigue 0 mean exhaustion. Social is not Mental.

Add a persisted, bounded mental-stability value and a matching separate UI meter.
Use versioned documented rules for starting values, stress/need/pain/isolation/
grief/conflict losses and rest/support/treatment gains. Avoid double-counting one
event through multiple callbacks. Existing profiles migrate deterministically to
documented defaults; do not infer traits or wealth from a citizen's name.

Stress already exists as `summary.metrics.stress`, but the current application
has no independent Mental state for stress to reduce. Implement that relationship:
sustained stress contributes to mental-stability loss under an explicit bounded
per-tick rule, while rest/support/treatment can improve it. Mental is not simply
`100-stress`; retain independent values and independent crisis triggers. Do not
wait for high stress to drain Mental to 10 before allowing a stress-triggered crisis.

Persist life state (`alive`, `unconscious`, `dead`), transition cause/evidence and
tick, crisis mode/episode/cooldown, and rescue/treatment state as needed. Treat
`summary.active=false` as dead for compatibility; unconscious people remain alive
and observable but cannot choose or perform ordinary actions. Separate the living
population predicate from the conscious-actor predicate. Consciousness and crisis
are different axes: being unconscious is not itself a mental crisis.

Health/fullness death takes precedence over fainting or a crisis. Check fatal
conditions before actor selection and after each action, need change, damage and
environmental effect that can cross a threshold. An agent killed earlier in a
tick cannot act later in its ordering. A corpse cannot be revived by an ordinary
help/treatment action. Record simultaneous causes consistently and one death event
per citizen, not a death on every subsequent tick.

Use raw values for comparisons: 0.1 is still alive/awake if other requirements
allow; 0 or a clamped negative value crosses the threshold. Define precisely
whether consumption/rest happens before normal end-of-tick decay, and test it.

### 1A. Intuitive interactions between metrics and needs

Use per-citizen values, not city-wide averages. Higher Mental, Social fulfillment
and Energy mean better condition. Persist Social and Energy through the existing
inverse needs (`social = 100-fulfillment`, `fatigue = 100-energy`) rather than
adding conflicting duplicate storage. Mental remains an independent value.

| Input | Mental stability | Social fulfillment/behavior | Energy/fatigue |
| --- | --- | --- | --- |
| High/low Happiness | Positive mood supports stability; sustained unhappiness erodes it. | Good mood improves accepted positive contact; unhappiness adds isolation pressure, moderated by sociability. | Good mood improves restorative rest; sustained low mood adds modest fatigue, without creating stamina during work. |
| High/low Safety | Feeling safe supports recovery; danger/injury undermines stability. | Safe encounters are more restorative; danger increases reassurance/help seeking or cautious withdrawal. | Safe rest is more effective; danger/hypervigilance causes extra fatigue. |
| High/low Trust | Reliable known relationships support stability; distrust adds insecurity. | Accepted contact with a trusted partner is more restorative; distrust makes bonding less effective and more selective. | Support improves rest slightly; persistent distrust/vigilance adds modest fatigue. |
| Adequate/scarce Resources | Basic security reduces scarcity pressure; deprivation drains stability. | Adequacy improves meaningful shared activity; scarcity can cause withdrawal, requests for help or solidarity according to traits. | Actual nutrition and safe rest support recovery; scarcity adds fatigue. Owning supplies never substitutes for eating. |
| High/low Stress | Sustained high stress drains Mental; low stress permits recovery. Stress >=80 still triggers a crisis directly. | Stress adds social strain and reduces positive interaction benefit; some profiles seek support while others withdraw. | Stress increases fatigue and reduces rest quality; calming lowers this penalty. |

Preserve direction and causality: being rich/happy alone does not satisfy social
needs or generate energy while moving/working. Social gains require actual
accepted interaction/support. Nutrition requires an actual conserved food/water
transfer or consumption. Resource fullness, wealth and the capped Resources meter
are distinct; 100% supplies with no food must not bypass hunger/starvation.

#### Initial versioned gameplay defaults

Provide one deterministic coupling function and a documented tuning table. Use
these initial defaults unless measured balance tests justify a recorded change;
these are gameplay coefficients. Every coefficient and cap must be configuration/
rule-version data, not scattered callbacks or model-generated numbers.

All metrics use 0..100. Define:

```text
bad(x)  = clamp((40 - x) / 40, 0, 1)
good(x) = clamp((x - 60) / 40, 0, 1)
strain  = clamp((Stress - 40) / 60, 0, 1)
dt      = tick_seconds / 10
```

The 40..60 neutral band prevents tiny metric jitter producing alternating
bonuses/penalties. Here H/S/T/R are Happiness/Safety/Trust/Resources respectively.

```text
Mental background delta per 10 simulated seconds = clamp(
    +0.12*good(H) +0.10*good(S) +0.08*good(T) +0.06*good(R)
    -0.30*bad(H)  -0.35*bad(S)  -0.20*bad(T)  -0.30*bad(R)
    -0.55*strain,
    -1.50, +0.30)

Additional Social-fulfillment loss per 10 simulated seconds = min(0.50,
    0.15*bad(H) +0.10*bad(S) +0.15*bad(T) +0.10*bad(R) +0.20*strain)

Additional Energy loss per 10 simulated seconds = min(0.60,
    0.12*bad(H) +0.20*bad(S) +0.10*bad(T) +0.18*bad(R) +0.30*strain)
```

Multiply these rates by dt and apply once per physical tick, alongside the
existing baseline need decay, then clamp canonical values to 0..100 and evaluate
fatal/faint/crisis transitions. This block supplies the sustained-stress Mental
effect described above; do not add a second independent copy of that drain.

For accepted friendly conversation, comfort or mutually agreed shared activity,
scale the existing Social-restoration effect once:

```text
Social restoration multiplier = clamp(
    1 +0.20*good(H) +0.20*good(S) +0.25*good(partner_trust)
      +0.10*good(R) -0.25*strain -0.20*bad(partner_trust),
    0.50, 1.60)
```

Use the actor's actual directed trust toward that observed partner, not a
city-average trust value. No known tie uses the documented neutral/default
baseline, not invented intimacy. Hostile/coerced contact does not receive this
friendly bonus. Conserve existing acceptance/consent rules.

For real rest/sleep/hospital recovery, scale the documented base Energy recovery
once, subject to actual living/consciousness/care state:

```text
Energy recovery multiplier = clamp(
    1 +0.10*good(H) +0.20*good(S) +0.05*good(T) +0.05*good(R)
      -0.25*strain -0.20*bad(S) -0.15*bad(R),
    0.50, 1.40)
```

Apply the Resources recovery bonus only when actual basic needs are met; it
cannot turn uneaten inventory into nutrition. Positive mood/security can make
rest better, but this multiplier produces no recovery during ordinary movement/
work. Fainted recovery follows the separate passive/care rules, not an illicit
autonomous Rest action. Critical survival rules always take precedence.

#### Feedback control, explanations and balancing

- Refresh derived input metrics from canonical state and freeze one input snapshot
  for the coupling phase. Apply all outputs simultaneously once per committed
  physical tick. Rendering, polling, opening a drawer, manual saves and repeated
  `update_metrics` calls must not advance this model.
- Current Resources derives from inventory, Safety from hazard/health, and Trust
  from directed ties. Do not write these derived numbers to make the tests pass;
  set their underlying state. Do not feed newly computed Mental/Social/Energy back
  into another copy of this phase in the same tick.
- Keep acute action/event effects distinct from background pressure. One event
  may have an immediate recorded impact and subsequent per-time pressure, but
  cannot be charged twice through duplicate callbacks. Safety already includes
  health/hazards: account for that overlap before adding extra injury/fear terms.
- Personality modifies behavioral response and selected effect weights within
  documented bounds; it does not reverse stress into a mental benefit, make low
  fullness safe, or create perpetual stamina. Social contact with trusted people
  can reduce stress and restore Mental, but no recursively repeated same-tick
  trust/happiness/need bonus is allowed.
- Expose concise reasons such as "unsafe surroundings: -0.2 Energy" or
  "trusted conversation: +6 Social" using actual final contributions after caps.
  Preserve cause/tick/evidence and distinguish base decay, activity and metric
  pressure. Do not attribute a whole combined change to one convenient metric.
- Test sustained neutral, deprived, stressed and recovering worlds over hundreds
  of ticks. Ordinary supported rest/eating/social routines must be capable of
  recovery; monotonic deterioration is acceptable under sustained deprivation,
  but an uncontrolled feedback loop is not. Record seed, rate table and actual
  curves; revise weights transparently if balancing changes these defaults.

## 2. Death, fainting and recovery

On death, invalidate pending intentions/tasks and future autonomous speech,
release routes/reservations/beds/interaction participation, resolve any rescue
links, and preserve history, profile, memories, possessions and voice identity.
Remove the citizen from living decision/need-update schedules, not from the
historical dataset. Do not silently erase inventories; retain or explicitly
transfer possessions under conserved, logged estate/drop rules. Render a clear
dead state/marker using the existing visual language and show death tick/cause.

An unconscious citizen stops self-directed movement, work, eating and conversation.
Their real position remains visible for rescuers. Implement deterministic passive
energy recovery, with a documented wake threshold initially 20 energy; a hospital
bed can improve the recovery rate. Fainting never teleports someone to safety,
heals fatal health or suppresses hunger/hazard damage. Prevent repeated faint/wake
events around zero with state transitions and hysteresis.

Unconscious people may still die from injury/starvation. If a helper dies/faints
while carrying someone, detach them safely at the current real location and make
the patient eligible for another rescue. Do not create duplicate occupants or
leave an invisible patient following a removed carrier.

## 3. Mental/stress crisis behavior

At mental <=10 **or stress >=80**, enter one recorded crisis episode using seeded deterministic
selection weighted by the existing personality traits, current needs, relationship
conflict, perceived threats and recent memories. Publish the chosen mode/reason;
do not roll an unrelated new mode every tick. Use bounded duration, cooldown and
exit hysteresis: initially require **mental >=25 AND stress <=60 for three
consecutive ticks** before recovery, with those parameters versioned/configurable.
Recovery may come from rest, safety, social comfort, food or hospital care. Low
Mental or high stress alone does not automatically kill anyone.

Both triggers enter the same personality-weighted modes below, including
withdrawal, panic, support seeking, aggression and fire-setting. If both thresholds
are crossed together, create one episode, not two actions, doubled damage or two
mode rolls. Record the cause as low mental, high stress, or both and preserve the
supporting measurements/evidence. A second trigger crossing during an existing
episode adds cause evidence without restarting it. Rising Mental cannot clear a
crisis while stress remains high, nor can falling stress clear persistently low
Mental. Keep death/unconsciousness precedence and the existing action safeguards.

Required modes and interactions:

| Mode | Personality/context tendency | Real behavior |
| --- | --- | --- |
| Withdrawal | Lower sociability/risk tolerance, overwhelm or grief | Travel to a known safe home/room, stay there and avoid optional contact; still account for eating/rest and escape from immediate danger. |
| Panic/flight | High fear/stress and low perceived safety | Seek reachable safety, warn known nearby people, reject unnecessary social/work tasks. |
| Distress/support seeking | Higher sociability/trust or existing supportive ties | Approach a known friend/helper and request comfort/care. Accepted support can improve mental state. |
| Aggression | Lower empathy/cooperation, higher risk tolerance and a specific grievance | Approach a perceived nearby target and attempt bounded attacks; actions may injure and eventually kill through health loss. |
| Destructive/fire-setting | Destructive crisis choice, higher risk and low concern for others | Move to a reachable nearby valid target and attempt one bounded ignition action, producing an actual engine fire/hazard if legal. |

Do not map every low-mental or highly stressed citizen to violence. Wealth/class alone does not
execute an attack; actions still require an eligible mode, motive and legal target.
Personality weights, probabilities, damage, durations and rates must be written
as versioned gameplay rules, not unexplained magic numbers or model discretion.

All new actions go through Game Master legality and produce auditable decisions.
Attack attempts require consciousness, reachable/perceived targets, interaction
range and a per-actor action/cooldown budget; no remote instant kills. Rejected
attempts have no physical side effects. Apply damage exactly once, handle zero
health immediately and record actor/victim/witness evidence.

Fire-setting is an engine action, not a visual-only scenario prop or an arbitrary
user construction request. Require local proximity and explicit flammability/
target rules. Bound simultaneous fires, affected area, severity, spread and
lifetime; integrate real exposure, evacuation, suppression and resolution with
existing hazards. Never burn the entire map from one unchecked random choice.

## 4. Compassion, cooperative rescues and hospital care

Build a stateful rescue flow: notice -> assess -> claim/coordinate -> approach ->
stabilize when possible -> escort/carry -> admit -> treat -> release/recover.

Only use public perception or remembered/heard requests. Helpers must not locate
remote unconscious victims or know others' private inventories/memories by reading
global state. Higher empathy increases willingness to help; higher cooperation
increases coordination and willingness to share effort/supplies. Relationship
affection/trust, familiarity and urgency should also matter.

Keep the existing self-safety priority: a threatened helper first seeks safety.
Use documented eligibility thresholds for the helper's own health, energy,
fullness, mobility and mental stability. Risk tolerance can affect choices among
safe reachable routes; it must not bypass existing hazard legality.

- Conscious injured patients can accept an escort and walk at a condition-limited
  speed. Unconscious patients can be carried; do not require them to make an
  autonomous consent/action while unconscious.
- One patient has at most one active rescue/transport claim; one carrier has at
  most one patient. Cooperative helpers can form an explicit team when needed.
  Test race/order handling so two helpers cannot duplicate a patient or rewards.
- Travel uses existing routing, entrances, speed limits and hazard checks. A
  carried patient follows the carrier's actual position with an explicit carried
  collision exception; neither actor crosses blocked cells or teleports.
- Admit only at a functioning reachable hospital with available/reserved capacity.
  Handle full/closed/unreachable facilities with waiting, another known facility
  or safe nearby first aid. No fabricated success when no route/bed exists.
- First aid/treatment consumes declared actual supplies; food/water used in care
  also comes from a real stock. Hospital inventories must be funded/transferred
  explicitly and included in conservation accounting. Define treatment/recovery
  per tick, admission/release criteria and what happens when supplies run out.
- Fainting, death, cancellation, changed hazards and hospital closure release or
  transfer claims/beds once. Death in a bed releases capacity without erasing
  the recorded death or duplicating possessions.

Witnesses can warn, call for help, comfort a survivor or grieve according to
relationships and traits. Knowledge and memories spread through actual observation
or communication; do not announce every death/incident into every private mind.

## 5. Resource classes and class conflict

Use real conserved holdings to define wealth. The current resources metric is
capped and cannot distinguish someone with 12 units from someone with 100 units.
Create a documented raw wealth measure, initially food + water + 2*supplies,
and versioned configurable poor/middle/rich bands. These are gameplay defaults,
not a new external currency system. Demonstrate an uneven starting distribution
by redistributing a fixed initial resource pool, not by inventing unrecorded stock.

Wealthier citizens acquire a negative class-affinity bias toward poorer citizens.
Lower empathy/cooperation amplify contempt, exclusion, refusal to share and
distrust. Compassion, supportive history and strong ties can overcome the bias,
so a rich compassionate character can still rescue a poor friend. Poor citizens
may resent observed hoarding/unfair access and form mutual-aid groups; do not
make all poor citizens violent or all cross-class interactions identical.

Separate objective owner-visible wealth from an agent's **perceived** class of
someone else. A citizen knows their own holdings; others' class must be learned
through explicit observable public signals or communication. Do not leak raw
private inventories or silently grant omniscience. A remote wealth change must
not update someone's beliefs before observation/hearing.

Class affinity influences encounter preferences, dialogue, directed trust/respect/
affection, aid/trade willingness, grievances and coalition choice. Cap changes;
apply them on meaningful encounters/evidence/cadence, not one penalty per frame.
Use hysteresis on wealth bands to avoid class flapping after consuming one unit.
Record discrimination, solidarity, refusal, aid and conflict as evidence-backed
events. If theft is introduced, it needs a local valid target, bounded conserved
transfer, consequences and its own Game Master legality, not a hidden inventory
edit. Citizens cannot silently change global laws or public resource ownership.

## 6. Additional personality/need combinations to implement

| Combination | Expected behavior and measurable consequence |
| --- | --- |
| High empathy + injured/unconscious neighbor | First aid and rescue, constrained by own condition and observed access. |
| High cooperation + multiple helpers | Shared rescue roles/claims, no duplicate carrying, treatment or cooperation rewards. |
| High cooperation + local scarcity | Offer conserved food/supplies, accept fair trades and form mutual-aid ties. |
| High sociability + unmet social need/low mental | Seek available friends, converse or request comfort; successful contact improves the relevant needs. |
| Low sociability + distress | Prefer quiet rest/withdrawal over constant conversation; support is possible through trusted ties. |
| Low risk tolerance + visible fire | Warn and evacuate early along a legal safe route. |
| High curiosity + unfamiliar event | Investigate/ask questions when safe; gain observed knowledge, without overriding evacuation. |
| Low trust + uncertain warning | Seek corroboration or ask a trusted contact; preserve uncertainty and subjective trust. |
| Friend/family learns of death | Evidence-backed grief and mental loss; supportive contact/rest can improve recovery. |
| Low mental OR high stress + low empathy/cooperation + grievance | Elevated aggression/destruction weight, bounded by action validation/cooldowns. |
| Wealth gap + low empathy/cooperation | Cross-class avoidance/refusal and negative directed ties, with capped evidence-backed changes. |
| Wealth + high empathy/cooperation | Sharing, rescue and reconciliation can overcome class resentment. |
| Poor + high cooperation + shared unfair treatment | Solidarity and mutual aid; conflict escalation needs additional motives/conditions. |
| Energy nearly depleted + work goal | Rest before collapse when personality/rules permit; goal pursuit never bypasses unconscious/dead state. |

All of these need explainable choices, observable effects and testable outcomes.
Use existing traits where possible. If adding a trait such as resilience or
impulsivity, document deterministic migration/defaults and update custom profiles,
provider context, UI and versioned contracts together. Do not derive traits from
occupation/name or let Gemini invent engine powers.

## 7. Contracts, persistence, analytics and UI integration

This work introduces new state/actions and may require a coordinated contract
version. Design that migration explicitly. **Do not edit/regenerate frozen v1
snapshots, put new enum values into v1 responses, or weaken strict client parsing.**
Use a documented versioned API/schema for new core semantics and/or a genuinely
compatible extension; keep existing saved worlds readable and old checkpoints
immutable. If adding v2 paths/streams, apply auth, CSRF, origin, ownership and
stream revocation there too; the current guard is keyed to the v1 prefix.

Persist RNG state, episode/rescue/life transitions, claims, possessions and wealth
beliefs. Branches copy independent state; replay reads stored outcomes without
new random decisions or provider calls. Migration must not retroactively rewrite
death into old history or silently kill legacy citizens at startup. Apply new
rules at a documented live rule-version boundary.

Expose life/crisis/care state, mental meter, cause/rationale and class/relationship
effects in the current UI style. Distinguish fainted, hospitalized, withdrawn and
dead citizens; disable impossible commands. Keep captions/audio focus stable and
preserve voices for historical replay. Coordinate LifeHUD/Simulation wiring with
`docs/prompts/live-conversation-voices.md`; do not overwrite its audio coordinator.

Update analytics/export/read models for deaths by cause, living/unconscious counts,
rescues, admissions, crisis episodes, ignitions and class-based aid/conflict.
Define all denominators: unconscious people count as living, dead people never
count as successfully evacuated, and an all-dead city is not a 100% survival
success. Handle zero living population without divide-by-zero/NaN or repeatedly
creating empty ticks. Label population-composition changes in mean metrics.
Tiger/Snowflake projections must preserve version, tick/revision and evidence;
do not fabricate supported analytics when the adapter cannot read the new schema.

## Required automated functional tests

Use small deterministic worlds and adversarial orders/boundaries; fixtures alone
are not proof of a working flow. Add actual engine, Game Master, persistence/API
and browser tests with expected state/decisions/counters, not only HTTP 200.

| ID | Case | Required acceptance |
| --- | --- | --- |
| AB-01 | Health 0 while fullness positive; fullness 0 while health positive; 0.1 boundaries; both zero. | Either independent threshold kills exactly once with correct cause/tick; nonzero values are not rounded into death. |
| AB-02 | A citizen is killed/starves before their turn, during damage or end-of-tick decay. | No later action/movement/speech/recovery; pending proposals invalidated; possessions and reservations conserved. |
| AB-03 | Energy 0 with positive health/fullness, then passive/hospital recovery. | Unconscious, not dead; no ordinary intents; wake only at documented threshold; no repeated transition events. |
| AB-04 | Unconscious person remains hungry/in a hazard; carrier faints/dies. | Death still possible; patient placed at actual position, no teleport/duplicate carrier/bed. |
| AB-05 | Mental 10 versus 10.1 with low stress; stress 80 versus 79.9 with healthy Mental. | Either independent threshold enters the same crisis system; nonqualifying raw values do not; stable episode and exit hysteresis. |
| AB-06 | Identical crisis setup with contrasting personalities and fixed seeds. | Supported withdrawal/support/panic/aggression/fire modes have reproducible rule-based differences and recorded motives. |
| AB-07 | Legal attack versus remote/dead/unconscious actor or out-of-range target. | Bounded once-per-action damage, immediate fatal transition when applicable; rejected attempts have no effects. |
| AB-08 | Legal ignition, invalid/remote ignition, repeated requests, cap/extinction. | Actual bounded fire exposure and evacuation; no duplicate hazards, arbitrary destruction or visual-only success. |
| AB-09 | Compassionate helper transports unconscious/injured victim to hospital. | Physical legal route/entrance, one claim, actual admission/treatment and conserved supplies; no instant teleport/heal. |
| AB-10 | Two helpers, full/closed hospital, blocked route, no supplies, unsafe helper. | Atomic claims/capacity, safe fallback/cancellation, no duplicated reward or bypass of self-safety. |
| AB-11 | Comfort/grief/social need and contrastive personality fixtures. | Knowledge-bound evidence, deterministic need/mental changes and valid recovery; no private-memory omniscience. |
| AB-12 | Rich/poor encounters, benevolent wealthy helper, class band crossings. | Negative class bias exists, personality/history can overcome it, effects bounded/hysteretic and not repeated per frame. |
| AB-13 | Change remote private wealth, then observe a public signal; share/steal if supported. | No premature class knowledge or raw inventory leak; explicit conserved transfers and correct evidence. |
| AB-14 | Save/restart/branch/replay during crisis, carrying and hospital care. | Exact life/care/RNG/voice provenance, independent branches and no repeated death/damage/provider work. |
| AB-15 | Legacy store and old v1 clients; new version security/validation. | Defined migration without historical mutation, strict schemas, denied unowned/unauthenticated commands and preserved v1 hashes. |
| AB-16 | All citizens dead, several unconscious, source deletion and analytics export. | Correct living/survival denominators, finite valid metrics/counters, restorable branch/history and truthful adapter support. |
| AB-17 | Real browser simulation: faint -> rescue -> hospital -> recovery; fatal threshold; two crisis modes; class encounter. | Correct visible states/meters, movements, explanations, logs and disabled impossible actions in dev's existing design. |
| AB-18 | Both crisis triggers together; second trigger crosses during an episode; Mental recovers while stress stays high and vice versa. | One episode/mode roll with correct cause evidence, no doubled effects; recovery only after both exit conditions hold for three ticks. |
| AB-19 | Sustained stress, rest/support/treatment, save/restart and branch. | Exact documented bounded stress-to-Mental changes, no accidental inverse-meter coupling, independent onset at stress 80 and reproducible persisted recovery/cooldown. |
| AB-20 | Vary each of H/S/T/R/Stress independently in canonical-consistent seeded fixtures; hold other inputs fixed. | Exact configured Mental/Social/Energy contributions and intuitive monotonic direction; neutral-band values do not generate spurious bonuses/penalties. |
| AB-21 | Alone versus accepted trusted/hostile contact; working versus resting; supplies-rich but unfed citizen. | No passive Social satisfaction or free working Energy, correct partner-specific trust/rest multipliers, no nutrition fabrication or starvation bypass. |
| AB-22 | Repeated frames/saves/metric refreshes; a different tick duration; acute event plus background stress; restart/branch. | Exactly one time-scaled coupling update per physical tick, no duplicated cause charges, deterministic persisted outcomes and unchanged state on reads. |
| AB-23 | Long neutral/deprived/stressed/recovery runs, then real UI inspection. | Bounded curves, successful supported recovery, maintained crisis/death boundaries and displayed reasons/numbers matching actual clamped contributions. |

Run focused tests while building, then the full backend/frontend/contract/build
gates and relevant browser suites on the integrated branch. Keep paid providers
out of default tests. A feature is not done if only its prompt, UI badge or random
animation exists. Record exact commands, seeds, rule version, commit and failures.

## Delivery sequence and ownership

Implement in coherent increments: (1) canonical state/contracts/migration and
fatal/faint boundaries plus the bounded metric/need interaction model; (2) rescue/hospital care; (3) mental/crisis states and legal
aggression/fire; (4) wealth perception/class behavior and extra combinations;
(5) UI/analytics, cross-feature save/replay/security tests and balancing. Each
increment must be functional and tested; do not claim the later ones from stubs.

Own engine/state/Game Master/perception/navigation/building-care changes, the
coordinated contract migration and behavioral tests. Coordinate shared UI and
provider context changes with the live-voices task. Preserve existing narration
authorization/unique voice identities and previously fixed consent/safety rules.
Push the focused branch, write `docs/release/agent-behavior-handoff.md` covering
rules, formulas, limits, migrations and acceptance results, and append the dev log.
