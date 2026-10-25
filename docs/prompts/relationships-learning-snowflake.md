# Task: relationships, learned outcomes and Snowflake social analytics

Implement this assignment in AgentCity with executable functional tests. Read
applicable instructions, `docs/dev-log.md`, the current relationship/memory engine,
Game Master, rule/Gemini decision paths, persistence, exports, Snowflake adapter
and frontend before editing. Start from latest fetched dev on
`codex/relationships-learning-analytics`; inspect an existing branch before reuse.
Preserve dev's frontend design and working security, scenarios, movement,
Tiger Data, Snowflake comparisons and ElevenLabs narration.

This extends [survival, personality and class conflict](agent-survival-personality-class-conflict.md)
and [live conversation voices](live-conversation-voices.md). Coordinate their new
state/contracts instead of implementing competing death, crisis, hospital or audio
systems. Their features are dependencies to integrate and test, not evidence that
those features have already shipped.

## Required behavior

- Relationships progress **strangers -> acquaintances -> friends -> best friends**.
- An optional reciprocal branch progresses **best friends -> lovers -> married**.
  Friendship can remain platonic indefinitely. Romance is not an inevitable reward.
- Disagreements can progress **arguing -> enemies**; recovery and reconciliation
  must also be possible through changed behavior and evidence.
- Outcomes from survival, personalities, rescue, crises, hazards and class conflict
  create persistent lessons that change later choices, not just narrative memories.
- Snowflake tracks relationship transitions, learned outcomes and subsequent
  applications of learning, with reproducible counts and inspectable evidence.

## 1. Reuse the existing model; define a versioned extension

The current `RelationshipKind` is `family`, `friend`, `acquaintance`, `rival`,
`romantic` or `stranger`. Relationships are directed and contain trust, affection,
respect, familiarity, conflict, shared history and evidence. `social_delta` already
deduplicates directed changes by decision evidence. Memories are persisted and
retrieved using importance, recency and relevance. These are useful foundations;
they do not implement the complete progression or durable behavioral learning.

Separate three axes instead of replacing marriage with an argument:

| Axis | State | Meaning |
| --- | --- | --- |
| Friendship | stranger, acquaintance, friend, best_friend | Shared stage, gated by both citizens' directed scores/history. |
| Romance/commitment | none, lovers, married; explicit ended/widowed history | Mutual accepted commitment, independent of temporary conflict. |
| Conflict | calm, arguing, enemies | Current dispute/hostility, including which party initiated it and directed grievances. |

Keep directed feelings asymmetric: A trusting B does not make B trust A. Store a
canonical unordered pair ID for mutual status and retain directed IDs for feelings
and grievances. A one-sided threat can create a conflict episode without implying
both parties feel equal hatred. Family/kinship is a separate preserved relation,
not a lower friendship stage. Unknown pairs are implicitly strangers; do not
allocate an all-pairs graph for every city.

Persist stage start/transition ticks, score deltas, qualifying encounter IDs,
proposal/acceptance/expiry records, cooldowns, dispute IDs, reconciliation and
evidence. Separate perceived status from historical facts when appropriate.
Death preserves relationship history; a surviving spouse becomes widowed, with
knowledge-bound grief. Historical marriage must not disappear on death/separation.

Do not insert `best_friend`, `lovers`, `married`, `arguing` or `enemies` into frozen
v1 enums/responses. Specify a coordinated versioned state/API extension, strict
frontend parsing and documented legacy projection. Retain v1 hashes and validators.
Map legacy `romantic` to lovers only at an explicit migration boundary, never to
married; do not manufacture proposal history. Preserve legacy ties and provenance
without treating migration as a new interaction or learning/statistics event.

## 2. Friendship progression, conflict and consent

Use deterministic, configurable, versioned thresholds. Suggested initial gameplay
defaults below are tuning values, not claims about human psychology. Gate on the
minimum of the two directed values; one generous citizen cannot promote a pair.

