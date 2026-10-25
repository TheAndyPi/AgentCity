# Machine C maintenance handoff — 2026-10-24

Base: `adf6295` (`origin/dev`). Implementation branch:
`codex/dependency-settings-deadlines`. The original checkout's uncommitted
dependency manifests and test results were preserved by using an isolated worktree.

## Dependencies and exposure

The full baseline audit reproduced seven affected packages (two critical, four
high, one moderate). The production-only audit reproduced three high packages.
The replacement lockfile uses React Router DOM/Router 7.18.4, Zod 4.6.7,
Vite 7.3.7 and Vitest/@vitest/mocker 4.1.12. The vulnerable tinypool dependency is
no longer in the dependency tree. These patched release lines preserve the
project's Node >=22.12 requirement and existing Vite configuration. Node type
declarations 24.19.2 are explicit development dependencies: the clean baseline
build otherwise failed on its existing Node imports and `process` references.

Both final audit variants report **zero vulnerabilities**. Raw before/after
reports are in [the evidence directory](evidence/machine-c-2026-10-24/).
No audit suppression, forced bulk fix, or validation removal was used.

Relevant upstream evidence and application exposure:

- [Vite Windows file-deny bypass](https://github.com/vitejs/vite/security/advisories/GHSA-93m4-6634-74q7)
  requires a Windows dev server exposed to the network. AgentCity's launcher
  binds to loopback. Later [Windows editor-path issues](https://github.com/vitejs/launch-editor/security/advisories/GHSA-587h-7wmj-h5pm)
  require Vite 7.3.7 rather than the historical 7.1.11 minimum. These are development
  server features; production serves the static build through the backend.
- [Vitest UI/API file access](https://github.com/vitest-dev/vitest/security/advisories/GHSA-5xrq-8626-4rwp)
  concerns exposed UI/API or Windows browser mode. AgentCity runs `vitest run`.
  The later [redirect mock](https://github.com/vitest-dev/vitest/security/advisories/GHSA-82fw-gwwq-j7x9)
  and [manual mock registration](https://github.com/vitest-dev/vitest/security/advisories/GHSA-qxg6-89mg-rqv8)
  fixes require the updated mocker; AgentCity does not install those plugins in
  its application server. The [tinypool advisory](https://github.com/tinylibs/tinypool/security/advisories/GHSA-85c8-ppgw-ccpr)
  requires prototype pollution and affected worker options. No such exploit was
  demonstrated in AgentCity.
- [Router redirect XSS](https://github.com/remix-run/react-router/security/advisories/GHSA-2w69-qvjg-hvjx)
  excludes declarative BrowserRouter mode, which AgentCity uses. SSR/RSC/server
  action findings likewise do not establish exposure in this client-rendered app.
  Later [untrusted-path redirects](https://github.com/remix-run/react-router/security/advisories/GHSA-wrjc-x8rr-h8h6)
  required upgrading beyond the original redirect fix. No application exploit
  was demonstrated.
- [Zod collection resource exhaustion](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5)
  and the [upstream bounds-check fix](https://github.com/colinhacks/zod/commit/a0ebf970f2d752e5f58527cd2942ff48be4f46bd)
  concern parsing oversized malformed collections. The browser validates API and
  fixture data; this is not evidence of a remotely exploitable Python server
  vulnerability. Upgrade to the patched v4 parser preserves all strict object
  boundaries and the frozen contract. Consumer generics were updated, and the
  exact v1 UUID pattern is retained because v4's `uuid()` adds variant restrictions.

## Settings operations

The historical browser diagnostic reproduced the old successful-save → 409
sequence before implementation. It remains unchanged outside normal discovery.

Settings now keeps a serial operation queue. The key and normalized settings,
including the expected version, are captured together when an operation first
sends. Success removes the operation. Connection failures, non-JSON responses,
and invalid success envelopes preserve the exact request for replay. Queued
appearance changes are applied after that replay with successive returned
versions, while remaining visible optimistically. Definitive stale-version
responses refresh the saved version and retain the user's shortcut draft for
an explicit retry. Backend idempotency and version checks are unchanged.

Normal browser coverage asserts fresh keys after success, replay without a second
mutation for all three ambiguous-response forms, appearance saves both before
and after shortcut saves, and stale-version recovery. Each test resets its own
preferences and shortcuts, restores the preceding preferences afterward, and
creates no cities.

## Optional lessons

The original mock diagnostic reproduced the unbounded authentication wait and
occupied semaphore slot. Lessons now have one overall deadline of
`min(10 seconds, 2 * llm_timeout + 0.25 seconds)`, covering queueing, credentials,
HTTP attempts, retry backoff and delivery. Timeout returns `None`, preserving the
existing deterministic lessons and adoption path. Decision and scene deadlines
are unchanged.

Vertex callers share one shielded credential worker until it actually finishes.
Cancelling an await does not stop a running thread; a timed-out worker may
continue using its independent, HTTP-timeout-bounded requests session. New callers
wait for that same worker within their own budget instead of starting overlapping
credential writers. Usage tasks retain Machine A's cancellation-safe accounting,
conservative unknown-usage charges and shutdown drain before client/repository
closure. Deadline and external-cancellation tests exercise these guarantees with
mocks; no vendor requests were made.

## Validation

- `npm --prefix frontend ci`: passed from the updated lockfile.
- `npm test`: passed, including 273 backend tests, the original 131 frontend
  tests, Ruff lint/format and all 43 frozen contract hashes/snapshots.
- Final frontend run after the UUID compatibility regression was added:
  144 tests passed; TypeScript passed. The production build passed.
- Eleven new dedicated provider tests cover queue, async auth, HTTP and usage
  stalls; retry backoff; external cancellation; surviving credential threads;
  conservative accounting; later successful calls; unchanged deterministic
  lessons and continued physical ticks.
- The standalone provider diagnostic now reports
  `lessons_pending_after_budget=false` and `slot_occupied=false`, where the
  original baseline reported both true. See
  [the final probe](evidence/machine-c-2026-10-24/provider-deadline-after.json).
- Focused Settings acceptance: seven tests passed on a fresh store.
- Initial broader browser run: 10 passed, 16 failed. Six assertion failures
  preceded a Windows Vite `EBUSY` watcher crash on a generated screenshot;
  the remaining ten failures were connection refusals after that crash,
  including the seven Settings tests. This run is not green. See
  [the summary](evidence/machine-c-2026-10-24/browser-initial-summary.json).
- Full rerun with test-only `CHOKIDAR_USEPOLLING=1`: **18 passed, 8 failed**,
  including all seven Settings tests passing with their preference cleanup.
  Polling avoided the screenshot watcher crash; no application configuration
  was changed. See [the final summary](evidence/machine-c-2026-10-24/browser-polling-summary.json).
  The eight failures match the review's deferred browser maintenance findings:
  the old setup heading, two old opening-scenario labels, `CITY PAUSED`,
  `Delete all archived`, a road-only assertion, the subsequent city's zero-tick
  wait (consistent with the earlier failure retaining the only run slot), and
  a missing 3D character marker under inherited display preferences. These
  remain unresolved; the full browser suite is not green.

## Changed files

- `frontend/package.json` and `frontend/package-lock.json`: patched dependencies
  and explicit Node types.
- `frontend/src/api/client.ts` and `frontend/src/api/schemas.ts`: Zod v4 type
  compatibility and the existing v1 UUID rule.
- `frontend/src/pages/Settings.tsx`: operation queue, retry snapshots and stale
  version recovery.
- `backend/app/infrastructure/gemini.py`: lesson deadline and shared credential
  refresh lifetime.
- `frontend/e2e/settings.spec.ts`,
  `frontend/tests/dependency-validation.test.ts` and
  `backend/tests/test_lesson_provider_deadlines.py`: dedicated acceptance and
  regression tests.
- This handoff and its audit, provider-probe and browser-summary evidence.

## Integration boundaries

Machine A's `2c39cdb` remains an ancestor. Machine B initially ended at
`9e68329793a06f03fc6654af5ec7c4a806bd9097` on
`origin/simulation-correction-fixes`, with only the five protected files described
in the review. The final fetch found **`fceecf9301e4163b2a2fe15876472e8fdfed052e`**
on that branch; `origin/dev` remained `adf6295`. Its new scenario interpretation
work touches 13 files, including gateway imports and a separate `interpret()`
method. Neither Machine B commit was merged or cherry-picked, and its combined
scenario behavior was not executed in this assignment.

A read-only three-way file preview found one existing Machine A/Machine B import
conflict in `gemini.py`. The same conflict appears with unmodified `origin/dev`,
so it is not introduced by Machine C. When integrating Machine B, retain both
`from app.simulation.navigation import distance, line_of_sight` and
`from app.simulation.scenario_scene import CATALOG`, plus its
`ScenarioInterpretation` import. The preview found no conflict in the lesson,
authentication or structured-accounting methods. See
[the compatibility evidence](evidence/machine-c-2026-10-24/machine-b-compatibility.json).
No assigned portion was deferred: the maintenance changes stay within the
gateway and do not alter Machine B's lesson facts, counts or adoption.

Frozen `contracts/v1/**`, all `backend/app/simulation/**`, `test_domain.py` and
`test_simulation_correctness.py` have no implementation diff. No scenario catalogs,
prompt files, proposal schemas or event/report payloads changed in this branch.

Retention, endurance, broad browser-suite cleanup and unavailable optional
integrations remain separate work as described in the original review.
