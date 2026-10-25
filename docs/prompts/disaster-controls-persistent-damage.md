# Task: disaster size/intensity controls and persistent map damage

Implement this assignment in AgentCity with executable functional tests. Read
applicable instructions, `docs/dev-log.md`, current scenarios/previews, contracts,
map/navigation/building visits, survival rules, exports and frontend before editing.
Fetch latest dev and start `codex/disaster-controls-damage`; inspect an existing
branch before reuse. Preserve dev's frontend design, scenario flow, movement fixes,
security and existing integrations. Deliver functioning mechanics, not just sliders
or a disaster animation.

Coordinate with [disaster audio](elevenlabs-disaster-audio.md),
[survival/personality/class conflict](agent-survival-personality-class-conflict.md)
and [relationship learning/Snowflake](relationships-learning-snowflake.md).
Those task files describe integration requirements, not already shipped features.

## User outcome and current foundation

The user can choose **how large a disaster is** and **how dangerous it is** using
separate sliders, see an accurate preview, and commit that exact configuration.
Earthquakes expose magnitude; tornadoes expose wind speed. Disasters physically
affect citizens, terrain, roads, buildings and services. Damage remains visible
and meaningful after the active disaster ends.

Current `EventSpec` has origin, affected polygon, severity 0..100 and duration.
Hazard types currently support flood, fire and storm. The scenario dialog shows
severity/area but does not provide this complete control model. Earthquake/tornado
scene props are not proof of earthquake/tornado mechanics. Infrastructure effects
currently change functionality/capacity and restore saved values on resolution;
that must not undo structural damage or a different event's continuing effects.

## 1. Independent controls and a truthful preview

Extend the existing scenario dialog in its current style. Support existing physical
disasters plus actual earthquake and tornado types; keep nonphysical scenarios
such as policy changes and misinformation working without irrelevant size sliders.

| Control | Required behavior |
| --- | --- |
| Disaster type | Earthquake, tornado, flood, fire and storm, with type-specific supported effects. |
| Size/extent | Explicit footprint radius/width in map meters, with numeric input and map overlay; changes coverage without silently increasing peak intensity. |
| Danger/intensity | Type-specific numeric slider/input with unit and description; changes local exposure/damage without silently enlarging the selected footprint. |
| Location | Move epicenter/ignition/origin on the preview map, within valid bounds. |
| Duration | Retain existing duration semantics; expose a control showing ticks and simulation time. |
| Tornado track | Direction/end point or short editable path and width; show the entire swept envelope and movement over time. |

Size bounds derive from actual map dimensions/cell size: a positive minimum
footprint and a documented map-diagonal maximum, clipped to valid map geometry.
Reject zero/negative/NaN/infinite values and degenerate/self-intersecting polygons.
Show clipped coverage and affected counts; an edge/corner origin must work. A
tornado's width and track length are distinct from its wind speed. Do not label
map meters as kilometers without a documented conversion.

Initial gameplay defaults, configurable and versioned:

- Earthquake: moment magnitude Mw 2.0..9.0, step 0.1, default 5.5; explicit area
  radius. Keep magnitude distinct from the distance-dependent local shaking proxy.
- Tornado: peak wind speed 0..130 m/s, step 1, default 50 m/s; optional mph display
  derived from the same stored SI value. At wind speed 0 there is no wind damage.
- Flood: water depth 0..5 m, step 0.1, default 1 m, plus selected inundation area.
- Fire: clearly labeled gameplay heat/danger 0..100, default 50, with bounded spread.
- Storm: peak wind speed using a documented bounded range, plus rain/exposure if
  implemented; do not imply tornado rotation/path behavior for a generic storm.

