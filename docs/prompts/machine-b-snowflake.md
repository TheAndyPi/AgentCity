# Machine B - Snowflake and one grounded comparison

Implement Snowflake ingestion and one evidence-backed comparison flow using
AgentCity's existing exports. **This assignment excludes scenario fixes.** Read
`docs/dev-log.md`, `docs/release/integration-handoff.md`,
`docs/release/acceptance-cases.md`, and applicable repository instructions.

Fetch latest `origin/dev` and work on `codex/snowflake-comparison`. Baseline
observed was `560e2ed`; do not overwrite the newer frontend or Machine C's patched
dependencies, Settings retry lifecycle and provider deadlines. Existing scenario
semantics/clarification and lesson facts are protected from this assignment.

## Deliverables

1. Consume the existing owned JSON export at explicit revisions for two histories.
   Implement Snowflake staging/ingestion with idempotent keys that separate source
   and branch. Store metrics and the selected event/decision evidence needed for
   comparison. Tiger Data availability must not be a dependency.
2. Define versioned SQL setup and parameterized ingestion/query operations.
   Support one documented server-only authentication method appropriate to the
   supplied account. Do not expose tokens, credentials or arbitrary SQL to clients.
3. Compute a truthful comparison of happiness, safety, trust, resources, stress,
   cooperation/conflict and evacuation counts where available. Return both
   simulation IDs, revisions, endpoint ticks, lineage, exact source values/deltas
   and citations to existing event/decision records. Handle unequal horizons
   explicitly. Report descriptive associations; do not infer causation or claim
   statistical confidence from two runs.
4. Use a supported Snowflake AI/Cortex interface to explain the retrieved records
   for one question such as 'What recorded differences accompany lower cooperation
   in B?' Numeric facts come from queries/calculations, not model arithmetic.
   Bound context, output, timeouts, retry and cost/concurrency. Reject or label
   unsupported factual claims; if the provider fails, show an explicit unavailable
   or separately labeled deterministic comparison, never pretend it was Cortex.
5. Implement the extension router reserved in the shared handoff, with its own
   explicit DTO/OpenAPI schema. Pin revisions before any network request. Preserve
   auth, ownership, CSRF, error envelopes and write idempotency, including identical
   retries after response loss without duplicate ingestion/model charges. A new
   request body under a used key must conflict.
6. Add a small comparison UI/component and service-specific client/schema module.
   Reuse existing branch selection where practical; leave the existing comparison
   chart functional when Snowflake is disabled. Give A exact minimal wiring for
   the shared app/router, capabilities and UI entry point. Avoid editing core
   contracts, central service/config/locks or replacing shared frontend modules.

## Required executable tests and evidence

Implement S-01 through S-06 in the acceptance matrix. Test exact fixture deltas,
   unequal ticks, inherited branch IDs, missing records, repeat ingestion,
   idempotency/response-loss retry, invalid ownership and malformed provider output.
Assert that every cited ID resolves at the pinned revision and every displayed
number agrees with query results. Test outages/rate limits and a browser flow
that reaches the real application route through a controlled external fake.
Test SQL in a disposable schema with opt-in supplied credentials as well as mocked
failure paths; no production database cleanup or destructive DDL.

No paid calls in the default suite. Provide an explicit opt-in live smoke command
and sanitized evidence if account access is authorized/available. Report lack of
credentials as unverified live integration, not a passed test. No arbitrary
natural-language-to-SQL execution; use bounded approved query shapes for this
deadline.

Push the focused branch and write `docs/release/snowflake-handoff.md` with config
names, schema/API, exact tests, live status, remaining limitations and A's wiring
instructions. Append a shared dev-log entry without replacing earlier evidence.
