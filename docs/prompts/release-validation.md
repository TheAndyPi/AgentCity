# Final maintenance and functional validation prompt

Act as AgentCity's release validator after the three integration branches land.
Verify actual execution; do not assume a green branch report applies to the
merged application. Read `docs/dev-log.md`, `docs/release/integration-handoff.md`,
`docs/release/acceptance-cases.md`, the service handoffs and applicable instructions.

## Preparation

Fetch current dev, record full SHA and clean/dirty state, inspect ancestry of
Machine A security, B scenario, C maintenance, skyline and new integration commits.
Use `codex/release-validation` from latest dev for any test corrections. Preserve
other work. All stores must be disposable, ports unique, and optional vendor
calls disabled by default. Never reset user DATA_DIR, remove referenced objects,
change live account/IAM/billing or invoke paid providers as an incidental unit test.
Do not expose secret values while checking which configuration is available.

Baseline maintenance evidence was collected before the final `560e2ed` merge.
Run its tests on your exact tree. Historical docs diagnostics assert old bugs;
do not count those as acceptance tests or copy their incorrect expectations.

## Execute and repair the test harness

1. Clean dependency installation: `npm --prefix frontend ci`; install the backend
   runtime from its tested lock in an isolated environment if needed. Record Node,
   Python and browser versions. Do not unnecessarily rebuild another machine's
   active environment.
2. Run `npm test`, `npm run build`, `npm --prefix frontend audit --json`, and
   `npm --prefix frontend audit --omit=dev --json`. The root test already includes
   TypeScript, frontend tests, backend tests, contracts and Ruff. Report all
   failures rather than a single misleading top-level pass.
3. Run focused Settings, deadline, security/context and new T/S/N integration
   cases, followed by `npm run test:e2e` on the built candidate. On Windows use
   test-only `CHOKIDAR_USEPOLLING=1` if needed for the documented Vite watcher
   failure; record that condition. Use installed Chrome or explicitly configured
   Playwright browser and collect traces/failing contexts.
4. Repair stale test selectors based on current rendered accessible names, isolate
   view mode/reduced-motion/preferences, set population explicitly and clean up
   cities in `finally` even on test failure. New setup supports population 10-100;
   don't restore old fixed-population text assertions. Road preference is not a
   rule that all legal destinations are roads: assert legal movement, entrances,
   speed bounds and no forbidden crossings. Keep those behavioral checks.
5. Add missing executable functional cases from the acceptance matrix. Use real
   public HTTP routes and browser flows with controlled external fakes; helper
   tests alone do not validate middleware, ownership, wiring, envelopes or UI.
   Never delete assertions, suppress whole failing suites, weaken schemas or
   regenerate frozen core contracts just to pass.

## Validate product execution

Execute R-01 through R-08 and T/S/N/M cases. Rehearse: create city -> accepted
Gemini/rules decisions -> flood preview/commit -> outcome -> recorded comparison
and evidence -> narration playback -> branch/export -> restart. Verify exact
numeric consistency across API state, CSV, external rows and displayed results.
Check that inherited branch IDs, revision pinning and deletion preserve history.

Validate sessions, origin/CSRF, ownership, socket logout/expiry/backpressure, new
child-route exception/validation envelopes, media access, idempotent retries and
bounded external calls. While each vendor is blocked, controls must remain
responsive and local committed state valid. Check that capability flags match
implemented enabled features, and no offline result pretends to be a vendor call.

Opt-in live vendor and hosting verification uses supplied authorized access and
disposable resources. If a real call may bill and access is not already authorized,
finish all offline validation and ask for the precise required access/approval.
Unavailable credentials are a blocked/unverified live check, not a passed feature.
Do not claim all services work from mocked tests. Check actual audio load/playback,
Snowflake SQL/AI provenance and Tiger rows at exact source revisions.

## Release report

Write `docs/release/validation-report.md` and append `docs/dev-log.md`. Include:

- exact application SHA, tested environment/config modes and integrated branches;
- case ID -> executable test/command -> result/evidence, with pass/fail/blocked/
  unverified kept distinct;
- totals for every suite, audits, exact remaining failures and reproduced impact;
- performance/soak measurements and deployment/backup/rollback rehearsal evidence;
- secrets-safe real-vendor status and prerequisites still missing;
- release recommendation: ready for the declared bounded demo scope, or not ready
  with specific blockers/owners. Do not label a narrow smoke pass a full sign-off.

Commit/push focused test repairs to the validation branch and report integration
instructions to A. If production source behavior is broken, add a meaningful
failing regression and report the owner; make a minimal fix only within your
authorized scope. Source/scenario changes must not be disguised as test cleanup.