| Promotion | Initial eligibility, in addition to the previous stage |
| --- | --- |
| Stranger -> acquaintance | At least one completed reciprocal encounter; both familiarity >=10. Seeing a remote person or receiving an unanswered invitation is insufficient. |
| Acquaintance -> friend | Both familiarity >=35, trust >=55, affection >=50, respect >=40, conflict <=30; at least 3 positive encounters spanning 30 physical ticks. |
| Friend -> best friend | Both familiarity >=65, trust >=75, affection >=70, respect >=60, conflict <=15; at least 6 positive encounters since friendship spanning 90 physical ticks. |

A qualifying encounter is a completed accepted conversation or a completed
observable action such as sharing, rescue or comfort with an actual recipient
response. Credit one encounter per pair/episode, not each dialogue turn, repeated
poll, warning, apology message or provider retry. Count positive encounters at
least 5 physical ticks apart. Require at least 10 ticks between promotions, never
skip stages, and never promote during arguing/enemy episodes. Existing seeded
ties may start at a declared stage; do not invent qualifying events for them.

Personality changes approach/response frequency and bounded score deltas. High
sociability seeks contact; empathy/cooperation favor help and trust; low trust may
need reliable repeated evidence. Respect introverts and refusals: waiting beside
someone cannot force friendship. Maintain a documented score/event rule table,
cause IDs and per-episode caps instead of letting Gemini set arbitrary scores.

Define downgrade hysteresis independently of promotion thresholds. Initial
defaults: best friends fall to friends if either trust <60, affection <55 or
conflict >35 for 3 consecutive physical ticks; friends fall to acquaintances if
either trust <40, affection <30 or conflict >60 for 3 ticks. A newly downgraded
pair must requalify with new positive evidence and a 10-tick cooldown. Severe
betrayal/violence can trigger a separately logged immediate break. Mere lack of
contact slowly changes familiarity under a documented rule, not instant hatred.

Romance is optional and governed by an explicit engine-validated proposal flow:

- Initially require best friendship, both trust >=75/affection >=80, no active
  argument/enemy state and mutually compatible declared preferences. Never infer
  attraction/preferences from names, occupation, wealth or gender stereotypes.
  Add explicit world/profile romance settings with documented adult defaults and
  deterministic migration; an unspecified preference cannot be invented by an LLM.
- Both participants must be adults (age >=18), unrelated by known family/kinship,
  alive, conscious and able to choose; no proposal/acceptance during an acute
  crisis or treatment incapacity. Rescue, gifts, class status and dependency do
  not create consent. Do not turn a refusal into an automatic hostility penalty.
- The initiator proposes; the other independently accepts/declines within a
  bounded expiry. The initiator cannot supply both acceptances. Consent may be
  withdrawn before commitment; replayed, stale or changed-state proposals fail
  atomically. Revalidate eligibility at commitment. No romance involving minors.
- Marriage requires a separate mutual proposal after at least 100 physical ticks
  as lovers, both trust >=80/affection >=85, no unresolved conflict and a minimum
  20-tick proposal cooldown after refusal/expiry. Start with one active partner
  per citizen; simultaneous proposals cannot produce multiple commitments.
- Persist separation/breakup, widowhood and reconciliation history. Either person
  can leave; marriage is not permanent consent or immunity from protective escape.
  Keep this non-explicit social simulation compatible with existing dialogue/audio.

Arguing starts from a validated disagreement, refusal with an independent dispute,
resource conflict, insult, perceived betrayal or harmful action; low scores alone
must not spawn an argument every tick. Record an episode, topics, initiator,
witness knowledge and bounded effects. Initial enemy escalation requires conflict
>=75 and trust <=25 in at least one direction plus 3 distinct harmful episodes
over at least 20 ticks. A deliberate serious attack may use a documented immediate
escalation exception. Distinguish an aggressor from a victim; protection/self-defense
is not equivalent evidence of malicious betrayal.

Calm an argument through accepted repair or 10 ticks without renewed hostilities;
unresolved grievances remain. Leaving enemies requires 3 distinct accepted repair
episodes spanning 30 ticks, both conflict <40 and trust >35, and no active threat.
Return to calm acquaintance status, not instantly to best friends or lovers.
Unended marriage remains recorded, but romantic activity stays paused pending
separate mutual reconciliation. Restoration never overrides either party's refusal.

## 3. Outcomes must produce usable, bounded learning

