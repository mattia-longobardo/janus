# Configuration

## `.env` (compose)

Copy `.env.example` to `.env`. `docker-compose.yml` turns these into the container variables below. Only four
variables are required; every other one is optional and turns on one feature. Optional variables are passed as `${VAR:-}`,
so a missing one never breaks `docker compose`.

### Required

| Variable | Used for |
|---|---|
| `DB_JANUS_PASSWORD` | Password of the `janus` role on the shared PostgreSQL |
| `JANUS_INTERNAL_TOKEN` | Shared secret between the Next.js proxy and FastAPI (long random string); also the fallback key for stored secrets (see `JANUS_SECRET_KEY`) |
| `AUTH_SECRET` | better-auth session secret (`openssl rand -base64 32`). Changing it signs everybody out |
| `JANUS_HOST` | Public host name served by Traefik; also `AUTH_URL` (the better-auth base URL) |

With only these set the app starts with password login: the first visit redirects to `/setup`, which creates the first admin. When OIDC providers are configured, `/setup` also shows their buttons: while no user exists, the first allowlisted OIDC account to sign in becomes admin.
The notification pages stay out of the menu until a channel is ready. Guests is listed while the DHCP provider supports guests or there is no provider (Janus then only keeps the list).

### Optional

| Variable | Enables |
|---|---|
| `REDIS_PASSWORD` | Redis db 3, the notification debounce store |
| `JANUS_PIHOLE_PASSWORD` | Pi-hole provider (app password: reads always, writes only after the cutover enables `app_sudo`). `JANUS_PIHOLE_URL` is fixed in `docker-compose.yml` |
| `GOTIFY_HOST`, `JANUS_GOTIFY_TOKEN` | Gotify channel (server and application token) |
| `SMTP_HOST`, `SMTP_NOREPLY_USER`, `SMTP_NOREPLY_PASSWORD`, `JANUS_NOTIFY_EMAIL` | E-mail channel; the user is also the sender, the last is the recipient |
| `JANUS_SMTP_SECURITY` | `ssl` (default) \| `starttls` \| `none`. Compose hard-codes `JANUS_SMTP_PORT=465`, so edit the port too when switching to STARTTLS |
| `AUTHENTIK_HOST`, `AUTH_AUTHENTIK_ID`, `AUTH_AUTHENTIK_SECRET` | Authentik OIDC sign-in (application `janus`) |
| `JANUS_ALLOWED_EMAILS` | Comma-separated e-mails allowed to sign in through OIDC; empty means no OIDC user. Local users are not subject to it |
| `JANUS_ADMIN_USERNAME`, `JANUS_ADMIN_PASSWORD` | A first local admin, created at start-up only when there is no user (alternative to `/setup`) |
| `JANUS_SECRET_KEY` | Key for the encrypted secrets in the database; unset falls back to `JANUS_INTERNAL_TOKEN` (see below) |
| `JANUS_DHCP_PROVIDER`, `JANUS_DNS_PROVIDER` | Which provider holds each role: a kind (`pihole`, `unifi`) or `none` |
| `JANUS_UNIFI_URL`, `JANUS_UNIFI_USERNAME`, `JANUS_UNIFI_PASSWORD` | UniFi provider defaults |
| `JANUS_GUEST_START`, `JANUS_GUEST_END` | Guest DHCP pool (both or neither) |
| `AUTH_DATABASE_URL` | libpq URL for the better-auth tables; unset derives it from `JANUS_DATABASE_URL` (drops the `+psycopg` suffix), which is right for compose |

`AUTH_TRUST_HOST` (NextAuth) is ignored and no longer in compose.

### Secret key

Secrets saved from Settings (OIDC client secrets, Gotify token, SMTP password, provider passwords) are encrypted with
`JANUS_SECRET_KEY`, or with `JANUS_INTERNAL_TOKEN` when it is unset (the compose default, and why the worker receives the
token too). Rotating whichever one is in use makes the stored secrets unreadable: they read back as unset and must be
entered again. Set `JANUS_SECRET_KEY` once, before saving secrets, if you want to rotate the internal token independently.

## Backend variables (`JANUS_*`)

Read by `backend/app/config.py`. Defaults in brackets; compose sets the ones marked *. A value saved in Settings wins over the environment.

