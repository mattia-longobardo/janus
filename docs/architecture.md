# Architecture

Interactive diagrams (open in a browser, with dark/light theme, search and export):

- [diagrams/architecture.html](diagrams/architecture.html) — containers and their connections
- [diagrams/device-access.html](diagrams/device-access.html) — how a device moves between `pending`, `authorized`, `lan_only` and `blocked`

The `.json` file next to each diagram is its source; regenerate with [Archify](https://github.com/tt-a1i/archify) (`archify finalize <type> <file>.json <file>.html`).

## Containers

One image (`Dockerfile`) runs in four containers; `entrypoint.sh` picks the role from the command.

| Container | Command | Network | What it does |
|---|---|---|---|
| `janus` | `api` | `proxy_public`, `db_internal` | Runs `scripts/migrate-auth.mjs` (better-auth schema) and `alembic upgrade head`, then FastAPI on `127.0.0.1:8000` and the Next.js server on `:3000`. Traefik routes `https://${JANUS_HOST}` to port 3000. |
| `janus-worker` | `worker` | `db_internal`, `mail_internal`, `metrics_internal` | Periodic jobs (below) and Prometheus metrics on `:9108/metrics`. |
| `janus-sentinel` | `sentinel` | host | Sniffs ARP, DHCP, NetBIOS, SSDP and mDNS answers on `enp5s0`, sweeps the subnet with ARP every 60 s, probes the DNS provider's host. Stays user 1000 through a `cap_net_raw` file capability on `/usr/local/bin/janus-sniff`. |
| `janus-scanner` | `scanner` | `db_internal` | Unprivileged `nmap -sT -sV --top-ports 200`, one host at a time, inside the scan window. |

All four share the PostgreSQL database; they talk to each other only through it (settings, heartbeats, events).

## Request path

1. The browser reaches Traefik over HTTPS; Traefik forwards to Next.js on `:3000`.
2. better-auth (`frontend/lib/auth/`, served under `/api/auth/*`) signs the user in with a username and password, or through an OIDC provider such as Authentik. Providers and the allowlist come from the backend (`GET /api/internal/auth-config`, cached 15 s, last good copy kept if the backend is down). A local user may sign in unless banned; an OIDC user is created only when their e-mail is allowlisted, and every request re-checks the allowlist (`getAllowedSession`), so removing an address takes effect within the cache time. With no user yet every page redirects to `/setup`, which creates the first admin.
3. The catch-all route `frontend/app/api/[...path]/route.ts` forwards `/api/*` to FastAPI on `127.0.0.1:8000`. It refuses unsigned (401) and cross-site (403) requests and bodies over 1 MB, and adds the `X-Janus-Internal-Token` header.
4. FastAPI accepts every route except `/api/health` only with that token (`backend/app/security.py`), compared in constant time. The API is bound to loopback, so nothing outside the container reaches it.

## Background jobs

### Worker (`backend/app/worker.py`)

A single loop that runs each job when it is due and touches `/tmp/janus-worker.heartbeat` for the Docker health check.

| Job | Interval | Effect |
|---|---|---|
| `reconcile` | 300 s | Compares the desired reservations with the DHCP provider's entries. In `dry-run` it only logs the diff; in `apply` it removes stale entries and adds missing ones, one at a time. Marks the role down/up (`infra.down` / `infra.up` with `service` = `dhcp`/`dns`). With Pi-hole it also writes the guest range. |
| `guests` | 60 s | Removes expired guests (own expiry, or the global rules) and revokes the lease of one still connected. |
| `presence` | 60 s | Tracks maintenance windows, checks the sentinel heartbeat, marks devices offline after 300 s without a sighting (offline alerts per group, muted during maintenance), purges sightings older than 30 days. |
| `dns` | 60 s | The DNS role is down if the sentinel has had no DNS answer for 3 minutes. |
| `dispatch` | 15 s | Sends pending events as Gotify / e-mail notifications according to the rules, quiet hours, maintenance windows and debouncing (Redis db 3). |
| `identity` | 60 s | Turns DHCP, mDNS, NetBIOS, SSDP announcements and the offline IEEE OUI file into device facts (vendor, model, OS hints). |

### Sentinel (`backend/app/sentinel/`)

- `observe.py` parses packets into observations (MAC, IP, source, hostname and announcement data).
- `record.py` turns observations into devices, sightings and events: a new MAC becomes a `pending` device (`device.new`); the gateway is recorded as authorized; it also raises `ip.conflict` (two MACs claim one address), `device.ip_mismatch` (an approved device outside its reservation) and `device.private_mac`.
- A full packet queue drops packets instead of blocking; a dead sniffer or a change of network settings makes the process exit so Docker restarts it.

### Scanner (`backend/app/intel/`)

`scanning.py` picks the next device: manual scan requests first (`POST /api/devices/{id}/scan`), then online approved devices in groups with `scan_enabled` whose last scan is older than the group interval. Manual requests run at any time; scheduled scans are skipped during quiet hours, maintenance windows and outside the scan window (08:00–22:00 by default). New open ports raise `security.new_port`; services in `rules.py`'s risky list raise `security.risky_service` (mutable per service).

## Network providers

Janus talks to the network through providers: plugins in `backend/app/providers/<kind>/`, discovered from the folder (Pi-hole
and UniFi ship with it). A provider declares the **roles** it can hold (`dhcp`, `dns`; one provider per role) and its
**capabilities** (`RESERVATIONS`, `FORCE_RENEW`, `QUARANTINE`, `DHCP_SERVER`, `CLIENT_INVENTORY`, `DNS_QUERY_LOG`, `DNS_PROBE`), and the
**policies** it can enforce (`FULL`, `LAN_ONLY`, `GUEST`, `BLOCKED`). The rest of Janus asks for a capability, never for a
provider name, and `GET /api/features` has a `providers` block per role (kind, label, capabilities, policies, `shared`,
`down_since`). Approving with a policy the provider lacks answers 409; with no DHCP provider approval answers `enforcement: "no provider"`.

Roles are chosen in Settings or with `JANUS_DHCP_PROVIDER` / `JANUS_DNS_PROVIDER`. When both roles name the same kind, DNS is
`same_as` DHCP: one config, one session. Provider config lives in the setting `providers.config` (secrets encrypted). Provider routers are
mounted at `/api/providers/<kind>`, and `janus_provider_up{role}` reports each role. See
[providers/adding-a-provider.md](providers/adding-a-provider.md) to write a new one.

### Pi-hole

Pi-hole v6 REST API (`backend/app/providers/pihole/`) with an app password; one login is shared across requests because Pi-hole refuses parallel logins. Roles: DHCP and DNS.

- **Reservations.** Every approved device with a MAC and a static IP becomes a `dhcp.hosts` line `mac[,set:lanonly],ip,hostname,24h`. Janus remembers which lines it wrote (`provider.pihole.written_macs`) and only removes those, so hand-written lines survive. Duplicate IPs or MACs are refused rather than written, so Pi-hole's DNS never breaks on a bad config.
- **Quarantine.** Pi-hole's DHCP range is the quarantine pool `.240-.254`; unknown devices get an address there without a gateway, so they reach only the LAN until approved.
- **LAN only.** `lan_only` devices get a reservation tagged `set:lanonly`; the Pi-hole `dhcp-option` tag rules (in the network stack) withhold the gateway from them.
- **Immediate enforcement.** In `apply` mode, approve and block write at once instead of waiting for the next reconcile. Approve revokes the device's quarantine lease, block revokes its current lease.
- **Guests.** See below.
- **Cutover.** `/api/providers/pihole/preflight` and the `janus preflight|backup|cutover|rollback` commands (registered through the provider's `cli` hook).
- **DNS activity.** The device page reads Pi-hole's query log for the device's IP (`/api/devices/{id}/dns`, `/dns/analysis`).

### UniFi

UniFi Network API client (`backend/app/providers/unifi/`) with a local Site Admin account (no 2FA). Role: DHCP. Policies: `FULL` (fixed IP on the LAN network), `GUEST` (known client, no fixed IP) and `BLOCKED` (block flag); there is no `LAN_ONLY`, so approving with it answers 409 and the frontend hides the option.

- **Ownership.** Janus writes `note = "janus:<policy>"` on every client it reserves and reads only clients with that note as its own. Clients you configured by hand (fixed IP or block, no note) are left alone; clear the fixed IP or block first to let Janus take one over. An admin note on a managed client is overwritten.
- **Clients page.** `GET /api/providers/unifi/clients` lists known and connected clients with AP or switch port and the matching Janus `device_id`; the page is `/integrations/unifi/clients`. 404 when UniFi does not hold DHCP, 502 when the controller is unreachable.
- **Status.** Hardware verification (task D4) is pending on a real controller.

### Guests

A guest is a device with access `guest`, a device that gets a dynamic address from the guest pool, optionally with an expiry. The DHCP provider must support the `GUEST` policy (or there is no provider, and Janus only keeps the list); otherwise guest writes answer 409 and list/removal still work.

- **Rules.** Global rules in `guests.settings` (`auto_remove_hours`, `inactive_remove_hours`) and an optional per-guest expiry that replaces them. The worker's `guests` job removes expired guests; one still connected loses its lease and returns as `pending`. Events: `guest.added`, `guest.expired`, `guest.removed` (notifications off by default).
- **Pi-hole (dnsmasq variant A).** Each guest is a `dhcp-host=<mac>,set:guest,<hostname>,<lease>` line with no address. Janus manages exactly one `dhcp-range=tag:guest,<start>,<end>,<lease>` line in `misc.dnsmasq_lines`, written after each apply sync and never touching other lines there. Clearing the pool removes it, and `janus rollback` removes it first. Writing it needs `app_sudo`, which the cutover grants; before the cutover with a pool defined the write is refused and recorded once as `sync.failed`.
- **Pool exhaustion.** If the guest pool is full, dnsmasq may fall back to the untagged quarantine range, which has no router (to verify on real FTL). Size the pool for the visitors you expect. The Guests page warns when no pool is set and the provider has a quarantine range.

## Data model

PostgreSQL, migrations in `backend/migrations/versions/` (applied at container start).

| Table | Holds |
|---|---|
| `groups` | Name, colour, icon, IP range, default access, offline alert hours, scan settings |
| `devices` | MAC, name, hostname, group, static IP, last IP, access (`authorized`, `lan_only`, `pending`, `blocked`, `guest`), guest since/expiry, presence, scan state |
| `sightings` | Who was seen at which IP, from which source (30-day retention) |
| `device_facts` | Identity facts from DHCP/mDNS/NetBIOS/SSDP/OUI |
| `services` | Open ports from nmap, risk level, mute flag |
| `events` | Event log and notification outbox |
| `notification_rules` | Per-event channel and Gotify priority |
| `maintenance_windows` | Recurring windows that mute offline and infra alerts |
| `links` | Wired uplinks drawn on the network map |
| `settings` | Key/value: network overrides, sync mode, heartbeats, down-since markers, map positions, `providers.config`, `auth.config`, `notify.*`, `guests.settings` (secrets encrypted) |

## Security model

- Single trust boundary at the web app: better-auth sign-in (password, optional OIDC with e-mail allowlist), same-origin check, then a shared secret to the loopback-only API.
- Everything runs as user 1000. Only the sentinel needs raw sockets, granted to one binary via a file capability; the other containers drop `NET_RAW`.
- Device identification uses only local data (OUI file, LAN announcements, DNS provider log); no external lookup services.
- The Pi-hole admin password is never stored: cutover and rollback read it from an environment variable for one command.
- Secrets saved from Settings (provider passwords, OIDC secrets, Gotify token, SMTP password) are encrypted with `JANUS_SECRET_KEY` (fallback `JANUS_INTERNAL_TOKEN`); API responses return only set/unset booleans.