Add a structured persisted lesson alongside the existing memory text. Each lesson
contains an ID, learner, topic/target/context, supporting and contradicting source
IDs, observed/heard origin, outcome tick/revision, confidence, before/after learned
parameter, last applied tick and rule version. A lesson must identify a concrete
behavioral change, such as seeking rest earlier, choosing a known hospital,
checking a warning, avoiding a particular aggressor or preferring a proven helper.

| Experienced or credibly learned outcome | Required possible learning and later observable behavior |
| --- | --- |
| Survived fainting/exhaustion or repeated near-collapse | Raise a bounded personal rest trigger; choose a reachable rest opportunity earlier under similar conditions. |
| Survived hunger/shortage; received or was denied aid | Adjust a bounded food/water reserve goal, remember actual sources/helpers and plan earlier; no invented supplies. |
| Rescued/carried/treated successfully | Remember the helper and discovered hospital route; increase target-specific trust and seek/request suitable help earlier. |
| Failed rescue/full hospital/unsafe route | Learn the observed constraint, seek a verified alternative and recheck stale availability; do not permanently blacklist a temporarily full hospital. |
| Helped someone and observed recovery | Increase bounded confidence in effective cooperation/support; repeat the useful action when safe and feasible. |
| Accurate warning, false rumor or broken promise | Calibrate source-specific credibility, retain uncertainty and verify future messages appropriately. |
| Assault, betrayal, theft if supported, fire or witnessed violence | Learn target/location-specific caution, safe distance and escape/help options; no global mind reading or inevitable revenge. |
| Mental crisis/high stress and successful rest/comfort/treatment | Learn a bounded earlier coping/help-seeking trigger; record what actually helped without curing every future crisis. |
| Death of a known close person and subsequent support | Persist knowledge-bound grief and helpful coping/support ties; only living survivors learn after the death. |
| Repeated successful conversations/shared tasks or an argument repaired | Learn contact preferences, trustworthy partners and effective repair; adjust future choices and relationship evidence. |
| Cross-class generosity, abandonment or unfair treatment | Revise beliefs about the actual person first; bounded corroborated group generalization can soften or reinforce class bias. |

Dead agents cannot learn, choose, speak or recover. An unconscious agent cannot
know unseen rescue details until awakening and perceiving or being credibly told
them. Heard reports have lower confidence than direct experience. An outcome is
not automatically public: witnesses need perception/hearing/communication evidence.
Do not blame a helper for a failed rescue caused by capacity or external hazards.

Implement a versioned numeric update rule with explicit confidence, caps, decay,
contradiction and context applicability. Keep stable personality traits separate
from bounded learned preferences. Learning cannot remove death/faint/crisis
thresholds, consent, self-safety, conservation, legal action checks or physical
navigation. High resources do not prevent starvation without food; confidence is
not perfect foresight. Avoid feedback loops that repeatedly reward one rescue or
turn a single poor/rich encounter into certainty about an entire class.

Consume each learner/outcome/topic once; keep one cause chain for memory, directed
score changes and lesson updates so existing `social_delta` and new handlers do
not double-reward it. Apply lessons in both the rules fallback and Gemini context,
with the Game Master retaining authority. Emit `lesson_applied` only when a lesson
materially changes a candidate score, threshold, goal, route or selected action;
record the before/after and decision ID. Merely including memory in a prompt is
not evidence of learned behavior. Bound conflicting lessons using specificity,
confidence and recency; test deterministic tie-breaking.

Provide a working numeric reference fixture: a survivor whose voluntary rest
trigger is remaining Energy <=20 learns to seek rest at <=25 after one directly
experienced collapse, with no change to actual Energy or the Energy 0 fainting
boundary. Cap this learned offset at +20 above the baseline, with a final trigger
within 15..45; count each collapse once. A heard story alone cannot apply the same
high-confidence update. Document analogous bounded rules for other topics and
how contrary successful experiences revise them. This is an initial gameplay
default; store the baseline/offset/rule version rather than silently changing
stable personality fields or hard-coding the fixture into one test path.

Bound active lesson retrieval and per-tick work. Archive/compact superseded lessons
without breaking cited source IDs or losing deduplication/analytics history; do
not resend a lifetime of memories to Gemini or scan every pair each tick.

