# Vultr release runbook

Prepared configuration; **live deployment is unverified**. No host, DNS, billing,
firewall or account changes have been made. Requires an authorized persistent
Linux host, Python 3.13+, Node 22.12+, Caddy, systemd, sufficient disk and an
authorized HTTPS hostname. Use one application worker and one running city.

## Install a reproducible candidate

1. Create a dedicated unprivileged `agentcity` account, `/var/lib/agentcity/data`
   owned by that account (0700), `/etc/agentcity` (0750), and a release directory
   `/opt/agentcity/releases/<full-commit>`. Keep source/build directories read-only
   for the service account. Provision only authorized 80/443 ingress; application
   port 8000 binds loopback. Do not expose Vite or development reload.
2. Check out the reviewed full commit into the release directory. From its root,
   run `npm --prefix frontend ci`, `npm run build`,
   `python3.13 -m venv backend/.venv`, then
   `backend/.venv/bin/python -m pip install -r backend/requirements.lock`.
   Run `npm test` with `AGENTCITY_PYTHON` pointing to that environment. The committed
   lock pins tested dependencies; deployment needs no global Python packages.
3. Copy `runtime.env.example` to `/etc/agentcity/runtime.env`; replace secret and
   origin placeholders. Keep it root:agentcity 0640. Copy the unit into systemd,
   and configure the reviewed `Caddyfile` with the authorized hostname. Keep
   cloud/service-account files outside Git, readable only by the service. Grant
   Tiger credentials access only to its dedicated schema; see the Tiger handoff.
4. Set `/opt/agentcity/current` to the candidate release using an atomic symlink
   replacement while the service is stopped. Install/start the unit after
   `systemctl daemon-reload`. Validate Caddy with `caddy validate --config ...`
   before reloading it. Caddy serves HTTPS and WebSocket upgrades; the app serves
   the production build, API and direct SPA reloads on the same origin. Only the
   loopback proxy is trusted for forwarded headers.

## Readiness, logs and rehearsal

- Check loopback `/health/live` and `/health/ready`, then the public HTTPS origin.
  Readiness 503 means local persistence is degraded. Optional Tiger failure is
  reported at authenticated `/api/v1/integrations/tiger/status`; it does not make
  a locally usable city fail readiness. Monitor both endpoints, lag, free disk,
  RAM and `journalctl -u agentcity`. Logs contain safe Tiger error codes, never
  raw database exception bodies. Avoid access logs with media tokens or secrets.
- Through HTTPS: log in; check Secure/HttpOnly/SameSite cookies; verify invalid
  Origin and missing CSRF are denied; create exactly ten citizens; commit a flood,
  resolve/acknowledge, save/export/branch, reload the SPA and revoke an active
  socket. Start a second writer against the same DATA_DIR and verify refusal.
- Stop and restart the service. Running cities must restore paused and committed
  exports/branches must match. These host/proxy checks remain unverified until
  executed on the real deployment. Local automated security/recovery tests are
  separate evidence.

## Offline backup, restore and rollback

1. Pause cities and stop `agentcity`; check the process has exited. Back up with
   `cd /opt/agentcity/current/backend` then
   `.venv/bin/python -m scripts.store_backup backup /var/lib/agentcity/data /secure-backups/city-<UTC>.tar.gz`.
   The script obtains the writer lock, verifies history, and refuses an existing
   archive or an archive inside the source. Restrict/encrypt archives; they contain
   sessions and simulation data. Retain the **entire** store and external database
   backup separately. Never delete immutable objects to reclaim disk.
2. Restore to a new, separate directory with
   `.venv/bin/python -m scripts.store_backup restore /secure-backups/city-<UTC>.tar.gz /var/lib/agentcity/restore-<UTC>`.
   It refuses overwrite and verifies referenced objects and heads. Start a separate
   single worker on loopback port 8001 with this DATA_DIR and a separate test
   session secret/origin, Tiger disabled, rules mode, then compare pinned exports
   and branches. Stop this drill process. Do not point it at production data.
3. Restart production and verify readiness. Before each upgrade record the current
   full commit, lockfiles and stopped-store backup. To roll back, stop the service,
   atomically repoint `current` to the previous built release, restore its compatible
   stopped-store backup into a **new** directory if required, update DATA_DIR,
   restart and rerun readiness/export/HTTPS checks. No down-migration or destructive
   database rollback is necessary for this additive optional read model. Do not
   reuse a newer store with an older incompatible application without a drill.
4. If the optional SQL database is restored independently, reset the local
   `tiger-progress.json` while stopped to replay retained committed history.
   Local restore integrity and branch equality are automated; actual host restore,
   Caddy, supervision and rollback rehearsal remain unverified.

History currently retains growing full states. A short measured benchmark is not
a 10,000-tick endurance sign-off. Establish disk alarms before a long run.
