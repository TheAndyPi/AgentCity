# Behavior extension 2.0.0

This is an independently versioned extension to the frozen 1.0.0 API. It does not
replace, loosen, or regenerate `contracts/v1/`. Its strict normative response
schema is `behavior.schema.json`, with an executable producer/consumer fixture in
`fixtures/behavior.json`. The complete child OpenAPI is documented in
`docs/release/integrations-openapi.json`.

Owned, authenticated GET routes:

- `/api/v1/integrations/behavior/v2/simulations/{sid}?revision=N`
- `/api/v1/integrations/behavior/v2/simulations/{sid}/export?revision=N`

Omitting revision reads the committed head. Both return the same pinned response
shape: `schema_version: "2.0.0"`, request ID, simulation ID, tick/revision, seed,
rule activation boundary, citizen conditions, structured learned rest rules,
engine fires, hospital stocks/claims/patients, evidence events, v2 action decisions
and explicitly defined analytics. Reads never tick, learn, roll randomness or call
providers. Export preserves evidence IDs and source tick/revision; checkpoints
additionally persist both RNG states and the full underlying world.

These paths live inside the already guarded v1 integration mount; the prefix is
intentional. Parent session, Origin and CSRF protections remain in force. The
route also resolves ownership at the requested revision. Validation/error
responses retain the existing core error envelope. There are no new public write
or WebSocket routes. Existing owned commands drive physical ticks and remain
subject to CSRF, Origin, idempotency and control-version checks.

V1 keeps its exact action enums and DTOs. Dead citizens project `active=false` and
an idle action; unconscious citizens remain active/living, idle and visibly marked
unconscious. New actions live in the extension's own decision list. Core evidence
links whose IDs start `behavior_` resolve through the v2 evidence panel rather
than requesting a nonexistent core decision. Existing recorded dialogue, voice
identities, captions and narration authorization are unchanged.

The v2 read model explicitly marks Tiger/Snowflake behavior support false. Those
adapters still support their existing core projections; no new behavior totals
are inferred from incomplete v1 records. The companion relationship/learning
assignment can consume these canonical outcomes and extend the independent
versioned schema without adding values to frozen v1 enums.
