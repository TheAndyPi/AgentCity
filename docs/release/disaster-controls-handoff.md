# Disaster controls and persistent damage

Implemented on `codex/disaster-controls-damage`, continuing `16bed98`. The existing
live voice implementation is retained. Delivery date: October 25, 2026, New York.

## Use

Choose **Introduce an event**, then a disaster type. Radius/width, danger, origin,
track end and duration are independent native numeric/range inputs. Arrow keys or
a map click move the origin. The solid preview is the validated clipped envelope;
a dashed circle is an unvalidated draft. **Preview event** performs validation;
**Confirm event** commits that exact preview. Editing invalidates the commit key,
aborts obsolete preview requests and ignores their completions. No automatic
requests run while dragging. Repeating a resolved typed event copies its original
parameters and computes fresh coverage against the current damaged city.

Damage persists after Continue, cancellation, reload, saves and branches. The
**City condition** panel and building hover tags report integrity, stage, cause,
capacity and occupancy. Ground marks/debris remain in 2D and 3D; destroyed 3D
buildings become low rubble. Crosses, labels and the legend supplement color.
There is no camera shake. Repairs cost **10 public supplies / 30 simulation
seconds**, restore at most 25 integrity, and require no occupants/reservations or
local active/queued hazard. **Clear doorway debris** costs **2 supplies / 10
seconds** and can free occupants before structural repair. Public supplies are
reserved once at scheduling; blocked jobs retain their documented spent cost.

## Rules: disasters-2.0.0

Map coordinates are meters, currently a 128 × 128 m map with 2 m cells. The minimum
extent is one cell; maximum is the map diagonal (181.019 m on this map). Tornado
extent means full width; other extents mean radius. Origins are in map bounds;
tracks may cross an edge within a map-diagonal length and margin. Convex clipped
48-segment envelopes are validated for positive area and simple geometry.

| Type | Canonical intensity | Normalized peak | Structural / health rate |
| --- | --- | --- | --- |
| Earthquake | Mw 2–9, step .1, default 5.5 | `((Mw-2)/7)^1.5` | 5 / 1 |
| Tornado | 0–130 m/s, step 1, default 50 | wind / 130 | 4 / 2 |
| Flood | 0–5 m depth, step .1, default 1 | depth / 5 | 1.5 / 1 |
| Fire | gameplay heat 0–100, default 50 | heat / 100 | 5 / 2 |
| Storm | 0–75 m/s, default 30 | wind / 75 | 1.5 / .5 |

Rates are actual loss at local exposure 1 per **five simulation seconds**.
Per application: `loss = rate × local_exposure² × tick_seconds / 5`, capped by
remaining health/integrity. Construction resistance is deterministic **1** for all
initial buildings. Earthquake attenuation is `1/(1+(distance/24m)^2)` within its
selected envelope: enlarging radius does not amplify an already covered location.
Tornado position interpolates along its track over the event; radial wind is
`peak × max(0,1-distance/(width/2))`. Flood/fire/storm use uniform bounded exposure.
There is no fire spread outside the envelope. Terrain marks require local exposure
at least .25; unsafe/destroyed structures produce bounded doorway rubble inside
the selected envelope. Resource stock loss is `2 × exposure² × tick_seconds/5`
units per exposed resource/application, capped at stock remaining.

The one application hook runs after citizen movement and before legacy community
and wellbeing effects. `last_physical_tick` deduplicates it. Existing duration
semantics are preserved: activation at tick S, final application/resolution at
S + duration (duration + 1 sampled applications). This is simplified continuous
shaking/exposure gameplay, not an earthquake impulse/risk calibration. Tornado
wind is sampled at the physical tick's moving center, rather than integrating a
continuous fluid field. Preview reports a conservative 0–peak structural loss
range over those applications; actual committed transitions are separate records.

At the same physical boundary, indoor health loss is multiplied by .4; an unsafe
occupied building uses 1.4. An exposed new entrant joins the evidence cohort.
Inactive/zero-health agents do not vocalize; fatigue 100 also blocks reactions.
This branch preserves existing help/need mechanics and does not add the separate
survival task's mortality, carrier, patient or mental-crisis state machine.

Integrity 100 is intact, 50–<100 damaged, >0–<50 unsafe, and zero destroyed.
Effective capacity is `floor(design_capacity × integrity/100 × minimum active
closure multiplier)`, with multiplier at most 1; unsafe/destroyed or otherwise
closed facilities have zero public capacity. Existing occupants retain their
places rather than creating/removing people or extra beds. Admission uses the
reduced capacity. Removing a closure recomputes all causes, never restores an old
map over durable condition. Exact fixture: integrity 80 minus actual 5 becomes
75 once; reads/resolution do not restore 80 or charge another 5.

Unsafe occupants use their legal doorway route if the approach is clear; otherwise
a persistent trapped/rescue need is published. No remote safe placement occurs.
Clearing debris permits later egress. Routes and plans are invalidated on damage
stage/topology changes. Movement and personal-space recovery respect debris.
Independent physical events add their own bounded losses once each; repeated
handlers/reads of one event do not create extra applications.

## API, persistence and projections

See [v2 contract](../../contracts/disasters-v2/CONTRACT.md). The local immutable
journal stores condition, debris, sources, cooldowns, repairs and parameters with
RNG/checkpoints. Historical reads never advance physics. Legacy maps acquire
intact condition at a live boundary; no past history is rewritten. V1 flood/fire/
storm activations bridge to typed parameters with severity converted to their
bounded native unit/precision. Typed earthquake/tornado use a strict v1 `custom` /
`storm` compatibility projection; v2 consumers use their real type and geometry.
Natural input recognized in the custom editor fills the same controls. Narrative
modifiers outside those controls are explicitly listed as unapplied in preview.

Tiger migration `002_disaster_damage.sql` adds complete event, condition, damage,
terrain, service, reaction and repair records; damage event IDs distinguish repeated
transitions from unique buildings. Snowflake comparison payloads carry a complete
versioned disaster projection when present. Run `002_disaster_projection.sql` after
its existing setup for the corresponding read view. Core comparison metric rows
still describe the original metrics; they do not pretend bounded explanation
citations are damage totals. Missing disaster projection is unavailable coverage.
Live Tiger/Snowflake SQL execution remains opt-in; local authoritative records do
not require either provider.

## Verification

Executable cases live in `backend/tests/test_disasters.py`,
`backend/tests/test_disaster_audio.py`, `frontend/tests/disasters.test.ts`, and
`frontend/narration-e2e/disasters.spec.ts`. They cover clipped controls and geometry,
zero/intensity/area independence, moving exposure, indoor protection/late entrants,
footprint intersection, exact loss/idempotent reads, overlapping closures, repairs,
trapping/clearing, cancel, historical reads, save/branch, late preview generations,
and real decoded browser media. Audio delivery/configuration and remaining external
audition are documented in [disaster audio handoff](disaster-audio-handoff.md).
Final command results and tested commit are appended in the development log.
