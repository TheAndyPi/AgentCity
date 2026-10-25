# Disaster extension 2.0.0

This extension does not change frozen `contracts/v1` DTOs, enums, streams or
snapshots. Its strict OpenAPI is [openapi.json](openapi.json); executable typed
fixtures are in [fixtures/typed-controls.json](fixtures/typed-controls.json).

Base: `/api/v1/integrations/disasters/v2/simulations/{sid}`. GET `/state` and
`/export` accept an optional exact `revision`. POST `/previews`, `/commits`,
`/events/{eid}/cancel`, and `/repairs` use the existing owner, session, Origin,
CSRF, canonical UUID idempotency receipts and single simulation writer. Preview
metadata never mutates the physical world or its random generator. A monotonically
increasing `editor_generation` rejects out-of-order control requests inside one
intervention. Commits require the exact unexpired preview ID, revision and control
version; cancellation never rewinds damage.

Core v1 clients see earthquake/tornado summaries as `custom` with a compatibility
`storm` hazard projection. The engine uses the typed parameters, never that proxy,
for physical exposure. New renderers replace that generic overlay with the current
v2 footprint. Flood/fire/storm queued through existing v1 scenarios acquire explicit
SI/gameplay parameters on live activation, preserving their original selected
polygon. Frozen historical states are read without migration. Existing active
legacy hazards keep their old semantics until a new activation; their baseline
infrastructure values are recovered when condition state is first initialized.

The root revision/time applies to every event view. Stable event/phase IDs,
parameters, rule version, seed, maximum and current footprint/origin, damage IDs,
service changes, reaction source records and vocal eligibility are published
at that revision. Queued and cancelled events have no active footprint. Reactions
are independent of conversations, voice availability, and playback success.

`/export` contains the complete canonical damage/condition/terrain/service/repair
records and separate unique damaged-building and structural-transition totals.
The state projection retains only the newest 100 reaction captions; exports retain
all reaction records. Do not use caption windows as cumulative analytics.
# Geometry precision

Clipped footprint coordinates are canonicalized to nine decimal places in map
meters and clamped to the exact map bounds. This removes platform-specific
trigonometric roundoff without changing the selected extent or local exposure
curve. The executable footprint fixtures use the same documented precision.

