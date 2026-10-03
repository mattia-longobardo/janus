# Handoff D: UniFi provider

## Environment variables
- `JANUS_UNIFI_URL`, `JANUS_UNIFI_USERNAME`, `JANUS_UNIFI_PASSWORD` (new, optional): the UniFi Network console and a
  local admin account (Site Admin, no 2FA: the classic API does not support it). They are the defaults of the UniFi
  provider; Settings → Network providers overrides them (the password is stored encrypted).

## Policies
- UniFi supports FULL (fixed IP on the LAN network), GUEST (known client without fixed IP) and BLOCKED (block flag).
  There is no LAN only policy: approving with it answers 409 and the frontend hides the option.
- Janus writes `note = "janus:<policy>"` on every client it reserves. Only a client with a `janus:` note is read as a
  Janus reservation; an existing admin note on a managed client is overwritten.
- To let Janus take over a client you configured by hand in UniFi, clear its fixed IP/block first.

## API
- `GET /api/providers/unifi/clients`: known and connected clients with AP or switch port, `device_id` linking the
  Janus device with the same MAC. 404 when UniFi does not hold the DHCP role, 502 when the controller is unreachable.
- Frontend page "UniFi clients" at `/integrations/unifi/clients`, listed while UniFi holds DHCP.

## Hardware verification
- Pending: the D4 checklist (task D4 in the plan) on the real controller. Record there the UniFi Network version,
  endpoint differences found and the fixes applied.

D4 checklist (summary of the plan task, with the enforcement step made explicit):
1. Create a local UniFi user (Site Admin, no 2FA), e.g. `janus`.
2. Settings → Network providers: DHCP = UniFi; DNS = Pi-hole or None. "Test connection" must answer `ok`.
3. Still in `dry-run`: `GET /api/sync/plan` must list the hand-set fixed IPs in `unmanaged` and have an **empty**
   `to_remove`.
4. Switch to `apply`: Settings → Access control → Enforcement → "Switch to apply…" (admins only; it shows the plan
   counts before confirming), or `janus sync-mode apply` in the worker container. The Pi-hole `cutover` command does
   not apply to UniFi.
5. Approve a test device → fixed IP in UniFi; block it → blocked in UniFi; unblock it.
6. Test guest (after E): no fixed IP, note `janus:guest`, removed at expiry.
7. Switch back with "Switch to dry-run" / `janus sync-mode dry-run` if anything looks wrong.
