# Handoff C: network providers (Pi-hole as a plugin)

## Environment variables
- `JANUS_DHCP_PROVIDER`, `JANUS_DNS_PROVIDER` (new, optional): a provider `kind` (`pihole`) or `none`. Unset keeps today's
  behaviour: Pi-hole holds both roles when `JANUS_PIHOLE_PASSWORD` is set, nothing otherwise. When DNS and DHCP name the
  same kind, DNS follows the DHCP config (`same_as`).
- `JANUS_PIHOLE_URL`: **the built-in default was removed.** It is now required outside compose (compose still passes it);
  the setting now defaults to empty, so an install that relied on the old default must set it (or save the URL in Settings).
- `JANUS_PIHOLE_PASSWORD`, `JANUS_RESERVATION_LEASE` keep their meaning.
- Provider settings changed in the UI live in the `providers.config` setting (secrets encrypted with `JANUS_SECRET_KEY`).
  Migration `0008` moves `network.config.pihole_url` and `pihole.written_macs` (now `provider.pihole.written_macs`) and renames the `*_down_since` keys.

## API and metrics
- Metric `janus_pihole_up` is now `janus_provider_up{role}` (`role` = `dhcp` or `dns`). Update dashboards and alerts.
- `/api/cutover` is now `/api/providers/pihole/preflight` (provider routers are mounted at `/api/providers/<kind>`).
- `network.pihole_url` is gone from the settings API; the provider config is read and written through the providers API.
- `status` exposes `dhcp_down_since` (and the DNS counterpart) instead of the Pi-hole specific key.
- `infra.down` / `infra.up` events carry `service` = `dhcp` or `dns` (was `pihole`) plus a `provider` field with the kind.
- `GET /api/features` has a `providers` block per role (kind, label, capabilities, policies, `shared`, `down_since`).
- Approving a device with a policy the DHCP provider does not support returns 409. With no provider, approval answers `enforcement: "no provider"`.

## CLI
- `janus preflight|backup|cutover|rollback` are now registered by the Pi-hole provider through the `cli` hook; usage
  is unchanged. `cutover` refuses when the DHCP role belongs to another provider. `janus sync [--apply]` is generic.

## Adding a provider
- Guide: `docs/providers/adding-a-provider.md`; skeleton: `backend/app/providers/_template/`; contract tests: `backend/tests/providers/test_contract.py`.