These are simplified game parameters. Magnitude is a source property while local
shaking varies by location; see [USGS magnitude versus intensity](https://www.usgs.gov/faqs/what-difference-between-earthquake-magnitude-and-earthquake-intensity-what-modified-mercalli).
Use a versioned monotonic gameplay curve, not a claim of calibrated seismic risk.
If showing an EF-style tornado descriptor, label it a gameplay approximation:
real EF ratings use surveyed damage and estimated winds, not a direct wind-meter
reading. See [National Weather Service EF scale](https://www.weather.gov/grb/efscale).

Keep one canonical type-specific intensity field. Any normalized severity is a
derived engine value, not a second contradictory editable source. Document the
mapping, precision, clamping and conversions. Zero intensity produces no associated
damage. Supported natural-language inputs (for example "magnitude 6.2" or
"tornado, 60 m/s, 20-meter width") compile into the same typed controls; unsupported
parameters are shown explicitly, not silently discarded or invented by Gemini.

Changing controls invalidates the old preview and commit key. Debounce/abort
preview requests and ignore stale responses. Preview is side-effect free: no map
mutation, world RNG advance, damage, fear reaction or paid audio generation.
Commit the exact server-validated, revision-bound preview; stale/expired previews
require refresh. Repeat copies the original disaster parameters, not its old
aftermath or an already clipped polygon as a new damage baseline. Refresh affected
counts against the appropriate current revision.

## 2. Authoritative footprint and exposure

Persist typed parameters, origin/track, normalized intensity mapping, footprint,
timing, rule version and seed. The engine, map overlay, preview counts, injury,
damage, navigation and audio must consume the same authoritative geometry.

Implement a bounded local exposure function by type and simulation time:
earthquake shaking attenuates from its epicenter; tornado winds follow the moving
track and fade toward its edge; flood depth and fire/storm exposure follow their
declared profiles. Clearly show the active footprint versus the maximum selected
or swept envelope. If fire spreads, cap it to the selected envelope and document
fuel/spread timing. No invisible citywide damage outside that envelope.

Use footprint intersection for buildings/roads/cells, not only whether a building
entrance is inside the polygon. A damaged building may lose service even when its
entrance lies outside the selected area. Calculate citizen exposure at their
actual location with documented indoor protection and structural risk. Distinguish
ongoing exposure from initially affected cohorts; entering the path later matters.

Apply exposure once per physical tick/impulse at the documented engine phase,
scaled by simulation time. No extra damage from rendering, polls, saves, control
revisions, duplicate provider callbacks or reconnect snapshots. Coalesce effects
sharing the same causal hazard; define how genuinely separate disasters combine
without accidentally charging the same event twice.

## 3. Persistent terrain, buildings and services

Add versioned durable condition state instead of destructive changes to the base
map template: building structural integrity 0..100, damage stage, cause history,
service restrictions, debris/blocked cells and damaged roads/resources as needed.
Keep entity IDs stable for inspectors, navigation, historical evidence and audio.
Use deterministic documented construction/resistance defaults, not an LLM guess
from a building name or a citizen's wealth.

For each hazard document numeric exposure -> structural-loss/injury/terrain rules,
caps and thresholds. Include an exact reference fixture: integrity 80 receiving
5 actual damage becomes 75 once, with evidence; refreshing/ending the event does
not subtract another 5 or restore 80. Require monotonic intensity and repeated
exposure behavior in controlled fixtures. Larger area increases possible affected
objects, not the damage inflicted on an unchanged object at the same local exposure.

| Disaster | Persistent consequences to implement |
| --- | --- |
| Earthquake | Cracked/unsafe/collapsed buildings, localized rubble and road/entrance obstruction, interrupted affected services. |
| Tornado | Damage along its actual track, roof/structure damage and bounded debris; nearby unaffected districts remain intact. |
| Flood | Inundation during the event, damaged buildings/stocks/roads where exposed, with water recession distinct from repairing damage. |
| Fire | Burning during the event, actual structural/resource loss, charred ground and rubble after extinguishing. |
| Storm | Wind/rain damage under its supported profile, localized debris/service disruption; no automatic earthquake-style collapse everywhere. |

Initial service defaults: intact integrity 100; damaged 50..<100 with reduced
capacity; unsafe >0..<50 with zero public service; destroyed 0. At exactly 50 use
the damaged rule. Capacity is a deterministic bounded function of design capacity
and condition, with a separate policy for beds/occupancy already in use. Document
visual stages and the capacity formula; permanent damage cannot silently increase
capacity or supplies. A visual crack/smoke effect must correspond to real state.

Separate (a) durable condition, (b) baseline capacity/functionality, (c) temporary
closures from each active event, and (d) repairs. Effective service derives from
all current causes. Removing one event's temporary closure cannot resurrect a
collapsed building, undo another event, reopen an occupied unsafe hospital or
restore already destroyed stock. Resolution must never blindly restore the old
`infrastructure_before` values over newer condition state.

Invalidate stale paths, facility choices, claims and entrance/bed reservations when
roads/buildings change. Route around real rubble; do not walk through newly
blocked cells or restart the old doorway deadlock. For occupants/carriers/patients
inside a collapsing building, define one causal injury/trapped/egress outcome with
safe legal placement where possible. If no exit exists, persist a trapped state
and expose rescue needs; never teleport everyone to safety or spawn citizens
inside solid rubble. Dead/unconscious rules and carrier failure remain authoritative.

Damaged homes affect shelter/rest choices; closed shops/workplaces/hospitals affect
stock access, work, care and rescue routing. Reconcile occupancy once without
duplicating people, beds, supplies or resource losses. New hazards can compound
existing damage. Stopping/cancelling an active event stops future exposure but
does not rewind committed harm; cancelling a queued unstarted event does no damage.

Include a minimal validated repair/debris-clear path: an operator intervention is
acceptable if agent construction actions do not exist yet. It must consume the
documented time/resources, validate occupancy/safety/claims, and record before/after
evidence. Reopening/reconstruction is explicit; event resolution is never repair.
Do not expand this assignment into an unrelated construction-management system.

## 4. Agent, UI, persistence and analytics integration

Feed perceived hazards/damage into evacuation, safe shelter, rest/work, rescue and
hospital selection. Reuse the survival task's health/fullness death, energy fainting,
mental/stress crisis and actual treatment logic. A stronger hazard cannot bypass
life-state checks. Provide observed/heard event references to the learning task
for later route avoidance, preparedness, source trust and help-seeking lessons.

The map visibly retains damage after outcome dismissal/Continue. Show condition,
service/capacity, obstruction and cause in existing inspectors, with a legend and
accessible non-color labels. Distinguish projected damage ranges from committed
damage. Keep any camera shake bounded and honor reduced motion. Preserve the
current 2D/3D presentation and navigation style; do not replace the frontend.

Save/restart/branch retain condition, debris, active track/time, closures, repairs,
claims and RNG. Replay reads the map at its pinned revision, before and after harm;
no new damage/randomness/audio jobs during history scrubbing. Branches mutate
independently, including repeating a disaster on an already damaged map.
Legacy maps start with documented condition defaults at a live rule boundary;
do not retroactively create damage in frozen histories.

Use a coordinated versioned state/API/stream extension. Do not edit frozen v1
snapshots, insert new disaster enums into strict v1 responses or weaken parsing.
Keep old clients/worlds working through a documented compatibility projection.
New routes/streams need auth, ownership, CSRF/origin and revocation coverage.

Export intensity with units, selected/actual footprint, exposure, damage transitions,
service downtime, blocked cells, repairs and outcome evidence. Extend Tiger/Snowflake
read models through versioned migrations and complete canonical records. Report
building counts once per entity versus repeated damage events separately, with
before/after integrity and resource units. Label missing projection coverage;
do not infer totals from bounded explanation snippets or treat dead as evacuated.

## 5. Shared contract for the disaster-audio instance

Own the authoritative disaster/damage event schema and publish typed fixtures early.
Coordinate exact version/route names with the audio instance before either edits
shared schemas. The following is the minimum semantic contract, not new v1 fields:

- Committed event/phase/damage IDs, simulation/revision/tick and simulation seconds,
  type, parameters with units, normalized intensity and rule version.
- Lifecycle phase (queued/start/active/resolve/cancel), actual current geometry,
  origin/track, and evidence links to damage/exposure. Queued/preview is not active.
- Local perceived-threat/reaction source records with agent ID, conscious/alive
  state, cause, location, nearby/audible scope and a stable episode ID. Reaction
  records are independent of conversation acceptance and cannot force dialogue.

You own lifecycle, geometry, structural condition, routing and source publication.
The audio instance owns ElevenLabs transports/assets, vocal delivery and mixer/UI.
Agree on one engine hook for deterministic fear/scream reaction selection; do not
create competing stress/crisis loops. It may stage a pure reaction module plus
fixtures until you wire it to committed perception. Audio failure never pauses
simulation or rolls back damage. No music/sound generation in previews or ticks.

## Required automated functional tests

Write these as executable tests, not only manual checklist items.

| ID | Case | Required acceptance |
| --- | --- | --- |
| DS-01 | Independent size/intensity sliders and numeric controls for each disaster. | Exact units/bounds, synchronized values, keyboard support, canonical payload and no silent coupling. |
| DS-02 | Rapid preview changes/out-of-order responses/stale commit/repeat. | Latest preview wins; exact revision-bound commit; repeated events preserve parameters, not old damage baselines. |
| DS-03 | Edge/corner geometry, min/max size, track crossing map boundary, invalid numbers. | Valid clipped envelope or clear rejection, consistent counts and no invalid/self-intersecting polygons. |
| DS-04 | Small versus large area, weak versus strong event with matched seed/exposure. | Coverage and danger change independently; monotonic effects and zero-intensity no-damage boundary. |
| DS-05 | Earthquake attenuation and moving tornado track. | Actual location/time exposure, entrants affected, out-of-envelope entities intact; scene props alone cannot pass. |
| DS-06 | Building footprint intersects but entrance does not; indoor versus outdoor citizens. | Documented overlap/protection semantics in preview, structural damage and actual exposure. |
| DS-07 | Integrity 80 ->75 fixture; repeated reads/frames/save; alternate tick duration. | Exactly one actual loss per cause/time interval, correct scaling, caps, stages and evidence. |
| DS-08 | Each disaster damages buildings/roads/terrain/stocks. | Real bounded mechanical and visual changes, conserved stock, no cosmetic-only success. |
| DS-09 | Resolve/cancel event; overlapping closures/damage; already damaged baseline. | Temporary effects removed by cause, durable damage retained and unrelated/current restrictions preserved. |
| DS-10 | Active paths, crowded doorway, damaged entrance, closed/full hospital. | Replanning/claim cleanup and usable legal fallback without deadlock or walking through rubble. |
| DS-11 | Occupied collapse with patient/carrier/unconscious/dead citizen and no legal exit. | One causal injury/egress/trapped outcome, no teleport/duplicate occupancy; authoritative life/rescue rules. |
| DS-12 | Damaged home/shop/workplace/hospital and repeated disasters. | Effective services/capacities and real agent choices match condition, with no stock/bed inflation. |
| DS-13 | Explicit repair/clear valid versus unsafe/insufficient/stale duplicate request. | Conserved costs, correct timing, atomic claims and no free event-end reconstruction. |
| DS-14 | Save/restart/branch/replay during track motion, aftermath and repair. | Exact independent map/claims/RNG/closure history; no replay damage or new provider work. |
| DS-15 | Legacy state, strict clients and new route/stream authorization. | Documented migration, frozen v1 hashes preserved, private/unowned mutation denied. |
| DS-16 | Typed lifecycle/perception fixtures consumed by audio and learning. | Stable source/episode IDs, current geometry/intensity and no reaction from previews or read callbacks. |
| DS-17 | Tiger/Snowflake export/read-model fixtures. | Exact entity/event damage totals, units/lineage/coverage, no duplicate interval counts or unsupported totals. |
| DS-18 | Real browser: set size/danger, commit, watch damage, resolve, Continue, save/reload. | Preview agrees with runtime; lasting map/service damage and sliders work in dev's existing design. |

Run focused deterministic tests, then backend/frontend/contract/lint/build gates
and relevant browser suites on the integrated branch. Default tests use no paid
providers. Record actual results, seed/rules/commit, limitations and commands in
`docs/release/disaster-controls-damage-handoff.md`; update the dev log and push the
focused branch. Do not claim real-world engineering accuracy or shipped mechanics
from this specification alone.
