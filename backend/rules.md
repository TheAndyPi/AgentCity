# Versioned rules, 1.0.0

All arithmetic is finite. Percentage results clamp to 0–100. Coordinates are
ground-plane meters, x east/y north. One physical tick is ten simulated seconds;
speed changes wall-clock cadence, never the tick duration or walking distance.

| Rule | Value/behavior |
|---|---|
| Grid | 64×64 cells, 2 m per cell, four-neighbor A* |
| Route preference | A* cost 1 per road cell and 4 per other walkable cell; lawns remain available for destination access or detours, while water/buildings/hazard-blocked cells remain forbidden |
| Walking | `1.4 * (0.5 + mobility/100)` m/s; default mobility 50 |
| Sight / hearing / physical action | 20 m with line of sight / 8 m with line of sight / 3 m |
| Hunger / fatigue / unmet social need | +0.6 / +0.4 / +0.2 per tick |
| Rest | Fatigue −6; stress −0.6 |
| Consume | Removes positive personal units; food/water reduce hunger 12/unit; supplies restore health 2/unit; happiness +0.4 |
| Gather | Transfers stock to inventory; proximity, remaining stock, kind and per-tick ration checked |
| Work | Valid functional workplace and per-tick capacity; transfers 0.25 supply units from the settlement stock pool; happiness +0.2 |
| Help | Removes 1 supply unit; target health +5×aid multiplier; target stress −2; helper happiness +1 |
| Talk | Local message/invitation; social need −5; happiness +0.3 |
| Social update | Once per directed evidence key; ordinary deltas at most ±5; final values clamped |
| Hunger >80 | Stress +0.5, happiness −0.4 per tick |
| Hazard exposure | Health damage `severity/100 × factor`; factors flood=1, fire=2, storm=0.5; stress +2×severity/100; happiness −severity/100 |
| Severe hazard routes | At severity ≥80, affected low-elevation land cells (<0.3 m) are blocked; public roads stay usable |
| Festival | Eligible local citizens: happiness +0.8 and stress −0.5 per tick, within capacity |
| Community aid | Eligible citizens receive 0.25×aid multiplier external supply units/tick; additions logged separately |

Work's settlement stock pool is a deliberately abstract supply chain, with
conserved units; this model does not simulate delivery vehicles. No other
physical action transfers inventory remotely. Trade first stores an offer without
transferring anything; the nearby recipient must submit an acceptance with its
own offered resource. Both debit/credit sides validate before either changes.
Rejected intents produce immutable Decision audit records, with no partial
inventory/health/relationship effects. A legal work-capacity claim or final-unit
claim is resolved in persisted seeded shuffled order rather than stable ID order.
Evacuation reserves facility capacity for accepted in-flight paths.

Aid groups store membership, proposal, actual acceptances, evidence and expiry.
Invited neighbors do not automatically contribute. Only an accepted help action
records participation and consumes supplies. One accepted help is one cooperation
count; group bookkeeping does not double count it.

Profiles use trait-aware generated diversity; selected custom profiles replace
generated citizens within the requested population. Their exact template version
is copied, and future template edits/deletion leave existing citizens intact.
Settlement and density change placement/clustering and building heights;
infrastructure changes capacities, and availability changes initial depot stocks.

Safety is `100-max(local_hazard_severity,100-health)`. Resource score is
`100*min(1,total_inventory/max(1,target_inventory_units))`, initially targeting
12 abstract units per citizen. Trust is the mean outgoing known-person trust,
or configured community trust without known ties. Happiness/stress are stored
state variables with evidence-bearing rule contributions. Population values are
means of active citizens; zones use authoritative cell membership to assign
boundary positions once, average their citizens, and use world means if empty.
Density is people divided by polygon area in square kilometers.

An advanced metric override preserves these formulas. Happiness/stress are
directly adjustable; trust changes outgoing scores; safety changes health and
cannot exceed a current hazard's physical limit. Resource score changes require
conserved stock/deposit transfers to known sources within 3 m; unavailable stock
or access rejects the command atomically. Goal/memory/intent overrides are
recorded as owner interventions; an intent still passes normal legality checks.

Counts are cumulative except current exposure and current-event evacuation.
Conflicts count contested stock claims, not every invalid intent. Removed food,
water and supplies count as consumption; transfers do not. Resource-multiplier
events and aid have separately logged external stock changes. Reports freeze the
initial affected cohort at activation and measure the event interval. They show
association, not causal proof. No lessons are invented when none are evidenced.

Events activate on the next physical tick and end at `start_tick+duration_ticks`,
or earlier for a validated all-safe condition. A flood-only preview does not
silently destroy infrastructure or multiply stocks. Outage functionality/capacity
and temporary policy overlays restore their scoped baseline on expiry. Removed
stock never regrows when a shortage ends. Uniform polygon hazards and simple
exposure rules are intentional; hydrodynamics and epidemiology are unsupported.

Custom events accept any nonempty description (up to 2,000 characters). The
premise is delivered locally as a reliable world observation, enters citizens'
memories and beliefs, and becomes available in perception and conversation. Rumor
requests retain uncertain, heard information instead. Familiar flood, fire, storm,
shortage, outage, festival/aid and policy terms add their existing physical effects.
The preview explains these separately: an arbitrary premise does not implement new
physics, spawn geometry, or force a citizen's choices. Severity, duration and compass
regions remain available. Unrecognized events default to the whole city. Random
and repeat use the same validation/commit path; repeat retains the original spec.

Nearby citizens prioritize a reply to an open conversation after urgent care and
needs. Rule-based dialogue uses the speaker's observed events, goals and values;
provider-supplied speech is retained. Conversations remain local, explicitly
accepted, and bounded to four turns. The UI groups lines by interaction ID and
orders them by tick and persisted sequence; overhearers are not participants.

Memory retrieval combines importance, recency and lexical relevance. Every 20
ticks, meaningful recent episodes can produce a subjective summary referencing
the retained originals. Provider contexts cap at eight memories, eight observed
people, six ties and six messages, plus self context/known locations and a hard
size bound. Other citizens' private profiles, inventories, needs, memories and
goals are not supplied. Remembered distant family ties do not reveal positions.
