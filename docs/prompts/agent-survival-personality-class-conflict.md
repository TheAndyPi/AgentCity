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
- Mental stability at or below 10 triggers a personality-dependent crisis.
  Behaviors must include withdrawal at home, aggression that can kill another
  citizen, and starting a fire, with real bounded simulation consequences.
- Compassionate/cooperative citizens help unconscious or badly injured people,
  including physically taking them to a functioning hospital.
- Wealth/resource inequality creates class hostility, including wealthier citizens'
  negative attitudes toward poorer citizens, moderated by personality/history.
- Expand combinations of needs, emotions, personality and interactions so behavior
  has understandable causes and consequences beyond repeated generic routines.

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

## 3. Mental crisis behavior

At mental <=10, enter one recorded crisis episode using seeded deterministic
selection weighted by the existing personality traits, current needs, relationship
conflict, perceived threats and recent memories. Publish the chosen mode/reason;
do not roll an unrelated new mode every tick. Use bounded duration, cooldown and
an exit threshold initially mental >=25 for several stable ticks. Recovery may
come from rest, safety, social comfort, food or hospital care. Low Mental alone
does not automatically kill anyone.

Required modes and interactions:

| Mode | Personality/context tendency | Real behavior |
| --- | --- | --- |
| Withdrawal | Lower sociability/risk tolerance, overwhelm or grief | Travel to a known safe home/room, stay there and avoid optional contact; still account for eating/rest and escape from immediate danger. |
| Panic/flight | High fear/stress and low perceived safety | Seek reachable safety, warn known nearby people, reject unnecessary social/work tasks. |
| Distress/support seeking | Higher sociability/trust or existing supportive ties | Approach a known friend/helper and request comfort/care. Accepted support can improve mental state. |
| Aggression | Lower empathy/cooperation, higher risk tolerance and a specific grievance | Approach a perceived nearby target and attempt bounded attacks; actions may injure and eventually kill through health loss. |
| Destructive/fire-setting | Destructive crisis choice, higher risk and low concern for others | Move to a reachable nearby valid target and attempt one bounded ignition action, producing an actual engine fire/hazard if legal. |

Do not map every low-mental citizen to violence. Wealth/class alone does not
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
| Low mental + low empathy/cooperation + grievance | Elevated aggression/destruction weight, bounded by action validation/cooldowns. |
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
| AB-05 | Mental 10 versus 10.1; repeated ticks; recovery/cooldown. | Defined crisis boundary, stable episode and exit hysteresis; no fresh crisis roll/log every tick. |
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

Run focused tests while building, then the full backend/frontend/contract/build
gates and relevant browser suites on the integrated branch. Keep paid providers
out of default tests. A feature is not done if only its prompt, UI badge or random
animation exists. Record exact commands, seeds, rule version, commit and failures.

## Delivery sequence and ownership

Implement in coherent increments: (1) canonical state/contracts/migration and
fatal/faint boundaries; (2) rescue/hospital care; (3) mental/crisis states and legal
aggression/fire; (4) wealth perception/class behavior and extra combinations;
(5) UI/analytics, cross-feature save/replay/security tests and balancing. Each
increment must be functional and tested; do not claim the later ones from stubs.

Own engine/state/Game Master/perception/navigation/building-care changes, the
coordinated contract migration and behavioral tests. Coordinate shared UI and
provider context changes with the live-voices task. Preserve existing narration
authorization/unique voice identities and previously fixed consent/safety rules.
Push the focused branch, write `docs/release/agent-behavior-handoff.md` covering
rules, formulas, limits, migrations and acceptance results, and append the dev log.
