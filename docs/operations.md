# Operations

## Deploy and update

    docker compose up -d --build

The `janus` container applies database migrations at start. The worker, sentinel and scanner wait for `janus` to be healthy. Every container has a health check and the `autoheal=true` label:

| Container | Healthy when |
|---|---|
| `janus` | `/api/health` (FastAPI) and `/api/healthz` (Next.js) answer |
| `janus-worker` | heartbeat file younger than 15 min |
| `janus-sentinel` | heartbeat file younger than 5 min (written after each ARP sweep) |
| `janus-scanner` | heartbeat file younger than 10 min |

Logs: `docker logs -f janus-worker` (same for the others). Rotation is 3 × 10 MB per container.

## Sync modes

| Mode | Behaviour |
|---|---|
| `dry-run` | Janus computes and logs the reservation diff; the DHCP provider is never written. Approve/block answer `enforcement: dry-run`. |
| `apply` | Reconcile writes the diff every 5 minutes; approve/block write at once and revoke leases. |

The switch happens only through the cutover procedure: see [runbooks/cutover.md](runbooks/cutover.md).

## CLI

Inside the `janus` container:

    docker exec -it janus python -m app.cli <command>

| Command | Purpose |
|---|---|
| `import-csv <file> [--dry-run]` | Import devices from a CSV export and infer group ranges |
| `sync [--apply]` | Show (or apply) the reservation diff of the DHCP provider now (generic) |
| `sync-mode apply\|dry-run` | Switch enforcement for any DHCP provider (refused without one taking reservations); records a `sync.mode` event |
| `preflight` | Check that the DHCP cutover can start; non-zero exit while something blocks |
| `backup` | Save a Pi-hole Teleporter export and a Janus data dump to `janus/backups/<timestamp>/` |
| `cutover --pihole-password-env VAR` | Enable Pi-hole DHCP with the quarantine pool and switch Janus to `apply` |
| `rollback --pihole-password-env VAR` | Turn Pi-hole DHCP off (removing the guest range first) and switch Janus back to `dry-run` |

`preflight`, `backup`, `cutover` and `rollback` are registered by the Pi-hole provider through its `cli` hook; usage is unchanged. `cutover` refuses when the DHCP role belongs to another provider. The same preflight is served at `GET /api/providers/pihole/preflight` (it replaces `/api/cutover`), and its informational `guest_rules` check does not block.

## Metrics

The worker serves Prometheus metrics on `janus-worker:9108/metrics` (network `metrics_internal`):

| Metric | Type |
|---|---|
| `janus_devices{access,online}` | gauge |
| `janus_devices_pending` | gauge |
| `janus_devices_health{health}` | gauge (`ok`, `warning`, `critical`) |
| `janus_last_sweep_timestamp_seconds` | gauge |
| `janus_last_port_scan_timestamp_seconds` | gauge |
| `janus_provider_up{role}` (`dhcp`, `dns`), `janus_sentinel_up`, `janus_maintenance_active` | gauge |
| `janus_sync_mode_info{mode}` | gauge |
| `janus_events_total{type}` | counter |

`janus_pihole_up` was replaced by `janus_provider_up{role}`: update dashboards and alerts. `infra.down` / `infra.up` events now carry `service` = `dhcp` or `dns` (was `pihole`) plus a `provider` field.

## Backups

A `pg_dump` of the whole `janus` database is enough, but it must include **both** schemas: `public` (Janus data, Alembic) and `auth` (better-auth users, password hashes, sessions). A dump restricted with `-n public` loses every user. `janus backup` covers the Pi-hole side and Janus data; the job that backs up PostgreSQL must keep the `auth` schema. Keep at least one local admin (via `/setup` or `JANUS_ADMIN_USERNAME`/`JANUS_ADMIN_PASSWORD`) so a broken identity provider never locks you out.

## Upgrading to the provider/better-auth release