Save/restart/branch preserve lessons, deduplication, thresholds, confidence,
relationship/proposal states and RNG. Parent and branch evolve independently.
Replaying history or opening a drawer performs no new learning, provider calls,
relationship changes or event ingestion. Legacy worlds get a documented neutral
learning state at the live rule boundary; historical memories may seed lessons
only through an explicit, bounded, versioned operation with provenance.

## 4. Snowflake ingestion, statistics and comparison evidence

The current `backend/app/snowflake/comparison.py` projection stages metrics and
bounded recent event/decision evidence into `AGENTCITY_COMPARISON_EXPORTS_V1`.
It does not stage a complete relationship/learning history. The existing
`POST /api/v1/integrations/snowflake/comparisons` cannot truthfully report all of
these new statistics from that bounded evidence alone.

Extend the canonical export/event stream and add a versioned Snowflake projection
and operator-run SQL migration. Keep core simulation state authoritative; Snowflake
is a rebuildable read model. Preserve existing comparison behavior and old schemas;
do not silently change frozen DTO enums, count semantics or the existing V1 table.
Propose a documented versioned social/learning analytics API with typed frontend
support and an exact route/schema in the handoff. New paths need the same session,
ownership, CSRF/origin and stream-revocation controls as existing paths.

Persist/project these records with owner, simulation, branch lineage, seed,
tick/revision, simulation time, rule/schema versions, source IDs and export hash:

- Relationship snapshots for known directed ties and canonical mutual pair status;
  score changes and explicit stage/conflict/commitment transitions with causes.
- Learning opportunities, lessons created/revised/contradicted/expired, and actual
  applications with changed rule/decision and subsequent observed outcome links.
  Keep free-text private memories out of warehouse payloads unless an explicitly
  documented existing export policy requires them; structured IDs/values suffice.
- Survival/rescue/care/crisis/class-interaction episode references needed to group
  outcomes. Reuse the companion task's canonical events, not duplicate inventions.

Use immutable source event IDs with application-level idempotent ingestion keyed
by owner/simulation/event ID, plus pinned snapshot keys including revision and
projection version. Multiple exports of one event must not count it again.
Inherited branch IDs retain origin lineage; each history includes its ancestry
once and reports post-fork changes separately. Query only through the requested
revision, with no leakage from future events or newer live state.

Snowflake standard-table primary keys are informational. Keep serialized/idempotent
ingestion and detect conflicting hashes/duplicate rows; a declared PRIMARY KEY is
not sufficient. Use bounded batches, durable receipt/checkpoint recovery, backfill
and read-after-write verification. No synchronous warehouse call per physical tick;
paused/offline simulation must still work. Track ingestion lag/coverage and show
unsupported or incomplete histories as unavailable/partial, never fabricated zero.
Do not count an export's entire payload again for each revision or overwrite source
history when retrying. Handle source deletion using existing ownership/retention rules.

### Required statistic definitions

| Statistic | Definition and denominator |
| --- | --- |
| Current relationship distribution | Counts of known unique pairs by friendship stage at a pinned revision; count each pair once, and show romance/conflict as separate axes. Do not create quadratic stranger rows. |
| Directed trust/affection/conflict | Directed edge counts/means and coverage, explicitly distinct from mutual-pair counts. Report endpoint population/life-state filters. |
| Friendship/romance/marriage transitions | Distinct transition events within a stated interval, time to promotion in simulation ticks/seconds and eligible pair counts; migrations are excluded. |
| Arguments/enemies/reconciliation | Distinct episode starts/resolutions/escalations and durations; a continuing dispute is not one new argument per tick. Include which side acted and available evidence. |
| Learning uptake | Distinct eligible observed learner/outcome opportunities, opportunities producing a new/revised lesson and their ratio; denominator is knowledgeable eligible living learners, not all citizens. |
| Learning application | Distinct decision/lesson applications, unique learners applying lessons and decisions changed; distinguish recalled-only from materially applied. |
| Subsequent outcomes | Repeat collapses, timely rest, successful help-seeking/rescue, warning accuracy and repeated harmful encounters after relevant lesson applications; give observation windows and eligible exposure. |
| Personality/class interaction | Aid/conflict/repair and resulting directed attitude changes by documented traits and perceived class at the event; distinguish perceived from actual wealth, with group sizes. |
| Survival/social aftermath | Grief/support, relationship loss/widowhood and survivor learning linked to actual episodes; death is never a successful recovery or a learner. |

