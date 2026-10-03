# Adding a router (network provider)

Janus talks to the network through providers: plugins that live in `backend/app/providers/<kind>/` and are
discovered from the folder. Pi-hole (`pihole/`) is the reference implementation; `_template/` is a minimal skeleton to copy.

## Roles and capabilities

A **role** is a job in the network. Two exist, and each is held by at most one provider at a time:

- `dhcp`: hands out addresses and enforces access per device.
- `dns`: resolves names and, optionally, logs queries.

A **capability** is one thing a provider can do. Each belongs to a role (`CAPABILITY_ROLE`). A provider that holds only
the DNS role never exposes DHCP capabilities, even if its spec declares them (`role_capabilities(spec, role)`).

| Capability | Role | Implement | Turns on |
|---|---|---|---|
| `RESERVATIONS` | dhcp | `ReservationStore`: `list_reservations`, `add_reservation`, `remove_reservation`, `describe` | Sync plan and apply, approval enforcement, per-device policy |
| `FORCE_RENEW` | dhcp | `LeaseControl`: `force_renew(mac, ip)` | Reconnect-now after a change |
| `QUARANTINE` | dhcp | no protocol: the provider itself parks unknown devices in a pool without gateway | Quarantine pages and wording |
| `DHCP_SERVER` | dhcp | no protocol: the provider can take over DHCP (its own `router`/`cli` carry the cutover) | Cutover page, preflight, backup |
| `CLIENT_INVENTORY` | dhcp | no protocol yet: live client list with AP or switch port (your `router` serves it) | Provider clients page |
| `DNS_QUERY_LOG` | dns | `DnsQueryLog`: `query_log(client_ip, since, until, limit)` returns `(list[DnsQuery], total)` | DNS history on a device |
| `DNS_PROBE` | dns | `DnsProbe`: `probe_host()` returns the host to probe, or `None` | Sentinel DNS checks |

Only the capabilities in `CAPABILITY_PROTOCOL` have a protocol the contract test can check; for the others the
declaration is a promise your own `router`, `cli` and frontend pages keep.

## Steps

1. **Copy** `backend/app/providers/_template/` to `backend/app/providers/<kind>/`. The folder name is the `kind`
   and must equal `SPEC.kind`. Rename `template`/`Template` and the `app.providers._template` imports.
2. **Fill `SPEC`** (`__init__.py`, see `ProviderSpec` in `base.py`):
   - `kind`, `label`, `description`, `docs_url`;
   - `roles` and `capabilities` (a DNS role needs `DNS_QUERY_LOG` or `DNS_PROBE`);
   - `policies`, required with `RESERVATIONS` (see below);
   - `config_model`: a pydantic model with the settings of the router;
   - `secret_fields`: names of model fields holding secrets;
   - `env_defaults`: callable returning the config fields taken from the environment (add the env fields to `app/config.py`);
   - `open`: `config -> context manager` yielding a `provider_class` instance (opened per use; share a login if the router
     refuses parallel sessions, as `pihole.open_pihole` does);
   - `provider_class`: the class the contract test inspects;
   - optional `router` and `cli` hooks (below).
3. **Implement the methods** in `provider.py` and `client.py`. Keep the client thin and put the Janus-to-router
   mapping in the provider.
4. **Test with respx**, modelled on `backend/tests/providers/pihole/test_client.py` and `test_provider.py`.
5. **Run** `scripts/test.sh tests/providers`. `tests/providers/test_contract.py` is parametrised over every discovered
   provider; you add nothing to it. It checks that:
   - `kind` matches the folder and `label` is not empty;
   - `config_model(**env_defaults())` validates (only "missing required field" errors are tolerated);
   - every `secret_fields` entry is a model field;
   - a DNS provider declares a DNS capability;
   - `provider_class` implements the protocol of each declared capability that has one;
   - `RESERVATIONS` comes with a non-empty `policies`;
   - CLI command names from `spec.cli` are unique and do not shadow core commands (`sync`, `import-csv`, ...);
   - nothing outside `app/providers/` imports `app.providers.<kind>` (AST scan of `app/**/*.py`).
6. **Optional frontend**: `frontend/providers/<kind>/index.ts` plus a line in `registry.ts` (below).

Discovery needs no registration: restart the backend and the provider appears in Settings.

## Policies

`Policy` is what a device may do: `FULL`, `LAN_ONLY`, `GUEST`, `BLOCKED`. `SPEC.policies` lists those the router can
really enforce, and you map each to a native concept: Pi-hole supports `FULL` (a `dhcp-host` line with the gateway) and
`LAN_ONLY` (a line with a tag that drops the gateway); `BLOCKED` is "no line", so the device lands in the
quarantine pool. For your router decide, per policy, which native object expresses it (a VLAN, a client group, a block flag).

Janus checks `policies` before touching the router: approving a device with an unsupported policy answers 409 with a clear
message, and the frontend hides the option (`lanOnlyAllowed`). Never degrade silently to `FULL`.

## Safety rules

