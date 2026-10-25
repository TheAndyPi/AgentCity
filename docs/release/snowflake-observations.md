# Snowflake observations

AgentCity observes committed history asynchronously. The local revision journal
remains authoritative; Snowflake is a rebuildable analytical read model. Existing
two-history comparisons retain their original table, endpoint and response.

## Enable

1. Configure the server-side key-pair credentials described in
   [Snowflake setup](snowflake-handoff.md#configuration-and-database-setup).
2. As the schema owner, run `backend/app/snowflake/sql/003_observations.sql`
   in the explicitly selected database/schema. Runtime does not run DDL.
3. Grant the service role database/schema/warehouse USAGE, and SELECT, INSERT
   and DELETE on the new observation tables, plus SELECT on their views.
4. Set these values in `backend/.env` and restart:

   ```dotenv
   SNOWFLAKE_OBSERVATIONS_ENABLED=true
   SNOWFLAKE_OBSERVATION_POLL_SECONDS=30
   ```

The observation switch defaults to false and is independent of
`SNOWFLAKE_ENABLED`, which enables the existing comparison feature. Credentials
are required when either feature is enabled. Poll intervals may be 1–300 seconds.
Use one backend worker and a dedicated warehouse/schema for the deployment.
Keep key material outside Git. Configure warehouse auto-suspend and resource
limits according to the operator's budget.

Open a city and choose **Simulation overview → Observations**. Citizen and event
panels provide scoped links. The same drawer in saved history pins observations
to its selected revision. Existing local reports remain available while
observations are disabled or the warehouse is unavailable.

## What is measured

The projection records agent stats and life state, existing directed relationship
scores/kinds, recorded information and class beliefs, social norms, event
lifecycle, and before/after changes. Private memories and provider prompts are
excluded. Missing source evidence remains missing; observation does not invent
opinions, relationships or causal links.

Agent community trust and directed relationship trust are separate measures.
A trusting B never establishes B's trust in A. Unknown relationships do not
create rows. Units and denominators accompany metrics. Empty populations yield
unavailable means. Historical dead agents remain inspectable, while living-agent
means exclude dead/inactive citizens.

Cooperation and conflict action counters are cumulative citywide totals. They
cannot be filtered to one citizen; the interface switches to Health when a citizen
is selected from one of those measures, and the API rejects that ambiguous query.

Events retain an internal baseline immediately before activation effects. Reports
compare it with resolution and up to 30 subsequent physical ticks. Pausing does
not advance that window. Cohort survival accompanies survivor means. Explicit
event references are distinguished from changes that merely occurred during the
event, and reports identify overlapping events. These are observations, not
estimates of causal effect or statistical significance.

## API

The session-authorized extension prefix is:

`/api/v1/integrations/snowflake/observations/v1/simulations/{sid}`

| GET route | Result |
| --- | --- |
| `/status` | Enablement, ingestion progress, coverage and errors |
| `/metrics` | Metric identifiers, units and denominator definitions |
| `/trends` | Revision-pinned bucketed time series and event markers |
| `/events` | Event summaries |
| `/events/{event_id}` | Baseline, resolution, follow-up and cited observations |
| `/changes` | Paginated changes and their evidence |

Historical data queries require `through_revision`; filters select tick intervals
and applicable agents/events. Graph queries return at most 500 buckets. Changes
default to 50 records and are capped at 100 per page. The response reports the
requested revision, effective ingested revision and complete/partial/unavailable
coverage. Results are explicitly identified as Snowflake results. No caller SQL
is accepted, and owner identity comes from the server session.

Bucket means average the recorded per-tick values with equal tick weights;
min/max show the range of those values. Samples count recorded ticks. The trend
table's maximum denominator is the largest contributing group in the bucket;
event snapshots provide metric-specific city and cohort denominators separately.
The [observation OpenAPI document](snowflake-observations-openapi.json) describes
the independently versioned request and response shapes.

## Recovery and rollout

The worker backfills retained revisions and saves progress separately from core
storage. Uploads are bounded by fact count and payload size. Only verified,
complete revisions are queryable. A lost checkpoint causes idempotent replay;
warehouse failures do not roll back or pause physical simulation. A conflicting
content hash is an integrity error rather than an overwrite.

Branch histories include inherited records once, with lineage provenance. Queries
cannot read beyond the requested revision. Deleting a simulation immediately
revokes application access and queues warehouse cleanup; retries resume after
warehouse recovery.

## Verification

From the repository root, `npm test` checks frontend and backend tests, frozen
contracts and Ruff; `npm run build` builds the production interface. The focused
browser commands, run from `frontend/`, are:

```sh
node node_modules/@playwright/test/cli.js test e2e/observations.spec.ts
node node_modules/@playwright/test/cli.js test --config playwright.observations.config.ts
node node_modules/@playwright/test/cli.js test --config playwright.snowflake.config.ts
```

The first covers real disabled status, explicitly labeled warehouse UI fixtures
and historical pins. The second uses the real application, journal and worker
with an offline warehouse transport and compares API values with rendered graph
and table values. The third preserves existing comparison browser coverage.

For opt-in live SQL verification, first provision the migration in a dedicated
schema whose name starts with `AGENTCITY_OBSERVATION_SMOKE_`. Load server
credentials into the environment, then run from `backend/`:

```sh
.venv/Scripts/python.exe -m scripts.snowflake_observations_smoke --live --schema AGENTCITY_OBSERVATION_SMOKE_TEST
```

On other systems use `.venv/bin/python`. The script performs real, potentially
billable SQL calls, verifies a disposable committed city, pinned values, repeated
ingestion and event evidence, then deletes only its own owner/simulation rows.
It performs no DDL or Cortex calls. A passing offline test or successful build
does not substitute for this live verification.

Verified on 2026-10-25: the full backend suite passed **630 tests, 2 skipped**;
frontend unit/contract tests passed **195 tests**; the three observation UI cases,
one real worker/API browser case and three existing comparison browser cases
passed. The additional citywide-counter filter regression passed separately.
TypeScript, production build, Ruff and all 43 frozen core contract hashes passed.
The live Snowflake smoke was not run and the production migration was not applied.

Default verification uses explicit fake transports and makes no paid calls. A
passing fake test does not establish that operator grants or live SQL execution
work. Live verification must use the opt-in smoke script and a dedicated test
namespace; production migration is an operator action.

Disable `SNOWFLAKE_OBSERVATIONS_ENABLED` and restart to stop ingestion without
affecting the simulation or existing local reports. Retained journal history can
be backfilled when re-enabled.
