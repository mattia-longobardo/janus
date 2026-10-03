# Janus

Self-hosted control plane for a home LAN (192.168.1.0/24): device inventory, static IPs through DHCP reservations (Pi-hole v6 or UniFi, as network providers), quarantine and approval of new devices, time-limited guests, local device identification and port scanning, optional alerts via Gotify and e-mail.

Janus never sits in the traffic path. It watches the LAN (ARP, DHCP, mDNS, NetBIOS, SSDP), keeps the inventory in PostgreSQL and tells the DHCP provider which reservations to hold. The router (QHora-301W) stays the gateway; after the cutover Pi-hole is the only DHCP server.

## Documentation

| Document | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Containers, data flow, network providers, guests, background jobs, data model, security model |
| [docs/configuration.md](docs/configuration.md) | Required and optional environment variables, and the settings editable from the web app |
| [docs/operations.md](docs/operations.md) | Deploy, sync modes, CLI, metrics, backups, upgrade notes, tests |
| [docs/providers/adding-a-provider.md](docs/providers/adding-a-provider.md) | Writing a network provider plugin |
| [docs/runbooks/cutover.md](docs/runbooks/cutover.md) | Moving DHCP from the router to Pi-hole, and rolling back |
| [docs/diagrams/architecture.html](docs/diagrams/architecture.html) | Interactive architecture diagram (open in a browser) |
| [docs/diagrams/device-access.html](docs/diagrams/device-access.html) | Interactive device access lifecycle |

## Quick start

    cp .env.example .env      # fill in the four required variables, see docs/configuration.md
    docker compose up -d --build

Open `https://<JANUS_HOST>`: with no user yet you are sent to `/setup` to create the first admin (or set `JANUS_ADMIN_USERNAME`/`JANUS_ADMIN_PASSWORD`). Everything else is optional and configured in **Settings** or through the optional variables of `.env.example`: Gotify and e-mail notifications, Authentik/OIDC sign-in, the Pi-hole or UniFi provider, the guest pool.

The stack joins the external networks `proxy_public`, `db_internal`, `mail_internal` and `metrics_internal`, and expects the shared PostgreSQL (database `janus`), Redis and Traefik of the homelab; Authentik, Gotify and SMTP are optional. Back up the `auth` schema of the database together with `public`.

Janus starts in `dry-run`: it computes the reservation diff and never writes to the DHCP provider until the cutover switches it to `apply`.

## Layout

    backend/     FastAPI API, worker, sentinel, scanner, Alembic migrations, tests
    frontend/    Next.js web app (better-auth, optional OIDC), proxy to the API, tests
    docs/        documentation, runbook and diagrams
    Dockerfile   one image for all four containers (entrypoint.sh picks the role)