| Variable | Default | Meaning |
|---|---|---|
| `JANUS_DATABASE_URL`* | local `janus` db | SQLAlchemy URL (`postgresql+psycopg://…`) |
| `JANUS_INTERNAL_TOKEN`* | empty | API refuses every protected route with 503 while empty |
| `JANUS_PIHOLE_URL`* | empty | Pi-hole v6 web/API. No built-in default: compose passes it; set it yourself outside compose (or save it in Settings) |
| `JANUS_PIHOLE_PASSWORD`* | empty | Pi-hole app password |
| `JANUS_SECRET_KEY`* | empty | Key for stored secrets; empty uses `JANUS_INTERNAL_TOKEN` |
| `JANUS_DHCP_PROVIDER`*, `JANUS_DNS_PROVIDER`* | empty | Provider `kind` or `none`. Unset: Pi-hole holds both roles when its password is set, nothing otherwise. Same kind for both: DNS follows DHCP (`same_as`) |
| `JANUS_UNIFI_URL`*, `JANUS_UNIFI_USERNAME`*, `JANUS_UNIFI_PASSWORD`* | empty | UniFi Network console and a local Site Admin without 2FA |
| `JANUS_GUEST_START`*, `JANUS_GUEST_END`* | empty | Guest pool; refused when only one is set or it overlaps the quarantine pool, a group range or the gateway |
| `JANUS_GUESTS_INTERVAL_S` | `60` | How often the worker removes expired guests |
| `JANUS_SYNC_MODE`* | `dry-run` | Initial mode; the stored mode (set by cutover/rollback) wins |
| `JANUS_SUBNET`, `JANUS_GATEWAY` | `192.168.1.0/24`, `192.168.1.1` | Managed network |
| `JANUS_QUARANTINE_START`, `JANUS_QUARANTINE_END` | `.240`, `.254` | DHCP pool for unknown devices (Pi-hole) |
| `JANUS_RESERVATION_LEASE` | `24h` | Lease time written into each reservation |
| `JANUS_RECONCILE_INTERVAL_S` | `300` | Reconcile period of the DHCP provider |
| `JANUS_PRESENCE_TIMEOUT_S`, `JANUS_PRESENCE_INTERVAL_S` | `300`, `60` | Offline after this long unseen; check period |
| `JANUS_DISPATCH_INTERVAL_S` | `15` | Notification dispatch period |
| `JANUS_IDENTITY_INTERVAL_S` | `60` | Identity enrichment period |
| `JANUS_SENTINEL_INTERFACE`* | `enp5s0` | Interface the sentinel sniffs |
| `JANUS_SWEEP_INTERVAL_S` | `60` | ARP sweep period |
| `JANUS_SIGHTING_RETENTION_DAYS` | `30` | Sighting history kept |
| `JANUS_SCAN_POLL_S`, `JANUS_SCAN_HOST_TIMEOUT_S` | `30`, `180` | Scanner poll period and per-host nmap timeout |
| `JANUS_SCAN_WINDOW_START`, `JANUS_SCAN_WINDOW_END` | `08:00`, `22:00` | Scheduled scans only inside this window |
| `JANUS_TIMEZONE` | `Europe/Rome` | Default time zone for quiet hours and windows |
| `JANUS_REDIS_URL`* | `redis://localhost:6379/3` | Debounce store |
| `JANUS_GOTIFY_URL`*, `JANUS_GOTIFY_TOKEN`* | empty | Gotify channel (off while empty); Settings can override |
| `JANUS_SMTP_HOST`*, `JANUS_SMTP_PORT`*, `JANUS_SMTP_SECURITY`*, `JANUS_SMTP_USER`*, `JANUS_SMTP_PASSWORD`*, `JANUS_SMTP_SENDER`* | empty host, `465`, `ssl` | E-mail channel (off while the host is empty) |
| `JANUS_NOTIFY_EMAIL`* | empty | Alert recipient |
| `JANUS_BASE_URL` | `https://janus.longobardo.me` | Links inside notifications |
| `JANUS_OUI_PATH` | `/usr/share/ieee-data/oui.csv` | Offline vendor registry (Debian `ieee-data`) |

## Frontend and auth variables

