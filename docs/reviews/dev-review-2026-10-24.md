# Dev review and implementation handoff — 2026-10-24

Reviewed application commit: `5f87f9c` on `dev`. This is a dated review, not a claim
that every finding remains open on a later checkout. The handoff adds documents,
diagnostic reproductions, and evidence only; it does not implement application fixes.

The next implementation assignment is [Machine C](../prompts/machine-c-maintenance.md).
Machine B owns scenario semantics and lesson fact calculation. Retention and broad
browser-suite repairs are separate work, outside Machine C's assignment.

## Integration status and ownership

`dev` includes Machine A's security/provider commit `2c39cdb` and Machine B's
initial simulation corrections and community lessons (`cfb1bc3`, `eb8cd71`).

At handoff preparation, fetching origin revealed Machine B's newer commit
`9e68329793a06f03fc6654af5ec7c4a806bd9097` on
`origin/simulation-correction-fixes`. It is not yet an ancestor of reviewed `dev`.
Its diff addresses list negation, unique citizen counts, construction synonyms,
and whole-word region matching. These changes were inspected but not executed
as part of this review. Do not describe them as verified merged fixes.

Machine B's latest commit changes exactly these files:

- `backend/app/simulation/scenario_scene.py`
- `backend/app/simulation/scenarios.py`
- `backend/app/simulation/lessons.py`
- `backend/tests/test_domain.py`
- `backend/tests/test_simulation_correctness.py`

Machine C must leave these files and all other scenario semantics untouched.
Its gateway deadline change may affect how long optional prose generation waits,
but must preserve the existing deterministic lessons and adoption semantics.
Compare commits from their merge base: a direct comparison of the scenario branch
against dev includes Machine A files that branch never contained. Do not replace
dev files with an older branch's versions to resolve that apparent difference.

## Findings assigned to Machine C

### C-1 — Dependency security maintenance

The frontend npm audit snapshot reports seven affected packages: two critical,
four high, and one moderate. Omitting development dependencies reports three
high affected packages: `react-router`, `react-router-dom`, and `zod`.
These are package-level advisory results, not seven demonstrated application
exploits. Evaluate reachable features and distinguish development tooling from
deployed application code.

The reviewed direct versions include React Router DOM 7.9.4, Zod 3.25.76,
Vite 7.1.9, and Vitest 3.2.4. Audit-suggested versions are only a snapshot;
recheck maintained releases and compatibility when implementing. In particular,
do not blindly force a major Zod update or alter the frozen API contract to make
an update compile.

Evidence:

