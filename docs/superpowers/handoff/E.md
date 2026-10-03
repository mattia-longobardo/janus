# Handoff E: guests

## Environment variables
- `JANUS_GUEST_START`, `JANUS_GUEST_END` (new, optional): the guest DHCP pool. Empty (the default) means no pool. Both
  or neither: setting only one is refused, like a pool that overlaps the quarantine pool, a group range or the gateway.
  The pool can also be set in Settings → Guests (`network.guest_start`/`guest_end`); saving the env value drops the override.
- `JANUS_GUESTS_INTERVAL_S` (new, default 60): how often the worker's `guests` job removes expired guests.

## Data
- Migration `0009`: new `access` value `guest`, columns `devices.guest_since` and `devices.guest_expires_at` (UTC).
- Global rules live in the `guests.settings` setting: `auto_remove_hours` (from `guest_since`) and
  `inactive_remove_hours`, each `null` (off) or 1..8760. Inactivity counts from `max(last_seen, guest_since)`, so
  activity from before the device became a guest does not count. A guest's own expiry replaces both rules.

## Pi-hole (variant A, confirmed by the E0 spike)
- Each guest is a `dhcp-host=<mac>,set:guest,<hostname>,<lease>` line, with no address.
- Janus manages exactly one `dhcp-range=tag:guest,<start>,<end>,<lease>` line in `misc.dnsmasq_lines`; other lines
  there are never touched. It is written after each apply sync, removed when the pool is cleared, and removed first
  on `janus rollback`.
- Writing `misc.dnsmasq_lines` needs `app_sudo`, which the cutover grants. Before the cutover, with a pool defined, the
  write is refused and recorded once as `sync.failed` ("guest range needs app_sudo (run the cutover)").
- The cutover preflight has an informational check `guest_rules` (non-blocking: the cutover writes the line itself).
- To verify on real FTL: if the guest pool is full, dnsmasq may fall back to the untagged quarantine range (no router).
  The page warns when there is no pool and the provider has a quarantine range.

## API
- `GET /api/guests`, `POST /api/guests`, `PATCH /api/guests/{id}`, `DELETE /api/guests/{id}`,
  `GET|PUT /api/guests/settings`, `POST /api/devices/{id}/guest` (pending devices only).
- `GET /api/devices` no longer lists guests; `?access=guest` does.
- With a DHCP provider that lacks the guest policy, guest writes answer 409 `"<label> does not support guests"`; list and
  removal keep working. `GET /api/features` has `guests: {enabled, pool}`.

## Events
- `guest.added`, `guest.expired`, `guest.removed`. Their notifications are off by default (Notifications → rules).
- An expired guest that is still connected has its lease revoked and comes back as a pending device.