| Variable | Meaning |
|---|---|
| `BACKEND_URL` | FastAPI base URL, `http://127.0.0.1:8000` inside the container |
| `JANUS_INTERNAL_TOKEN` | Sent to the API as `X-Janus-Internal-Token` |
| `AUTH_SECRET`, `AUTH_URL` | better-auth `secret` and `baseURL` |
| `AUTH_DATABASE_URL` | Database of the better-auth tables (schema `auth`); derived from `JANUS_DATABASE_URL` when unset |
| `JANUS_ADMIN_USERNAME`, `JANUS_ADMIN_PASSWORD` | First local admin, read by `scripts/migrate-auth.mjs` at start-up |

The OIDC variables (`AUTH_AUTHENTIK_ID`, `AUTH_AUTHENTIK_SECRET`, `AUTH_AUTHENTIK_ISSUER`, or `JANUS_OIDC_ID`, `JANUS_OIDC_SECRET`,
`JANUS_OIDC_ISSUER`, `JANUS_OIDC_NAME` (default `Authentik`)) and `JANUS_ALLOWED_EMAILS` are read by the **backend** only; the
frontend gets the providers and the allowlist from `GET /api/internal/auth-config` (cached 15 s). Together they define one
env provider with id `authentik`.

## Settings editable from the web app

**Settings** changes values without a restart; each stored value wins over the environment default, and saving a value equal
to the env one drops the override.

### Integrations

Gotify and e-mail (`notify.gotify`, `notify.email`). Secrets are write-only (shown as set/unset; empty keeps the saved value).
One Save button. While no channel is ready, the Notifications pages are hidden and the menu links here.

### Sign-in & users

- Users: create local users, ban, change role, delete. The last usable admin cannot be deleted, banned or demoted.
- OIDC providers (setting `auth.config`, secrets encrypted) and the e-mail allowlist. Each provider shows its callback URL
  `https://<host>/api/auth/callback/<provider id>`; for the env provider that is `/api/auth/callback/authentik`.
- A provider whose discovery URL does not answer is left out of the login page and re-probed every 15 s; password login keeps working.

### Network providers

Which provider holds the DHCP and DNS roles, and each provider's settings (`providers.config`; Pi-hole, UniFi), with a
"Test connection" button. When DNS and DHCP are the same provider the config is shared and edited once. See
[providers/adding-a-provider.md](providers/adding-a-provider.md) for what a provider declares.

UniFi specifics: **Verify TLS is off by default** (consoles ship a self-signed certificate), so the connection to the
console is encrypted but not authenticated; turn it on once the console has a certificate this host trusts. Janus marks
every client it manages with the note `janus:<policy>`, which **overwrites any note an admin had set** on that client.

### Guests

The guest pool (`network.guest_start`/`guest_end`) and the global rules (`guests.settings`): `auto_remove_hours` (from the time
the device became a guest) and `inactive_remove_hours` (from `max(last_seen, guest_since)`), each off or 1 to 8760 hours. A
guest's own expiry replaces both rules. Guests get no static IP, so they are not shown on the map or in the IP plan;
they are listed on the Guests page.

### Other settings

- **Network:** subnet, gateway, quarantine pool, sentinel interface, sweep interval, scan window. Values are validated against each other and against the group ranges. The sentinel restarts itself when one of its settings changes.
- **Notifications:** per-event channel (Gotify, e-mail) and Gotify priority, quiet hours, time zone, test messages.
- **Maintenance windows:** recurring periods that mute offline and infrastructure alerts and pause scheduled scans.
- **Groups:** IP range, default access, offline alert threshold, port scan on/off and interval.
- **Sync mode:** `dry-run` / `apply`. Pi-hole's `cutover` and `rollback` commands set it as part of the DHCP takeover; for any other DHCP provider (UniFi) use Settings → Access control → Enforcement (admins only: switching to `apply` first shows the counts of `GET /api/sync/plan` and asks for confirmation), `POST /api/sync/mode {"mode": "apply" | "dry-run"}` or `janus sync-mode apply|dry-run`. Switching to `apply` is refused (409) without a DHCP provider that takes reservations. The backend does not check the user's role: like every API route it trusts the internal token, and the admin-only rule lives in the UI.
