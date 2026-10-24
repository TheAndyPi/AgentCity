# Contract review — version 1.0.0

No endpoint, JSON field, unit, transition or wire version was changed. The final
shared baseline is frozen and verified by hashes, Python/JSON Schema fixtures,
OpenAPI comparison and the normative endpoint-table coverage test.

Two interpretations are explicit for frontend integration:

1. **Provider usage unavailable.** Usage counters are required nonnegative
   integers, while the prose requires measured or explicitly unavailable usage.
   A timeout/response without usage metadata makes the aggregate unknowable.
   The current compatible behavior returns `503 SERVICE_UNAVAILABLE` from the
   affected Usage query, with an explanation, instead of inventing zeros. A
   future coordinated contract could add an availability field or nullable
   token counters. Affected consumers: Usage panel/export tooling; no migration
   or contract edit is made here. No-provider rules runs retain valid zero usage.
2. **Derived metric overrides.** Metrics must retain the mandatory formulas.
   Resource overrides therefore require conserved transfers at known nearby
   stock/deposit access; safety overrides cannot exceed the current hazard
   ceiling. Impossible requests return a concrete validation/precondition error.
   The advanced inspector should display that error rather than assume an
   arbitrary number can bypass physics. This follows the existing invariant;
   no extra override field or endpoint was invented.

The merged frontend now passes Zod validation of the shared fixtures and real
browser/proxy rehearsal. See [integration-handoff.md](integration-handoff.md).
Both interpretations above remain compatible with the consumer. Optional sponsor
adapters and credential-dependent live smoke tests remain explicit limitations.
