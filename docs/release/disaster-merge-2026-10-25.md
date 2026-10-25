# Disaster merge verification — 2026-10-25

Integrated `origin/codex/disaster-controls-damage` at `0d60ed5269ab3fe4201dcda4f42a01002b0c74ef`
onto current dev `dda07af35ed42c47bda71fda3b2409339d94113a`. The user explicitly requested
this previously excluded branch and authorized restarting the local application.
Read both disaster controls/audio handoffs and the shared development log.

Normal merge `5fc0083` preserves both histories. Integration correction `5f9575c`
composes scenario funding/closures with persistent structural integrity. Browser
readiness correction `664df38` waits for the actual renderer and citizen meshes
before projecting the real camera position and clicking.

## Integration behavior

Preserved current scenario interpretation, survival/crisis, physical rescue and
care, class/personality behavior, live voices and crowd movement. Building and
citizen condition types remain distinct. Physical hazards apply canonical injury
once before care; fatal boundaries cannot be healed away, unconscious citizens
cannot react, trapped actors cannot move/rescue, and unsafe buildings release
care claims at actual locations. Independent temporary service controls compose
with damage and funding instead of restoring stale capacity or reopening shops.
Eleven new regression cases cover these cross-feature boundaries.

Geometry is rounded to nine decimal places in meters and clamped to map bounds;
only the versioned disaster fixture changed. Frozen core v1 remains unchanged.

## Executed verification

| Gate | Result |
| --- | --- |
| Final root npm test | 184 frontend passed; 538 backend passed, 2 opt-in SQL skips; backend 439.24 seconds |
| Disposable PostgreSQL 18 TLS | 2 passed, 19 deselected; restricted role; both migration versions and upserts executed |
| Frozen core | All 43 hashes plus DTO/OpenAPI/stream checks match |
| Ruff lint / format | Passed; 142 Python files formatted |
| Production TypeScript / Vite build | Passed; existing upstream annotation warnings |
| Core browser | 28 passed, no flakes or skips |
| Narration / disaster browser | 8 passed with controlled valid decoded media |
| Behavior browser | 4 passed |
| Snowflake browser | 3 passed using controlled transport |
| Browser total | 43 passed |

The first full backend run had 533 passes and two failures: hospital funding was
lost during capacity derivation and scenario shop closures were reopened. Both
were fixed and the entire suite rerun. One final core browser run had 27 passes
and a renderer initialization race in its selection helper; the helper was fixed
without bypassing production selection, and the entire 28-case suite rerun.
An earlier focused fixture failure exposed insignificant trig precision noise;
canonical geometry precision fixed it. Initial failures are retained with final
evidence rather than represented as green runs.

## Measured local performance

Disposable rules-mode stores; 10 manual steps and 5 live ticks per population.
These short samples measure baseline durability, not disaster endurance or vendor latency.

| Citizens | HTTP step p95 ms | Control p95 ms | Live ticks/s | Compute p95 ms | Commit p95 ms | Persisted bytes |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | 101.0 | 74.2 | 1.84 | 9.5 | 17.0 | 3,443,490 |
| 30 | 195.3 | 144.9 | 1.80 | 38.9 | 28.0 | 5,702,254 |
| 100 | 664.9 | 286.8 | 1.52 | 394.7 | 61.3 | 13,995,879 |

Sanitized JUnit, browser JSON/screenshots, initial failures and benchmark JSON are
preserved in the original checkout's ignored
`backend/.tmp/disaster-merge-2026-10-25/`. Generated baseline artifacts were restored.
The original checkout's unrelated local README edits are preserved separately from this merge.

## External boundaries

No paid provider, live Tiger/Snowflake account, hosted deployment or real effects/music
listening audition was exercised. Controlled playback proves transport and mixer
behavior; real voice/music quality remains unverified. Existing local saved-history
verification and single-writer storage guarantees remain intact. No source-store rewrite.
Restart/readiness evidence will be appended after the authorized local restart.

## Authorized original-store restart

Restarted the verified original launcher/process tree after merging, retaining
current server configuration and the real DATA_DIR. Before shutdown, all **20**
saved cities were already paused; no pause commands were necessary. Readiness
returned with `status=ok`, and all **20** cities restored paused. The development
UI at `http://127.0.0.1:5173/`, its same-origin capability proxy, an existing city's
new v2 disaster state route, and the independent disaster OpenAPI all returned
200. Original-checkout production build also passed. Startup occurred at
04:40:25 local time; readiness was confirmed by 04:43:49. The launcher uses the
existing configurable 1200-second allowance for this large-history recovery.

Gemini and narration were enabled in the user's current configuration before and
after restart; these settings were preserved. No smoke mutation or paid-provider
request was made. Sanitized `before-restart.json`, `after-restart.json`, build log
and launcher output are retained alongside the test evidence. The unrelated local
README edit was reapplied successfully after the fast-forward; it remains uncommitted.
This is documentation-only follow-up to the tested source; no application change.