For every aggregate specify whether it is an endpoint stock, interval flow,
cumulative count, mean or rate, and show numerator/denominator/units. Use living
person-time or eligible opportunity counts where appropriate. Keep deceased ties
available historically but exclude them from explicitly labeled current-living
graphs. Zero opportunities gives an unavailable ratio, not 100% success or NaN.
Report censoring: no later observed outcome is unknown, not failed or successful.

Calculate complete totals from the projected canonical records, not the latest
16 events/32 decisions currently used for explanation snippets. Bounded samples
can illustrate a total but cannot establish its completeness. Keep current
provider budgets/deadlines and avoid unbounded graph scans or Cortex context.
Use parameterized, owner-filtered SQL and approved metric definitions; no LLM SQL.

Comparison of two pinned histories must include horizons, rule versions, lineage,
coverage and ingestion watermark. Separate inherited baseline from post-fork change;
do not add sibling histories as independent experiments. Display descriptive
associations with source values and supported event/lesson/decision links. Two runs
do not prove learning caused an outcome or establish statistical significance.
Keep Cortex limited to selecting approved evidence-backed facts; the server owns
arithmetic, denominators and claims. Use new citation kinds only in the appropriate
versioned DTO. Preserve explicit `local_export` fallback when Snowflake is absent;
do not label local calculations as warehouse results.

## 5. UI and example acceptance flow

Extend the existing relationship drawer/graph and comparison components in dev's
style. Show friendship, romance and active conflict together, directed scores,
transition timeline and why a change happened. Include a compact "What I learned"
view with evidence, confidence, the concrete changed preference and last use.
Do not publish raw private memory/personality prompts to other agents. Observer
inspection remains governed by existing user ownership; agent knowledge is separate.
Keep live dialogue and per-character voice identity compatible with the voice task.

Show the new Snowflake statistics with filters for interval/branch/stage and
inspectable source records, including loading/disabled/lagged/error/partial states.
A transition badge, decorative line or generated story alone is not implementation.

Demonstrate this deterministic flow end to end:

1. Two strangers meet and accept conversation. Repeated distinct positive contact
   satisfies acquaintance, then friend and best-friend gates over real ticks.
2. One faints from energy 0. A compassionate/cooperative friend physically rescues
   them to a hospital. The survivor wakes, learns the helper/hospital and adopts an
   earlier rest/help-seeking trigger. The helper learns from observed recovery.
3. A later comparable low-energy situation produces earlier valid rest/help-seeking;
   the decision cites the learned rule and actual changed threshold. No collapse
   is prevented by silently granting energy or ignoring fatal fullness/health.
4. The pair may remain best friends, or independently choose a valid lovers and
   later marriage proposal. An argument pauses romance without erasing marriage;
   repeated evidenced harm can produce enemies, with later repair or separation.
5. A generous cross-class rescue revises the recipient's belief about the actual
   helper and can soften class hostility under bounded generalization rules.
6. Save, branch and replay. Snowflake shows exact pair/transition/lesson/application
   counts and cited outcomes at both pinned revisions, including inherited baseline
   versus branch differences. A control branch can decline romance or choose a
   different response without changing the parent's committed history.

## Required automated functional tests

Write and run these as real tests; this checklist is not proof they pass. Use
small deterministic worlds, boundary values and observable committed decisions.