- **Never remove entries Janus does not manage.** `list_reservations` returns every entry; return `reservation=None`
  for one you cannot interpret as Janus' own. The diff reports it and never deletes it. Only entries that are Janus'
  (recognised by the canonical format you write) may be removed. Mark ownership in whatever the router lets you
  write: Pi-hole recognises its own `dhcp-host` line format, UniFi writes `note = "janus:<policy>"` on every client it
  reserves and treats a client without that note as the admin's own.
- Return `canonical=False` for a Janus entry written in an outdated format; it is rewritten.
- Normalise MACs with `app.net.mac.normalize_mac`; never accept duplicate IPs or MACs in what you write.
- Raise `ProviderError`, never raw `httpx` errors. Use `ProviderError(msg, status=4xx)` for a one-off refusal by a
  reachable router (`.rejected` is true: the request failed, the provider is not marked down). Transport errors and
  5xx (anything that is not a 4xx) mark the role down (`infra.down`).
- Set an explicit timeout on every HTTP call (the template uses 10 s). The worker and web requests share this code.
- Do not log secrets. Declare them in `secret_fields`; they are stored encrypted and read back as booleans.
- A provider never imports another provider.

## Hooks

### `router` (extra HTTP API)

Set `SPEC.router` to a FastAPI `APIRouter`; it is mounted at `/api/providers/<kind>` (Pi-hole serves
`/api/providers/pihole/preflight` there). Use it for provider pages: cutover, client lists, diagnostics.

```python
# providers/<kind>/api.py
router = APIRouter(tags=["<kind>"])

@router.get("/clients")                       # served at /api/providers/<kind>/clients
def clients(db: Session = Depends(get_db)) -> list[dict]:
    ...

# __init__.py:  SPEC = ProviderSpec(..., router=api.router)
```

### `cli` (extra commands)

Set `SPEC.cli` to `register(sub)`, which adds subcommands to the `argparse` subparsers of `janus` (`app/cli.py` calls it
for every spec). Each command sets `set_defaults(run=run)`; `run(args) -> int` is the exit code. Pi-hole adds
`preflight`, `backup`, `cutover`, `rollback` this way (`providers/pihole/cli.py`). Names must be unique across providers
and different from the core commands.

```python
# providers/<kind>/cli.py
def register(sub: Any) -> None:
    sub.add_parser("<command>", help="what it does").set_defaults(run=run)

def run(args: argparse.Namespace) -> int:
    ...
    return 0

# __init__.py:  SPEC = ProviderSpec(..., cli=cli.register)
```

### `HealthCheck` (optional protocol)

If `provider_class` has `check(self) -> str`, Settings "Test connection" calls it (`isinstance(provider, HealthCheck)`):
make one cheap authenticated call and return a short human summary, or raise `ProviderError` when the router cannot be
reached. Without it, the button only reports that the provider has no health check. The template has a stub.

## Config, secrets and the generic form

`config_model` is a pydantic model. Settings builds the form from `model_json_schema()` (served by the providers API):
a field per property, `Literal`/enum as a select, `X | None` handled, and fields in `secret_fields` as write-only inputs
(shown as set/unset; empty keeps the saved value). Defaults of secret fields are stripped from the schema because they come from the env.
Values come from `env_defaults()`; what the user changes in Settings is stored in the setting `providers.config`
(secrets encrypted) and wins over the env. A value equal to the env default is not stored, so it keeps following the env.

Choosing providers: `JANUS_DHCP_PROVIDER` and `JANUS_DNS_PROVIDER` (a `kind`, or `none`). Unset, an install with
`JANUS_PIHOLE_PASSWORD` keeps Pi-hole for both roles.

### `same_as` (DNS shared with DHCP)

The DNS role can be `{"same_as": "dhcp"}`: the DNS role *is* the DHCP provider's own config (Pi-hole doing both). It
means one config, one session and nothing that can drift apart; editing one edits both, and the config is marked
`shared`. It works only when the DHCP provider declares `Role.DNS`; otherwise the DNS role is off. A router that serves
DHCP and DNS needs nothing special: declare both roles. A DNS-only provider next to a DHCP one is configured as its own role entry.

## Frontend (optional)

A provider with no frontend code still works: Settings shows the generic form (`frontend/providers/generic-config-form.tsx`)
and no page is added.

For pages create `frontend/providers/<kind>/index.ts` exporting a `ProviderUi` (`types.ts`) and add it to
`PROVIDER_UI` in `frontend/providers/registry.ts`, one line:

```ts
export const PROVIDER_UI: Record<string, ProviderUi> = { pihole, unifi };
```

A `ProviderPage` is `{ slug, label, icon, Component, role, capability? }`, served at `/integrations/<kind>/<slug>`:

- `role` (`"dhcp" | "dns"`) is required: the page is listed only while this provider holds that role. A Pi-hole kept
  for DNS next to another DHCP provider has no cutover page.
- `capability` narrows it further: the provider must offer it *in that role* (per-role capability filtering,
  `providerNav` in `lib/provider-status.ts`).
- Wrap the page body in `ProviderPageGate` (`provider-page-gate.tsx`) so a direct URL shows "not available" when the menu would not list it.
- `SettingsForm` (optional) replaces the generic form with your own component.

Gate the rest of the UI with `features.providers` (`hasCapability`, `lanOnlyAllowed`), never with the provider's name.
