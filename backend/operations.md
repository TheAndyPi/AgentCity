# Storage and operations

The local repository stores immutable compressed **full internal states**, not
only public frames, under `DATA_DIR/objects/<sha256>.json.z`. An ordered per-world
revision journal in `manifest.json` references those objects. Full states include
profiles/version provenance, needs/inventory/paths, memories/beliefs/ties, plans,
interactions/acceptances, RNG, schedules, policies, event cohorts, counters,
provider references, snapshots and lineage. Snapshot labels point at exact durable
states. Every revision is therefore also a recoverable immutable checkpoint.

A write stages objects, flushes and fsyncs their temporary files, atomically
renames them, then flushes/fsyncs and atomically replaces the checksum-protected
manifest. The manifest replacement is the sole visibility/commit point. Public
heads change after successful durability. A failed save publishes neither its
new revision nor a "saved" receipt. The service stops further mutations and
returns readiness 503 while the last committed state stays readable. On supported
Unix systems the parent directory is also fsynced; Windows uses Python's fsync
and same-volume replacement. Tests inject failure before manifest replacement
on Windows; actual power-loss/filesystem-controller guarantees were not tested.

Recovery verifies the manifest, object hashes and contiguous revision numbers.
It checks each unique compressed object and its tick/revision reference without
constructing every historical Python object graph. Restored heads receive full
State validation at startup, and historical reads fully validate their requested
State on demand. Invalid heads fall back to a valid prefix and degrade readiness.
Incomplete temporary/orphan objects are ignored. A damaged referenced revision
retains its valid prefix, marks readiness degraded and blocks mutations until
operator recovery. An invalid manifest checksum fails startup clearly rather
than pretending a new empty store exists. Restore a known-good backup for that
case. Do not repair committed history with ad hoc edits.

Running worlds restore paused with a new durable loaded revision. Open editors
and auto-resume permissions are cleared. Pending network calls are not serialized;
new deliberation uses the restored state. An unfinished durable initialization
continues from completed stages. One service process holds the writer file lock.
Shutdown retains that lock until an in-flight storage transaction finishes,
including a thread whose asynchronous await was cancelled.

Idempotency receipts, sessions, profiles, settings and measured usage share the
same manifest transaction as their mutation. A same-key same-normalized-request
retry returns its original status/body before checking current control versions.
A different request with that key returns 409. Branches copy an independent
immutable prefix reference list; all historical projections use the new world ID.
Deleting a source does not remove a branch's referenced objects. Holds, preview
tokens, task generations and resume intent do not carry into a branch.

All history is retained for the bounded demonstration. Logical deletion does
not garbage collect objects, and revision objects currently contain growing
audit history. Monitor disk use and back up the **entire DATA_DIR while the
writer is stopped**. Long 10,000-tick/100-citizen retention was not load-tested;
production retention, compaction and garbage collection need a separately
validated increment. Never remove a referenced object to free disk space.

No database migration is required for a fresh 1.0.0 local store. A future schema
or operational-adapter change must provide a versioned migration and backup/
restore rehearsal. No PostgreSQL dual-write path exists in this build.

## Private production deployment recipe

Coordinator integration is required; this task does not create root deployment
files or deploy anything. On a persistent host such as Vultr:

1. Install the locked Python environment. Give a dedicated service account a
   persistent private DATA_DIR and enough disk for history plus backups.
2. Set `AUTH_MODE=session`, a random 32+ character `SESSION_SECRET`, a shared demo
   `DEMO_PASSPHRASE`, and exact HTTPS `ALLOWED_ORIGINS`. Set any vendor keys only
   in server environment. Rotating SESSION_SECRET invalidates session lookups.
3. Run `python -m app` under a process supervisor, **one worker**, normally
   binding 127.0.0.1:8000 behind the proxy. Probe `/health/ready` and `/health/live`.
4. Serve the frontend from the same TLS origin and reverse-proxy `/api`, with
   WebSocket Upgrade/Connection forwarding and a timeout longer than 45 seconds.
   Forward headers only from the configured trusted proxy; do not expose an
   unrestricted forwarded-client-address trust setting.
5. Verify login, Secure/HttpOnly/SameSite=Lax cookies, Origin/CSRF denial, socket
   reconnect, a durable save/restart and backup restore through that proxy.

HTTP login returns CSRF and a Secure cookie, so session mode needs HTTPS at the
browser. There is one demo owner, not account registration or public tenancy.
Every world/profile/export is owner scoped. Local mode checks both peer address
and loopback Host; it is only for loopback development.

The stream sender holds no simulation commit lock. It reads only the latest
durable head, coalesces intermediate revisions, and disconnects a socket whose
send stalls for two seconds. A 15-second server heartbeat maintains idle links.
The client must implement the contract's reconnection/backoff and polling
fallback; no frontend was available for that half of the protocol.

Runtime measurements are available to operators in `Service.stats` and
`Gateway.diagnostics` and are exported by the benchmark script. They include
compute/commit samples, socket bytes, provider queue/fallback/timeout/discard
counts and measured usage. No extra diagnostic HTTP endpoint was invented.