- [Full npm audit](evidence/dev-2026-10-24/npm-audit.json)
- [Production dependency audit](evidence/dev-2026-10-24/npm-production-audit.json)
- [Vite Windows file-deny advisory](https://github.com/vitejs/vite/security/advisories/GHSA-93m4-6634-74q7)
- [Vitest UI/API advisory](https://github.com/vitest-dev/vitest/security/advisories/GHSA-5xrq-8626-4rwp)
- [React Router redirect advisory](https://github.com/remix-run/react-router/security/advisories/GHSA-2w69-qvjg-hvjx)

The Vite advisory has Windows/network-exposure prerequisites. The reviewed root
dev launcher binds Vite to loopback, and the normal test command uses Vitest run
mode rather than its UI/API server. SSR-only advisories must not be presented
as confirmed vulnerabilities in this client-rendered application.

Acceptance criteria:

1. Update compatible direct/transitive dependencies and the frontend lockfile.
2. Preserve runtime parsing, validation boundaries, strictness, routes, and
   frozen contract bytes. Use focused consumer changes only when required.
3. Verify a clean lockfile install, type checking, frontend tests and build;
   rerun both audits and explain remaining findings with exposure and fix status.
4. Any change needed in Machine B-owned files is deferred and reported; do not
   silently weaken validation or remove coverage to obtain a clean audit.

### C-2 — Settings save reuses a completed operation key

Location: `frontend/src/pages/Settings.tsx`, `shortcutsKey` and `save()`.

Reproduce in one visit to Settings:

1. Change Pause shortcut from Space to P.
2. Click **Save shortcuts**; PUT settings succeeds with HTTP 200.
3. Click **Save and create a new simulation**.
4. A new PUT settings body contains the updated version, but reuses the earlier
   idempotency key. The backend returns HTTP 409 `IDEMPOTENCY_CONFLICT`, and the
   page remains on Settings.

A real browser/API reproduction passed while asserting that incorrect behavior.
The [diagnostic browser spec](reproductions/settings-save-conflict.spec.ts) records
the current bug; it is deliberately outside normal test discovery. It is not an
acceptance test that should continue to assert 409 after the fix.

Acceptance criteria:

1. A successful save ends its operation; a subsequent distinct save gets a new
   key. Save shortcuts followed by Save and create navigates successfully.
2. A retry after an ambiguous/lost response reuses both the original key and
   original normalized body, including its expected version. Merely rotating
   every key on every click would break durable retry semantics.
3. Appearance autosaves, shortcut edits, stale-version handling and navigation
   keep working. Do not change backend idempotency rules to hide this UI bug.
4. Add a normal browser regression test for the successful sequence and a
   meaningful ambiguous-response retry test.

### C-3 — Optional lesson calls lack an overall provider deadline

Location: `backend/app/infrastructure/gemini.py`, `Gateway.lessons()`.

Citizen decisions have an outer wall-clock timeout; scene generation has its
own outer timeout. Lessons call `structured()` without an outer timeout.
Per-HTTP-operation timeouts do not bound the whole queue/authentication/retry
path. A stalled credential stage can retain a concurrency slot beyond the
intended operation budget.

Mock-only reproduction: with request timeout 0.05 seconds and one slot, block
`headers()` on an asyncio event. The decision deadline is 0.35 seconds. A lesson
call is still pending and owns the slot after about 0.56 seconds; the equivalent
decision call falls back after about 0.35 seconds. No live provider is called.
See [probe results](evidence/dev-2026-10-24/probes.json) and the
[standalone diagnostic](reproductions/provider-deadline.py).

Acceptance criteria:

1. Bound the entire lesson operation, including queueing, authentication,
   request attempts, backoff, and delivery, with an explicit finite budget.
2. Timeout retains already available deterministic lessons and physical ticking;
   it must not change lesson facts, schemas, prompts, or scenario outcomes.
3. Preserve existing decision and scene deadlines, semaphore release,
   cancellation-safe usage accounting, conservative budget charges, and shutdown
   ordering. Cancellation of an await does not stop an already running thread.
4. Add mocked regression coverage for queue/auth stalls, HTTP stalls, timeout
   fallback, cancellation cleanup, usage durability, and a subsequent successful
   request. No real paid calls are required for verification.

## Other findings, outside Machine C's assignment

### R-1 — Logical deletion does not reclaim historical objects

`backend/app/data/repository.py` removes the simulation's manifest references but
does not garbage collect compressed revision objects. A disposable city returned
HTTP 200 from DELETE and HTTP 404 on later GET while retaining all 11 objects,
835,122 object bytes before and after. The UI calls this permanent deletion.
This is an existing documented storage limitation, not a newly proven remote
security exploit. Retention/garbage collection needs separate design, preserving
objects referenced by branches. Do not implement it under Machine C's scope.

### R-2 — Browser regression suite needs maintenance

The unmodified suite produced 11 passes and 8 failures out of 19. Findings include
outdated setup/editor/outcome/delete labels, shared 2D/3D and reduced-motion
settings, a failed running-city test leaving the single run slot occupied, and
road-only assertions that reject supported lawn access/building visits.

Temporary probes with current labels and explicit display settings passed:

- Create city, initial flood, live stream, inspector, outcome, undo, and history.
- Running editor pause/cancel and prior running-intent restoration.
- Composed 3D scenario preview, activation, reload persistence, and resolution.
- Walking into and out of a building with 3D and reduced motion disabled.

Do not remove assertions wholesale or call the unmodified suite green. Machine C
may add/fix its focused Settings tests; broad suite cleanup is separate work.

### R-3 — Scale and endurance remain limited

Short rules-mode benchmark: 30 manual ticks plus 10 live ticks, 59 stored
revisions per population. These results are local measurements, not service
guarantees or a 10,000-tick endurance rehearsal.

| Measurement          |  30 citizens | 100 citizens |
| -------------------- | -----------: | -----------: |
| HTTP single-step p95 |       196 ms |       403 ms |
| HTTP control p95     |       114 ms |       264 ms |
| Live cadence         | 1.88 ticks/s | 1.85 ticks/s |
| Retained store size  |      9.14 MB |     21.03 MB |

Default target cadence is 2 ticks/s. Every revision retains full growing internal
audit history; sustained disk/memory/latency behavior needs further work.
See [benchmark evidence](evidence/dev-2026-10-24/performance.json).

### R-4 — Optional integrations and live verification

PostgreSQL/Tiger Data, Snowflake, and ElevenLabs remain unavailable and are
advertised as such. This review used rules mode and mocked provider behavior;
it did not make live Gemini calls. These limitations do not establish a new
regression in the security/provider fixes already merged into dev.

## Scenario findings delegated to Machine B

On reviewed `5f87f9c`, HTTP previews still made a fire from **No flood or fire
today** and a flood from **There will not be a flood**. **Create a new building
in the north** missed the specific construction notice. Repeated evacuation
actions could overcount people in a lesson. Machine B's later `9e68329` targets
these issues, as described above. Recheck after its integration; do not duplicate
that work in Machine C's branch.

## Baseline verification

- Backend: 262 tests passed, no failures or skips.
- Frontend: 131 tests passed; TypeScript and production build passed.
- Ruff lint/format and the contract check passed; 43 shared hashes matched.
- Browser suite and targeted checks are reported separately above.
- All reproductions used isolated disposable stores, with no live vendor calls.

To run the historical Settings diagnostic from repository root in PowerShell,
copy it into the Playwright test directory temporarily, then remove that exact
copy. Its success means the old bug was reproduced, not that Settings is fixed:

```powershell
$taskProbe = 'frontend/e2e/__review_settings_save_conflict.spec.ts'
if (Test-Path -LiteralPath $taskProbe) { throw 'Probe path already exists' }
Copy-Item -LiteralPath docs/reviews/reproductions/settings-save-conflict.spec.ts -Destination $taskProbe
try {
  Push-Location frontend
  try {
    node node_modules/@playwright/test/cli.js test __review_settings_save_conflict --reporter=line
  } finally {
    Pop-Location
  }
} finally {
  Remove-Item -LiteralPath $taskProbe
}
```

Run the provider diagnostic with the backend virtual environment's Python:

```powershell
backend/.venv/Scripts/python.exe docs/reviews/reproductions/provider-deadline.py
```

For implementation checks, use `npm test`, `npm run build`, focused Playwright
tests, and `npm --prefix frontend audit --json` plus its `--omit=dev` variant.
Do not claim known unrelated browser failures were fixed by this handoff.
