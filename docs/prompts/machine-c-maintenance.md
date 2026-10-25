# Machine C implementation prompt

You are Machine C working on AgentCity. Implement the three maintenance fixes
below while preserving Machine A's merged security/provider fixes and Machine B's
scenario updates. Read `docs/reviews/dev-review-2026-10-24.md` and applicable
repository instructions before editing. Recheck the current code: the review
baseline is `5f87f9c`, not necessarily your current HEAD.

## Start and ownership

Fetch origin and start from the latest `origin/dev` on a new branch named
`codex/dependency-settings-deadlines`. Preserve existing user changes. If that
branch already exists, inspect it rather than resetting or overwriting work.

Machine B owns scenario interpretation, negation, region matching, physical
effect declarations, lesson fact/count calculations, and their tests. Its latest
observed commit is `9e68329793a06f03fc6654af5ec7c4a806bd9097` on
`origin/simulation-correction-fixes`. Check its current diff/status at execution
time. Do not merge or cherry-pick Machine B's work as part of this assignment.

Protected files include `backend/app/simulation/**`,
`backend/tests/test_domain.py`, and `backend/tests/test_simulation_correctness.py`.
Do not modify frozen `contracts/v1/**`. Do not change scenario catalogs, lessons
prompts, proposal schemas, or event/report payloads.

You may edit frontend dependency manifests/lockfiles, necessary frontend
validation consumers, `frontend/src/pages/Settings.tsx`, dedicated frontend tests,
`backend/app/infrastructure/gemini.py`, dedicated provider tests, and focused
handoff documentation. File ownership is not the only check: shared gateway
changes must also preserve Machine B's deterministic lesson behavior.

If a requested change requires modifying protected files, changes Machine B's
behavior, or produces an overlap you cannot resolve within these boundaries,
skip that portion and document the exact conflict. Continue all independent
safe work. Do not revert or rewrite either machine's commits. Do not expand
scope into garbage collection, scenario fixes, or broad browser-suite cleanup.

## 1. Update dependencies

Reproduce full and production-only frontend audits, examine applicable upstream
advisories, and upgrade vulnerable direct/transitive dependencies to maintained,
compatible releases. The review found seven affected packages (two critical,
four high, one moderate), with three high packages remaining under `--omit=dev`.
Counts and suggested versions may change; use current evidence.

Preserve the frontend's strict contract parsing, validation and routing. A Zod
major migration may require focused consumer changes; do not change frozen wire
contracts or backend simulation files to accommodate it. Avoid blanket
`npm audit fix --force`, removing validation, or suppressing advisory reports.
Document unresolved findings and exposure when a safe compatible fix is blocked.

Verify lockfile installation with `npm --prefix frontend ci`, frontend tests,
type checking/build, and both audit variants. Distinguish a package advisory
from a demonstrated exploit in AgentCity's enabled runtime modes.

## 2. Fix Settings operation lifecycle and retry behavior

Reproduce: change Pause shortcut to P, Save shortcuts, then Save and create a new
simulation. The reviewed build sends a new expected version under the completed
save's old idempotency key and receives 409 `IDEMPOTENCY_CONFLICT`.

Make successful saves end their operation and give subsequent distinct saves
fresh keys. Preserve ambiguous-response retries with the exact original key and
body/expected version. A fix that merely changes every retry key is incomplete.
Do not weaken backend idempotency or control-version validation.

Add normal regression tests for successful Save shortcuts -> Save and create,
ambiguous-response retry without duplicate mutation, and interaction with queued
appearance saves. The historical diagnostic under docs deliberately asserts the
old 409; use it as reproduction evidence and add acceptance coverage asserting
the corrected successful behavior. Keep tests independent of previous cities
and display preferences.

## 3. Bound optional lesson provider calls

`Gateway.lessons()` calls `structured()` without the wall-clock deadline used by
decisions and scene generation. Add a finite overall budget covering queueing,
credential acquisition, HTTP attempts and backoff, with fallback to existing
deterministic lessons. Limit implementation to provider infrastructure and
dedicated provider tests. Preserve existing lesson inputs, outputs, adoption,
facts/counts, and scenario behavior.

Preserve Machine A's cancellation-safe persisted usage accounting, budget
reservations, stream authorization, context freshness, and existing decision and
scene deadlines. Release concurrency slots and ensure later calls can proceed.
Do not assume cancelling `asyncio.to_thread` stops its underlying worker. Avoid
real vendor calls; mocks can reproduce queue/auth/HTTP stalls and cleanup.

If the provider fix cannot be made without modifying Machine B's protected
files or semantics, defer only this conflicting portion and finish dependencies
and Settings. Explain what prevented the deadline fix.

## Validation and delivery

Run appropriate focused tests while implementing, then `npm test` and
`npm run build`. Run focused browser acceptance tests and the broader browser
suite when feasible, reporting known unrelated failures separately. Run
`npm --prefix frontend audit --json` and the `--omit=dev` variant. Verify that
frozen contract files and protected simulation files have no changes in your
branch diff. Recheck origin and Machine B's branch before delivery.

Make a focused implementation commit on your branch and push that branch to
origin. Do not push implementation changes directly to dev or force-push. Report
the branch/commit, files changed, tests and audit results, remaining risks, and
any skipped overlap. Do not claim a full suite is green if tests still fail.