| ID | Case | Required acceptance |
| --- | --- | --- |
| RL-01 | Stranger through best friend, exact score/time/count boundaries. | No skipped stages, premature promotion, unilateral promotion or credit from unanswered invitations. |
| RL-02 | Repeated dialogue turns/retries/views; friendship score downgrade/recovery. | One credit per episode, exact cooldown/hysteresis, no read-side mutation or promotion oscillation. |
| RL-03 | Asymmetric trust, kinship, unknown pairs and seeded/legacy ties. | Directed feelings preserved, mutual status gated, family retained, no fabricated encounter history or all-pairs allocation. |
| RL-04 | Adult romance/marriage, refusal, expiry, withdrawal and simultaneous proposals. | Both independent valid acceptances; one partner; correct timing; no forced romance or refusal penalty. |
| RL-05 | Minor/relative/dead/unconscious/crisis participant; stale acceptance. | Engine rejects invalid commitment atomically, including state changes between proposal and acceptance. |
| RL-06 | Married pair argues, repeated harms become enemies, then repair or breakup. | Conflict does not erase marriage/history; exact episode gates and direction; repair never overrides refusal. |
| RL-07 | Rescue/hospital/faint/shortage/accurate warning/false rumor/violence/crisis fixtures. | Persistent lesson has real evidence and bounded before/after values; observed constraints and uncertainty preserved. |
| RL-08 | Matched worlds differ only in relevant learned state, with the same future inputs/seed. | An actual later rule-based decision changes as specified; irrelevant/low-confidence lessons do not arbitrarily alter it. |
| RL-09 | Gemini structured output and rules fallback use the same lesson fixtures. | Both receive/apply allowed learning; Game Master rejects impossible learned actions and arbitrary score/consent changes. |
| RL-10 | Remote/private event, unconscious rescue, reported death and conflicting accounts. | Only knowledgeable living learners update; no mind reading, dead learning or unsupported certainty/group blame. |
| RL-11 | Duplicate outcome callbacks, contradictory evidence and cross-class generosity/harm. | No double social reward/lesson; confidence can revise; target-specific updates precede bounded generalization. |
| RL-12 | Save/restart/branch/replay with proposal, conflict and lessons in flight. | Exact independent state/RNG/history, no repeated learning or new provider/ingestion work on replay. |
| RL-13 | Canonical export -> Snowflake fake transport -> SQL aggregate -> versioned API. | Exact expected row keys, scores, pair/directed counts, opportunity denominators, transition/application totals and evidence links. |
| RL-14 | Repeat exports/ingestion retry/crash/duplicate/conflicting hash/branch-inherited IDs. | Idempotent complete results, recoverable receipts, no double count, future-state leak or silent corruption. |
| RL-15 | Zero eligible pairs/opportunities, all dead, unequal horizons and incomplete backfill. | Finite metrics or explicit unavailable values, correct filters/coverage/units and no unsupported success/causal claims. |
| RL-16 | Two pinned revisions and Cortex invented facts/citations/arithmetic. | Correct source values and lineage; reject unsupported model claims; truthful deterministic/local fallback. |
| RL-17 | Legacy migration, strict old clients, new DTOs/auth/CSRF/ownership. | Old contracts/hashes and histories preserved, explicit compatibility, private records inaccessible to another owner. |
| RL-18 | Real browser progression, learned later action, conflict and comparison evidence. | Visible state/timeline/graph/statistics agree with backend, correct partial/disabled states and preserved voice focus. |

Add an opt-in live Snowflake smoke test using a disposable owned simulation and
dedicated projection namespace. Verify actual committed rows, parameterized query
readback, exact expected aggregates and source citations, then clean its data.
Default tests use deterministic local/fake transports with no paid calls. Distinguish
offline SQL/transport coverage from real warehouse verification in the handoff.

## Delivery and coordination

Implement in coherent increments: versioned relationship/lesson state and migration;
friendship/conflict/consent mechanics; outcome learning and changed future decisions;
export/SQL/projection/API; UI and integrated browser evidence. Coordinate shared
engine/state/Game Master/schema/UI edits with the survival and voice assignments.
New behavior must work without Snowflake, Gemini or ElevenLabs being enabled.

Run focused tests as each increment lands, then existing backend/frontend,
contract/lint/build gates and relevant browser suites on the integrated branch.
Write `docs/release/relationships-learning-handoff.md` with rules/defaults,
migrations, exact routes/schema/SQL setup, seed/commit, evidence coverage, tests
run and remaining limitations. Append the dev log and push the focused branch.
Do not claim the requested mechanics or warehouse tracking from this prompt alone.
