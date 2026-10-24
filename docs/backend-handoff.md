# AgentCity backend handoff

> Historical independent backend baseline. Frontend integration, shared Zod
> parity and browser/proxy checks are now complete. See the current
> [integration handoff](integration-handoff.md); its results supersede the old
> frontend absence and test counts below. Provider and storage limits still apply.

Contract: **1.0.0**. Built from the three supplied prompt files against an empty
application checkout. The standalone normative contract is preserved verbatim;
all three embedded copies were identical. Root README/frontend/deployment/CI
files were preserved. No deployment or external messaging was performed.

## Implemented and verified

| Milestone                   | Delivered evidence                                                                                                                                                                                                                                                   |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B0 — baseline               | `contracts/v1/CONTRACT.md`, manifest, DTO/stream schemas, OpenAPI and 32 shared valid/invalid fixtures; `docs/ownership.md` and `decisions.md`                                                                                                                       |
| B1 — live core              | FastAPI HTTP/WS, durable staged initialization, seeded 64×64 map, valid entrances/resources, A\*, autonomous rules, play/pause/step/speed and one bounded runner per world                                                                                           |
| B2 — explanation            | Profiles, needs/inventory/goals, local sight/hearing, bounded memory retrieval and summaries, directed social evidence, legal decisions, invitations/acceptance/decline/bounded dialogue, conserved trades/help and voluntary aid groups                             |
| B3 — complete scenario flow | Initial/random/repeat/custom/policy preview, pause hold, unique replaced-preview tokens, atomic pre-event snapshot/confirm, queued/active/resolved events, interval reports, outcome pause and prior-intent acknowledgment, restored-copy undo                       |
| B4 — management/history     | Exact revision reads, pinned pagination, snapshots/lineage/branch prefix independence, navigation saves, archive/delete, copied custom-profile versions, settings/shortcuts, overview, metrics and exhaustive JSON/CSV exports                                       |
| B5 — reliability            | Recovery/checksums/orphan-write faults, restart pause, persisted idempotency, single-writer process lock, shutdown commit join, owner/origin/CSRF checks, full-frame reconnect and slow-socket isolation, real Uvicorn smoke test, load measurements and demo traces |

All normative HTTP operations are present; a test compares the actual operation
set to the contract's endpoint table. Narration is the specified explicit 501.
Provider intentions pass through the same Game Master rules. Gemini has bounded
concurrency, request/token budgets, per-call timeout, at most one eligible retry,
backoff, circuit breaking, stale-generation/context rejection and rules fallback.
Nine separate versioned templates and exact internal proposal schemas/fixtures
are included; only persona/decision calls currently use Gemini. Core dialogue,
reflection, planning and social updates work deterministically without a model.

Internal checkpoints contain the full restorable state. A wire WorldFrame is
never used as a substitute. Branches inherit exact durable prefixes with new
simulation projections and stable entity IDs, and clear editor/provider/resume
work. A source can be deleted without breaking the copy. Replay reads stored
commits and makes no provider calls.

Citizen contexts exclude other citizens' private inventories, traits, goals and
memories. Current remote stock levels and hidden information-event labels are
not treated as citizen observations. Heard warnings retain sender/uncertainty
and use the recipient's subjective trust. All physical transfers/claims and
social deltas are checked at one commit boundary.

## Reproduce

From `backend/`, with the environment in `requirements.lock`:

```text
.venv/Scripts/python.exe -m pytest --junitxml=artifacts/test-results.xml
.venv/Scripts/ruff.exe check app scripts tests
.venv/Scripts/ruff.exe format --check app scripts tests
.venv/Scripts/python.exe -m scripts.contracts --check
.venv/Scripts/python.exe -m scripts.demo --data-dir artifacts/load-data/demo
.venv/Scripts/python.exe -m scripts.benchmark --steps 30 --live-ticks 10
```

The final suite reports **104 passed in 39.97 seconds**, with its JUnit report at
`backend/artifacts/test-results.xml`. Static analysis and formatting pass.
The contract check verifies **36 shared file hashes** plus
current DTO, HTTP OpenAPI and WebSocket schema equality; the supplied contract
bytes have not changed. Shared fixtures pass Python and JSON Schema acceptance/
rejection parity. Bootstrap schemas were corrected during initial validation
before any frontend consumer existed; normal regeneration is now refused.

Tests include a real one-worker Uvicorn process over loopback HTTP and WebSocket,
not only in-process tests. They run without provider credentials. The Windows
automation sandbox required local socket access and a writable TEMP/TMP; these
were test-environment constraints, not backend test failures left unresolved.

## Recorded demonstration and measurements

`backend/artifacts/demo-trace.json` contains the resolved flood report and
restored simulation ID. `request-response-trace.json` contains full real HTTP
write request/response bodies. The completed sequence is create → initial preview
confirm → queued event → physical steps → automatic outcome pause → measured
report → branch from the pre-event snapshot. The copy starts paused at tick zero;
the source history survives. These artifacts explicitly identify **rules mode**.

`backend/artifacts/performance.json` records a 30-manual-tick plus 10-live-tick
sample at each population with full-frame streaming enabled:

| Measurement                      | 30 citizens | 100 citizens |
| -------------------------------- | ----------: | -----------: |
| Initialization                   |      0.20 s |       0.32 s |
| HTTP control p95                 |       98 ms |       221 ms |
| HTTP single-step p95             |      164 ms |       376 ms |
| Tick compute p95                 |     12.5 ms |      58.4 ms |
| Durable commit p95               |     28.2 ms |      59.6 ms |
| Observed live ticks/second       |        1.88 |         1.84 |
| Retained disk after 59 revisions |     9.18 MB |     21.88 MB |

The default-population command target of p95 <200 ms is met in this sample.
Observed cadence is below the ideal two ticks/second; faster speed selections
can overload and the service reports achieved cadence. These are short local
measurements, not a guarantee or a 10,000-tick endurance result. All decisions in
this benchmark are rules, with zero provider calls and null estimated dollars.

## Remaining limitations and integration work

- **Live provider verification:** no Gemini key/account/model was supplied. The
  gateway is implemented and failure-tested with mock provider responses;
  a credential-dependent live smoke test remains. No invented default model,
  prices, usage or claim of live Gemini execution appears in the demo.
- **Optional adapters:** PostgreSQL/Tiger Data, Snowflake and ElevenLabs are not
  implemented. Capabilities advertise local persistence and false for analytics/
  narration; PostgreSQL configuration fails explicitly, narration returns 501.
- **Frontend/deployment verification:** no frontend source existed. React/Zod
  consumer parity, browser user flows, same-origin TLS proxy and a Vultr-hosted
  rehearsal remain for integration. Backend tests do not claim those checks.
- **Scale/retention:** every immutable compressed revision retains full internal
  audit history. Long 100-citizen runs need storage monitoring and future tested
  compaction/garbage collection. Logical deletion preserves objects. The full
  10,000-tick horizon and prolonged high-speed overload have not been load-tested.
- **Language/social scope:** scenarios use a bounded keyword compiler with exact
  previewed effects and unsupported notices. This is not unrestricted natural
  language physics. Rich model-generated dialogue, negotiation and other
  optional enrichment remain beyond the working deterministic core.
- **Usage availability:** missing provider token metadata makes the affected
  Usage query explicitly unavailable (503). Known metadata and conservative
  internal budget charges persist; no guessed token total or price is returned.

See `backend/README.md` for startup/seed/reset instructions, `rules.md` for units
and formulas, `operations.md` for storage/recovery/deployment, and
`docs/backend-contract-requests.md` for compatible interpretation details.