- **`JANUS_PIHOLE_URL` has no default any more.** Compose still passes it; outside compose set it (or save the URL in Settings). Migration `0008` moves the stored Pi-hole URL and written-MAC markers into the provider settings; migration `0009` adds the guest access value and columns.
- **Authentik callback.** better-auth serves it at `/api/auth/callback/authentik`, the path NextAuth used; verify the redirect URI in Authentik (Applications > Providers > janus) before deploying. After the first deploy check that "Sign in with Authentik" completes.
- **Sessions and the first admin.** Everybody signs in again once (new session store). The first start creates the `auth` schema and there is no user yet, so every page (`/login` included) leads to `/setup`. There you either create a local admin, or press "Sign in with Authentik" (shown next to the form for every configured OIDC provider): while no user exists, the first allowlisted OIDC account to sign in becomes admin (its source stays `oidc`). Alternatively set `JANUS_ADMIN_USERNAME`/`JANUS_ADMIN_PASSWORD` before the first start to create the local admin automatically. Later allowlisted Authentik users are created as plain users on their first OIDC login.
- **Secret key.** Production has no `JANUS_SECRET_KEY`, so stored secrets are encrypted with `JANUS_INTERNAL_TOKEN`. Rotating the token (or the key) orphans them: they read back as unset and must be re-entered. Set `JANUS_SECRET_KEY` before saving secrets to decouple the two.
- **DNS probe target.** The sentinel probes the host of the DNS provider (the Pi-hole URL by default) instead of falling back to `127.0.0.1`; compose now passes the provider env (`JANUS_PIHOLE_*`, `JANUS_DHCP_PROVIDER`, `JANUS_DNS_PROVIDER`, `JANUS_UNIFI_*`, `JANUS_INTERNAL_TOKEN`, `JANUS_SECRET_KEY`) to `janus-sentinel` too. Without it the sentinel sees no DNS provider and the probe is off.
- **Metrics and events.** Rename `janus_pihole_up` in dashboards and alerts; `infra.*` events use `service` = `dhcp`/`dns`.
- **E-mail.** `JANUS_SMTP_HOST` has no default; compose passes `SMTP_HOST`, so make sure it is in `.env`. Use `JANUS_SMTP_SECURITY` (and the port) for STARTTLS.
- Compose no longer passes `AUTH_TRUST_HOST`; `AUTH_AUTHENTIK_*` and `JANUS_ALLOWED_EMAILS` are optional and read by the backend.

## Notifications

Events are written to the `events` table and dispatched every 15 s, through the channels configured in Settings > Integrations (Gotify and/or e-mail; with none ready the notification pages are hidden). Defaults (editable per event in **Notifications**):

| Event | Default |
|---|---|
| `device.new` | Gotify priority 8 + e-mail, never muted |
| `ip.conflict`, `security.risky_service` | Gotify priority 8 + e-mail |
| `infra.down` | Gotify priority 8 + e-mail, muted during maintenance |
| `security.new_port` | Gotify priority 6 |
| `device.approved`, `device.blocked` | Gotify priority 4 |
| `infra.up` | Gotify priority 4 + e-mail, muted during maintenance |
| `device.offline` | Gotify priority 5, muted during maintenance |
| `device.private_mac` | Gotify priority 5 |
| `device.ip_mismatch` | e-mail only |
| `guest.added`, `guest.expired`, `guest.removed` | off (enable in Notifications rules) |

Quiet hours defer non-urgent messages; Redis debouncing collapses bursts of the same alert.

## Tests

Backend (needs a reachable PostgreSQL database `janus_test`; the script reads `.env`):

    scripts/test.sh

Frontend:

    cd frontend && npm ci && npm test

`backend/tests/test_repo_hygiene.py` fails if a real MAC address is about to be committed: use the documentation ranges `00:00:5E:00:53:xx` / `02:00:5E:00:53:xx` in examples and fixtures.
