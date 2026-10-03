# Flussi C e D — Provider di rete (Pi-hole come plugin) e UniFi: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (C) Staccare Janus da Pi-hole. Un provider di rete diventa un plugin, scoperto automaticamente da una cartella, che dichiara ruoli (`dhcp`, `dns`), capability e policy supportate. Pi-hole diventa il primo plugin senza perdere alcun comportamento di oggi. Le pagine del sito si adattano al provider scelto. (D) Aggiungere il plugin UniFi: prenotazioni a IP fisso, blocco/sblocco, riconnessione forzata, lista dei client con AP o porta dello switch, eventualmente affiancato a Pi-hole come DNS.

**Architecture:**

```
backend/app/providers/
  __init__.py          # vuoto: è il package che il registro scansiona
  base.py              # Role, Capability, Policy, Reservation, CurrentEntry, DnsQuery, ProviderError, protocolli, ProviderSpec
  registry.py          # discover(): ogni sotto-package senza "_" iniziale che esporta SPEC
  config.py            # configurazione per ruolo (env → default, Setting "providers.config" → override, segreti cifrati)
  runtime.py           # provider_factory(db, role), has_capability(...), features, IP dell'infrastruttura
  README.md            # come si aggiunge un router (in breve; la guida completa è in docs/providers/)
  _template/           # scheletro copiabile, ignorato dalla scoperta
  pihole/              # __init__ (SPEC), client.py, codec.py, provider.py, dns.py, cutover.py, api.py
  unifi/               # __init__ (SPEC), client.py, provider.py, api.py           (flusso D)
backend/app/enforcement/
  reservations.py      # desired_reservations, written/managed MAC per provider, diff_reservations (logica di sicurezza attuale)
  sync.py              # plan_sync / apply_sync generici
frontend/providers/
  types.ts             # ProviderUi, ProviderPage
  registry.ts          # PROVIDER_UI: una riga per provider
  generic-config-form.tsx  # form generato dallo schema JSON del modello di config (nessun codice UI obbligatorio)
  pihole/  index.ts, cutover-page.tsx
  unifi/   index.ts, clients-page.tsx                                          (flusso D)
frontend/app/(app)/integrations/[kind]/[[...slug]]/page.tsx   # pagine specifiche del provider
```

Il diff generico confronta `Reservation` desiderate con `CurrentEntry` lette dal provider. `key` è l'identificativo nativo: per Pi-hole la riga `dhcp-host` grezza, per UniFi l'`_id` del client. `canonical` vale `False` quando la voce è di Janus ma scritta in un formato diverso da quello attuale (lease cambiato, maiuscole); quelle voci vengono riscritte. Le regole di sicurezza di `pihole/reservations.py` passano 1:1: niente IP o MAC duplicati, voci non gestite riportate ma mai rimosse, proprietà iniziale riconosciuta dal formato canonico.

**Tech Stack:** FastAPI, Pydantic v2 (`model_json_schema()` per il form generico), httpx + respx, Next.js 16.

**Spec:** `docs/superpowers/plans/2026-10-03-00-orchestration.md` (requisito 4; decisioni D8, D9, D10; Review Focus 1, 2, 3).

## Global Constraints

- C: branch `feat/providers` da `main` con F. D: branch `feat/unifi` da `main` dopo il merge di C.
- Migrazione **pre-assegnata**: C crea `0008_provider_settings.py` (`down_revision = "0007"`). D non crea migrazioni.
- **Nessun cambiamento di comportamento** per un'installazione Pi-hole esistente: stesso diff, stesse righe `dhcp-host`, stessi eventi (con `service` rinominato, vedi C4).
- `app/pihole/`, `app/cutover.py` e `app/api/cutover.py` spariscono a fine C5: nessuno shim di compatibilità.
- Un provider non importa mai un altro provider; il codice fuori da `providers/` non importa mai `app.providers.<kind>` (solo `base`, `registry`, `config`, `runtime`). C'è un test che lo verifica (C7).

## Review Focus

1. Aggiornamento da `0007`: `pihole.written_macs` → `provider.pihole.written_macs`; `network.config.pihole_url` → override di `providers.config`; le chiavi `*_down_since` rinominate. Dopo l'upgrade, `GET /api/sync/plan` deve dare lo stesso diff di prima. → `test_migration_0008_preserves_written_macs` (C4) e `test_pihole_plan_is_unchanged_after_refactor` (C3).
2. Nessun provider configurato: `reconcile`, `dns`, approvazione e blocco devono funzionare senza errori e senza `infra.down`; l'approvazione risponde `enforcement: "no provider"`. → C5.
3. Cambio del provider `dhcp` in `apply` → `sync_mode` torna `dry-run`, e i `written_macs` del vecchio provider non vengono usati per il nuovo. → C4.
4. Policy non supportata: approvare `lan_only` con UniFi deve dare 409 con un messaggio chiaro, mai una prenotazione `full` silenziosa. Il frontend nasconde l'opzione. → C5 (`test_approve_with_unsupported_policy_is_409`) e D2.
5. Provider configurato ma irraggiungibile all'avvio del worker: un `ProviderError` produce `infra.down` con `service="dhcp"`; un'eccezione di config (modello non valido salvato in passato) produce un log e `infra.down`, senza far cadere il loop. → C5.
6. Pi-hole DNS+DHCP (default) e Pi-hole solo DNS accanto a UniFi: nel primo caso una sola config e una sola sessione per entrambi i ruoli; nel secondo il sito non mostra quarantena né cutover, e il cutover si rifiuta di accendere il DHCP di Pi-hole. → C4 (`test_pihole_dns_and_dhcp_share_one_config`, `test_role_ref_only_exposes_capabilities_of_that_role`, `test_switching_dhcp_away_from_pihole_keeps_pihole_as_dns`), C3 (`test_cutover_refused_when_pihole_is_dns_only`), C6 (`providerNav`).

---

## Parte C — Astrazione e Pi-hole come plugin

### Task C1: Contratti e registro con scoperta automatica

**Files:**
- Create: `backend/app/providers/__init__.py` (vuoto), `backend/app/providers/base.py`, `backend/app/providers/registry.py`, `backend/tests/providers/__init__.py`, `backend/tests/providers/fixture_pkg/__init__.py`, `backend/tests/providers/fixture_pkg/demo/__init__.py`, `backend/tests/providers/fixture_pkg/_hidden/__init__.py`, `backend/tests/providers/test_registry.py`

**Interfaces:**
- Produces (in `base.py`, i nomi esatti che tutti i task successivi usano):

```python
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from fastapi import APIRouter
from pydantic import BaseModel


class Role(StrEnum):
    DHCP = "dhcp"
    DNS = "dns"


class Capability(StrEnum):
    RESERVATIONS = "reservations"          # per-MAC reservations with an access policy
    FORCE_RENEW = "force_renew"            # make a device ask for a new lease now
    QUARANTINE = "quarantine"              # unknown devices land in a pool without a gateway
    DHCP_SERVER = "dhcp_server"            # the provider can take over DHCP (cutover/preflight/backup)
    DNS_QUERY_LOG = "dns_query_log"
    DNS_PROBE = "dns_probe"                # the sentinel can probe this DNS server
    CLIENT_INVENTORY = "client_inventory"  # live client list with AP / switch port


class Policy(StrEnum):
    FULL = "full"
    LAN_ONLY = "lan_only"
    GUEST = "guest"
    BLOCKED = "blocked"


@dataclass(frozen=True, order=True)
class Reservation:
    mac: str            # normalized, upper-case, colon-separated (app.net.mac.normalize_mac)
    hostname: str
    ip: str | None = None
    policy: Policy = Policy.FULL


@dataclass(frozen=True)
class CurrentEntry:
    key: str                         # native identifier: raw dhcp-host line, UniFi _id, ...
    display: str                     # what the UI and logs show
    mac: str | None
    ip: str | None
    reservation: Reservation | None  # None: not a reservation Janus can read (unmanaged)
    canonical: bool = True           # False: Janus' entry in an outdated format; rewrite it


@dataclass(frozen=True)
class DnsQuery:
    time: float
    domain: str
    qtype: str
    blocked: bool
    status: str
    reply: str | None
    client_ip: str


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status

    @property
    def rejected(self) -> bool:
        """The provider refused this one request (4xx); it is reachable."""
        return self.status is not None and 400 <= self.status < 500


@runtime_checkable
class ReservationStore(Protocol):
    def list_reservations(self) -> list[CurrentEntry]: ...
    def add_reservation(self, reservation: Reservation) -> None: ...
    def remove_reservation(self, entry: CurrentEntry) -> None: ...
    def describe(self, reservation: Reservation) -> str: ...


@runtime_checkable
class LeaseControl(Protocol):
    def force_renew(self, mac: str, ip: str | None) -> None: ...


@runtime_checkable
class DnsQueryLog(Protocol):
    def query_log(self, client_ip: str, since: int, until: int, limit: int = 5000) -> tuple[list[DnsQuery], int]: ...


@runtime_checkable
class DnsProbe(Protocol):
    def probe_host(self) -> str | None: ...


@runtime_checkable
class HealthCheck(Protocol):
    def check(self) -> str: ...   # short human summary; raises ProviderError when unreachable


# Which role a capability belongs to: a provider that holds only the DNS role never exposes DHCP capabilities.
CAPABILITY_ROLE: dict[Capability, Role] = {
    Capability.RESERVATIONS: Role.DHCP,
    Capability.FORCE_RENEW: Role.DHCP,
    Capability.QUARANTINE: Role.DHCP,
    Capability.DHCP_SERVER: Role.DHCP,
    Capability.CLIENT_INVENTORY: Role.DHCP,
    Capability.DNS_QUERY_LOG: Role.DNS,
    Capability.DNS_PROBE: Role.DNS,
}


def role_capabilities(spec: "ProviderSpec", role: Role) -> frozenset[Capability]:
    return frozenset(c for c in spec.capabilities if CAPABILITY_ROLE[c] is role)


CAPABILITY_PROTOCOL: dict[Capability, type] = {
    Capability.RESERVATIONS: ReservationStore,
    Capability.FORCE_RENEW: LeaseControl,
    Capability.DNS_QUERY_LOG: DnsQueryLog,
    Capability.DNS_PROBE: DnsProbe,
}


@dataclass(frozen=True)
class ProviderSpec:
    kind: str                                   # == folder name
    label: str
    roles: frozenset[Role]
    capabilities: frozenset[Capability]
    config_model: type[BaseModel]
    open: Callable[[Any], AbstractContextManager[Any]]   # config instance -> provider instance
    provider_class: type | None = None          # checked by the contract test (C7)
    policies: frozenset[Policy] = frozenset()
    secret_fields: frozenset[str] = frozenset()
    env_defaults: Callable[[], dict[str, Any]] = dict
    router: APIRouter | None = None             # mounted at /api/providers/<kind>
    description: str = ""
    docs_url: str = ""
```

- Produces (in `registry.py`): `discover(package: ModuleType | None = None) -> dict[str, ProviderSpec]` (risultato in cache se `package is None`), `get_spec(kind: str) -> ProviderSpec` (`UnknownProvider(KeyError)`), `all_specs() -> list[ProviderSpec]` ordinati per `label`, `RegistryError(RuntimeError)`, e `override(extra: dict[str, ProviderSpec]) -> ContextManager[None]`, un hook di test che aggiunge spec finte a quelle scoperte per la durata del `with`.

- [ ] **Step 1: Test che fallisce**

```python
# backend/tests/providers/fixture_pkg/demo/__init__.py
from contextlib import nullcontext

from pydantic import BaseModel

from app.providers.base import Capability, Policy, ProviderSpec, Role


class DemoConfig(BaseModel):
    url: str = ""


SPEC = ProviderSpec(kind="demo", label="Demo router", roles=frozenset({Role.DHCP}),
                    capabilities=frozenset({Capability.RESERVATIONS}), config_model=DemoConfig,
                    open=lambda cfg: nullcontext(object()), policies=frozenset({Policy.FULL}))
```

```python
# backend/tests/providers/fixture_pkg/_hidden/__init__.py
raise AssertionError("underscore packages must never be imported")
```

```python
# backend/tests/providers/test_registry.py
import pytest

from app.providers import registry
from tests.providers import fixture_pkg


def test_discovers_packages_and_skips_underscored_ones():
    specs = registry.discover(fixture_pkg)
    assert list(specs) == ["demo"]
    assert specs["demo"].label == "Demo router"


def test_kind_must_match_folder(monkeypatch):
    import tests.providers.fixture_pkg.demo as demo
    monkeypatch.setattr(demo, "SPEC", demo.SPEC.__class__(**{**demo.SPEC.__dict__, "kind": "other"}))
    with pytest.raises(registry.RegistryError, match="demo"):
        registry.discover(fixture_pkg)


def test_override_adds_fakes_temporarily():
    demo = registry.discover(fixture_pkg)["demo"]
    with registry.override({"demo": demo}):
        assert registry.get_spec("demo") is demo
    with pytest.raises(registry.UnknownProvider):
        registry.get_spec("demo")


def test_unknown_kind():
    with pytest.raises(registry.UnknownProvider):
        registry.get_spec("does-not-exist")
```

- [ ] **Step 2: Verificare che fallisca** — Run: `scripts/test.sh tests/providers/test_registry.py -v` → FAIL (`No module named 'app.providers'`)

- [ ] **Step 3: Implementazione** — `base.py` come sopra. `registry.py`:

```python
import importlib
import pkgutil
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache
from types import ModuleType

from app.providers.base import ProviderSpec


class RegistryError(RuntimeError):
    pass


class UnknownProvider(KeyError):
    pass


def discover(package: ModuleType | None = None) -> dict[str, ProviderSpec]:
    if package is None:
        return _discover_default()
    specs: dict[str, ProviderSpec] = {}
    for info in pkgutil.iter_modules(package.__path__):
        if not info.ispkg or info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package.__name__}.{info.name}")
        spec = getattr(module, "SPEC", None)
        if not isinstance(spec, ProviderSpec):
            continue
        if spec.kind != info.name:
            raise RegistryError(f"provider folder {info.name!r} declares kind {spec.kind!r}")
        specs[spec.kind] = spec
    return dict(sorted(specs.items()))


@cache
def _discover_default() -> dict[str, ProviderSpec]:
    import app.providers
    return discover(app.providers)


_extra: dict[str, ProviderSpec] = {}


@contextmanager
def override(extra: dict[str, ProviderSpec]) -> Iterator[None]:
    """Tests only: register fake providers on top of the discovered ones."""
    _extra.update(extra)
    try:
        yield
    finally:
        for kind in extra:
            _extra.pop(kind, None)


def _all() -> dict[str, ProviderSpec]:
    return {**_discover_default(), **_extra}


def get_spec(kind: str) -> ProviderSpec:
    try:
        return _all()[kind]
    except KeyError:
        raise UnknownProvider(kind) from None


def all_specs() -> list[ProviderSpec]:
    return sorted(_all().values(), key=lambda s: s.label)
```

- [ ] **Step 4: Verificare che passi** — Run: `scripts/test.sh tests/providers/test_registry.py -v` → 4 passed

- [ ] **Step 5: Commit** — `git commit -m "feat(providers): provider contracts and folder-based registry"`

### Task C2: Motore di prenotazioni generico

**Files:**
- Create: `backend/app/enforcement/__init__.py`, `backend/app/enforcement/reservations.py`, `backend/app/enforcement/sync.py`, `backend/tests/fakes_provider.py`, `backend/tests/test_enforcement.py`
- (Non toccare ancora `app/pihole/`: lo sostituisce C3.)

**Interfaces:**
- Consumes: `base.*` (C1)
- Produces:
  - `desired_reservations(db, policies: frozenset[Policy]) -> set[Reservation]`. `authorized` → FULL, `lan_only` → LAN_ONLY (entrambi richiedono `mac` e `static_ip`); `blocked` → BLOCKED (senza IP) solo se `BLOCKED in policies`. Il flusso E aggiungerà `guest` → GUEST. Le policy non in `policies` vengono **escluse** qui; il rifiuto esplicito avviene all'approvazione (C5).
  - `written_key(kind) -> str` = `f"provider.{kind}.written_macs"`; `written_macs(db, kind) -> set[str] | None`; `remember_written(db, kind, macs)`
  - `managed_macs(db, kind, current: list[CurrentEntry]) -> set[str]`: MAC dei device noti ∪ MAC scritti. Al primo giro i MAC scritti sono le voci con `reservation is not None and canonical`.
  - `ReservationDiff(to_add: list[Reservation], to_remove: list[CurrentEntry], unmanaged: list[CurrentEntry], failed: list[str])` con `.empty` e `.as_dict(describe: Callable[[Reservation], str])`, che produce `{"to_add": [describe(r)], "to_remove": [e.display], "unmanaged": [e.display], "failed": [...]}`. Per Pi-hole il risultato è identico all'`as_dict()` di oggi.
  - `diff_reservations(desired, current, managed) -> ReservationDiff`
  - `plan_sync(db, store: ReservationStore, kind: str, policies) -> ReservationDiff`; `apply_sync(db, store, kind, policies) -> ReservationDiff` (stessi eventi `sync.applied` e `sync.failed` di oggi; cattura `ProviderError` con `.rejected` voce per voce e rilancia gli altri)
  - `tests/fakes_provider.py`: `FakeStore(entries=None, *, fail=False, reject: set[str] = set() (MAC delle aggiunte da rifiutare con ProviderError status=400), drop_after_writes=None)`, che implementa `ReservationStore` + `LeaseControl` e registra `writes: list[tuple[str, str]]`. Le voci che crea hanno `key = f"{mac},{ip or ''},{hostname},{policy}"`.

- [ ] **Step 1: Test che fallisce** — Portare **ogni** test di `tests/test_reservations.py` che riguarda `desired_hosts`, `managed_macs`, `diff_hosts`, `plan_sync`, `apply_sync` in `tests/test_enforcement.py`, con `Reservation` e `FakeStore` al posto di `HostLine` e `FakePihole`. I test di `render`/`parse` restano per C3. Esempi da includere letteralmente:

```python
# backend/tests/test_enforcement.py
from app.enforcement.reservations import desired_reservations, diff_reservations, managed_macs, written_macs
from app.enforcement.sync import apply_sync, plan_sync
from app.models import Access, Device, Event, Group
from app.providers.base import CurrentEntry, Policy, ProviderError, Reservation
from tests.fakes_provider import FakeStore

ALL = frozenset(Policy)


def _group(db, name="People", start="192.168.1.10", end="192.168.1.19"):
    g = Group(name=name, color="#6FB7FF", icon="device", range_start=start, range_end=end, default_access=Access.authorized)
    db.add(g)
    db.flush()
    return g


def _device(db, group, name, mac, ip, access=Access.authorized):
    d = Device(mac=mac, name=name, hostname=name.lower().replace("_", "-"), group=group, static_ip=ip, access=access)
    db.add(d)
    db.flush()
    return d


def _entry(mac, ip, host, policy=Policy.FULL, *, canonical=True, key=None):
    r = Reservation(mac, host, ip, policy)
    return CurrentEntry(key or f"{mac},{ip},{host}", key or f"{mac},{ip},{host}", mac, ip, r, canonical)


def test_desired_maps_access_to_policy_and_drops_unsupported(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    _device(db, g, "PLUG", "00:00:5E:00:53:20", "192.168.1.11", Access.lan_only)
    _device(db, g, "BAD", "00:00:5E:00:53:30", None, Access.blocked)
    assert desired_reservations(db, ALL) == {
        Reservation("00:00:5E:00:53:10", "laptop-a", "192.168.1.10", Policy.FULL),
        Reservation("00:00:5E:00:53:20", "plug", "192.168.1.11", Policy.LAN_ONLY),
        Reservation("00:00:5E:00:53:30", "bad", None, Policy.BLOCKED),
    }
    assert {r.policy for r in desired_reservations(db, frozenset({Policy.FULL}))} == {Policy.FULL}


def test_unmanaged_entries_are_reported_never_removed(db):
    stranger = _entry("00:00:5E:00:53:99", "192.168.1.99", "nas")
    diff = diff_reservations(set(), [stranger], managed=set())
    assert diff.to_remove == [] and diff.unmanaged == [stranger]


def test_duplicate_ip_with_unmanaged_entry_is_refused(db):
    stranger = _entry("00:00:5E:00:53:99", "192.168.1.10", "nas")
    want = Reservation("00:00:5E:00:53:10", "laptop-a", "192.168.1.10")
    diff = diff_reservations({want}, [stranger], managed=set())
    assert diff.to_add == [] and "would duplicate" in diff.failed[0]


def test_non_canonical_own_entry_is_rewritten(db):
    want = Reservation("00:00:5E:00:53:10", "laptop-a", "192.168.1.10")
    old = _entry("00:00:5E:00:53:10", "192.168.1.10", "laptop-a", canonical=False, key="old-format")
    diff = diff_reservations({want}, [old], managed={"00:00:5E:00:53:10"})
    assert [e.key for e in diff.to_remove] == ["old-format"] and diff.to_add == [want]


def test_written_macs_are_per_provider(db):
    store = FakeStore([_entry("00:00:5E:00:53:10", "192.168.1.10", "laptop-a")])
    managed_macs(db, "pihole", store.list_reservations())
    assert written_macs(db, "pihole") == {"00:00:5E:00:53:10"}
    assert written_macs(db, "unifi") is None


def test_apply_records_rejections_and_keeps_going(db):
    g = _group(db)
    _device(db, g, "LAPTOP_A", "00:00:5E:00:53:10", "192.168.1.10")
    _device(db, g, "LAPTOP_B", "00:00:5E:00:53:11", "192.168.1.11")
    store = FakeStore(reject={"00:00:5E:00:53:10"})
    diff = apply_sync(db, store, "fake", ALL)
    assert len(diff.failed) == 1 and [w[0] for w in store.writes] == ["add"]
```

- [ ] **Step 2: Verificare che fallisca** — Run: `scripts/test.sh tests/test_enforcement.py -v` → FAIL (modulo mancante)

- [ ] **Step 3: Implementazione** — Trasporre `pihole/reservations.py` e `pihole/sync.py` sostituendo:
  - `HostLine` → `Reservation`, e la riga grezza → `CurrentEntry` (`key` per rimuovere, `display` per riportare);
  - `HostLine.parse(raw)` → `entry.reservation`, e `_identity(raw)` → `(entry.mac, entry.ip)`;
  - il controllo di proprietà iniziale `parsed.render() == raw and parsed.lease == lease` → `entry.reservation is not None and entry.canonical`;
  - in `diff_reservations` una voce gestita resta solo se `entry.canonical and entry.reservation in desired`;
  - i controlli di duplicato su IP valgono solo quando `ip is not None` (le prenotazioni GUEST/BLOCKED non hanno IP);
  - `PiholeError` → `ProviderError`;
  - `client.add_host(h.render())` → `store.add_reservation(r)`, e `client.remove_host(raw)` → `store.remove_reservation(entry)`;
  - il payload degli eventi `sync.applied`/`sync.failed`: stessi campi di oggi, con le stringhe ottenute da `store.describe(r)` ed `entry.display`.

  Lo stesso commento di docstring di `diff_hosts` va mantenuto (spiega il perché del rifiuto dei duplicati). Esempio della funzione chiave:

```python
def diff_reservations(desired: set[Reservation], current: list[CurrentEntry], managed: set[str] | None = None) -> ReservationDiff:
    """Entries Janus does not manage (MAC neither known nor written by Janus) are reported, never removed.

    An addition that would give the provider two reservations with the same IP or MAC is refused and reported in
    `failed`: dnsmasq (and most routers) reject such a configuration, and dnsmasq stops answering DNS."""
    diff = ReservationDiff()
    own: list[CurrentEntry] = []
    for entry in current:
        if entry.reservation is None or (managed is not None and entry.mac not in managed):
            diff.unmanaged.append(entry)
        else:
            own.append(entry)
    keep = [e for e in own if e.canonical and e.reservation in desired]
    diff.to_remove = sorted((e for e in own if e not in keep), key=lambda e: e.key)
    taken_ips = {e.ip: e.display for e in keep + diff.unmanaged if e.ip}
    taken_macs = {e.mac: e.display for e in keep + diff.unmanaged if e.mac}
    present = {e.reservation for e in keep}
    for r in sorted(desired - present):
        clash = (taken_ips.get(r.ip) if r.ip else None) or taken_macs.get(r.mac)
        if clash is not None:
            diff.failed.append(f"{r.mac} {r.ip or ''} {r.hostname}: would duplicate {clash}, skipped")
            continue
        diff.to_add.append(r)
        if r.ip:
            taken_ips[r.ip] = r.hostname
        taken_macs[r.mac] = r.hostname
    return diff
```

  Attenzione: oggi il messaggio di `failed` contiene la riga renderizzata. Per non cambiare il testo per Pi-hole, `diff_reservations` accetta anche `describe: Callable[[Reservation], str] | None = None` e la usa quando c'è; `plan_sync` passa `store.describe`.

- [ ] **Step 4: Verificare che passi** — Run: `scripts/test.sh tests/test_enforcement.py -v` → tutto passa

- [ ] **Step 5: Commit** — `git commit -m "feat(enforcement): provider-neutral reservation diff and sync"`

### Task C3: Il plugin Pi-hole

**Files:**
- Create: `backend/app/providers/pihole/__init__.py`, `client.py` (spostato da `app/pihole/client.py`), `codec.py`, `provider.py`, `dns.py`, `cutover.py` (spostato da `app/cutover.py`), `api.py` (contenuto di `app/api/cutover.py`)
- Move tests: `tests/test_pihole_client.py` → `tests/providers/pihole/test_client.py`; la parte codec di `tests/test_reservations.py` → `tests/providers/pihole/test_codec.py`; `tests/test_cutover.py` → `tests/providers/pihole/test_cutover.py`; creare `tests/providers/pihole/test_provider.py`
- Modify: `tests/fakes.py` (`FakePihole` solleva `app.providers.pihole.client.PiholeError`)

**Interfaces:**
- Consumes: `base.*`, `enforcement.*` (C1, C2)
- Produces:
  - `client.PiholeError(ProviderError)`. L'API pubblica di `PiholeClient` resta invariata.
  - `codec.LAN_ONLY_TAG = "set:lanonly"`; `codec.render(r: Reservation, lease: str) -> str` produce `mac[,set:lanonly],ip,hostname,lease`, **identico a oggi**, con il MAC in minuscolo; `codec.parse(raw: str, lease: str) -> CurrentEntry`, dove `canonical = render(parsed, lease) == raw`, la riga non riconosciuta dà `reservation=None` e `mac`/`ip` vengono estratti come fa `_identity` oggi.
  - `provider.PiholeConfig(BaseModel)`: `url: str`, `password: str = ""`, `lease: str = "24h"`
  - `provider.PiholeProvider(client: PiholeClient-like, config: PiholeConfig)`: context manager che implementa `ReservationStore`, `LeaseControl` (`force_renew(mac, ip)` → `revoke_lease(ip)` se `ip`), `DnsQueryLog`, `DnsProbe` (`probe_host()` restituisce l'host di `config.url`) e `HealthCheck` (`check()` chiama `list_hosts()` e restituisce `"{n} reservations"`).
  - `dns.normalize(raw: dict) -> DnsQuery` (insieme `BLOCKED` spostato qui da `intel/dns.py`)
  - `SPEC = ProviderSpec(kind="pihole", label="Pi-hole", roles={DHCP, DNS}, capabilities={RESERVATIONS, FORCE_RENEW, QUARANTINE, DHCP_SERVER, DNS_QUERY_LOG, DNS_PROBE}, policies={FULL, LAN_ONLY}, provider_class=PiholeProvider, secret_fields={"password"}, env_defaults=lambda: {"url": settings.pihole_url, "password": settings.pihole_password, "lease": settings.reservation_lease}, open=open_pihole, router=api.router, docs_url="https://docs.pi-hole.net/api/")`
  - `open_pihole(cfg) -> PiholeProvider`, che usa `shared_session(cfg.url)` come fa oggi `get_pihole_factory`
  - `api.router`: `GET /preflight`, montato a `/api/providers/pihole/preflight`. Il frontend passerà a questa rotta (C6). Il preflight ha un controllo in più, `pihole_is_dhcp_provider`: se il ruolo `dhcp` non è questo Pi-hole (es. UniFi fa il DHCP e il Pi-hole solo DNS), il controllo fallisce e `cli.py cutover` si rifiuta di partire. Accendere il DHCP di Pi-hole accanto a quello del router metterebbe due server DHCP sulla stessa LAN. Test: `test_cutover_refused_when_pihole_is_dns_only` in `tests/providers/pihole/test_cutover.py`.

- [ ] **Step 1: Test che fallisce**

```python
# backend/tests/providers/pihole/test_provider.py
from app.enforcement.sync import plan_sync
from app.models import Access, Device, Group
from app.providers.base import Capability, DnsProbe, DnsQueryLog, LeaseControl, Policy, ReservationStore
from app.providers.pihole import SPEC
from app.providers.pihole.codec import parse, render
from app.providers.pihole.provider import PiholeConfig, PiholeProvider
from app.providers.base import Reservation
from tests.fakes import FakePihole

CFG = PiholeConfig(url="http://192.168.1.220:1000", password="pw", lease="24h")


def test_spec_declares_what_the_provider_implements():
    p = PiholeProvider(FakePihole(), CFG)
    for proto in (ReservationStore, LeaseControl, DnsQueryLog, DnsProbe):
        assert isinstance(p, proto)
    assert Capability.QUARANTINE in SPEC.capabilities and SPEC.policies == {Policy.FULL, Policy.LAN_ONLY}


def test_codec_round_trip_is_byte_identical_to_before():
    lan = Reservation("00:00:5E:00:53:20", "plug", "192.168.1.120", Policy.LAN_ONLY)
    assert render(lan, "24h") == "00:00:5e:00:53:20,set:lanonly,192.168.1.120,plug,24h"
    assert parse(render(lan, "24h"), "24h").reservation == lan
    assert parse("00:00:5e:00:53:20,set:lanonly,192.168.1.120,plug,12h", "24h").canonical is False
    stranger = parse("not,a,reservation", "24h")
    assert stranger.reservation is None


def test_pihole_plan_is_unchanged_after_refactor(db):
    g = Group(name="People", color="#6FB7FF", icon="device", range_start="192.168.1.10", range_end="192.168.1.19",
              default_access=Access.authorized)
    db.add(g)
    db.flush()
    db.add(Device(mac="00:00:5E:00:53:10", name="LAPTOP_A", hostname="laptop-a", group=g, static_ip="192.168.1.10",
                  access=Access.authorized))
    db.flush()
    fake = FakePihole(hosts=["00:00:5e:00:53:99,192.168.1.99,nas,24h", "00:00:5E:00:53:10,192.168.1.10,laptop-a,12h"])
    diff = plan_sync(db, PiholeProvider(fake, CFG), "pihole", SPEC.policies)
    store = PiholeProvider(fake, CFG)
    assert diff.as_dict(store.describe) == {
        "to_add": ["00:00:5e:00:53:10,192.168.1.10,laptop-a,24h"],
        "to_remove": ["00:00:5E:00:53:10,192.168.1.10,laptop-a,12h"],
        "unmanaged": ["00:00:5e:00:53:99,192.168.1.99,nas,24h"],
        "failed": [],
    }


def test_force_renew_revokes_the_lease_by_ip():
    fake = FakePihole()
    PiholeProvider(fake, CFG).force_renew("00:00:5E:00:53:10", "192.168.1.241")
    assert fake.writes == [("revoke", "192.168.1.241")]


def test_query_log_is_normalized():
    fake = FakePihole()
    fake.queries = [{"time": 100.0, "domain": "ads.example", "type": "A", "status": "GRAVITY",
                     "reply": {"type": "IP"}, "client": {"ip": "192.168.1.10"}}]
    [q], total = PiholeProvider(fake, CFG).query_log("192.168.1.10", 0, 200)
    assert (q.domain, q.blocked, q.reply, total) == ("ads.example", True, "IP", 1)
```

Prima di scrivere `test_pihole_plan_is_unchanged_after_refactor`, eseguire lo stesso scenario sul codice **attuale** (`app.pihole.sync.plan_sync`) e copiare nel test l'output reale di `as_dict()`. Il dizionario sopra è quello atteso; se differisce, vince l'output reale.

- [ ] **Step 2: Verificare che fallisca** — Run: `scripts/test.sh tests/providers/pihole -v` → FAIL

- [ ] **Step 3: Implementazione** — `git mv` dei file da spostare (la cronologia si conserva). In `codec.py` va la logica di `HostLine.render/parse` e di `_identity`. `PiholeProvider.list_reservations()` restituisce `[parse(raw, cfg.lease) for raw in client.list_hosts()]`; `add_reservation(r)` chiama `client.add_host(render(r, cfg.lease))`; `remove_reservation(e)` chiama `client.remove_host(e.key)`; `describe(r)` restituisce `render(r, cfg.lease)`. `__enter__` ed `__exit__` delegano al client. In `cutover.py` gli import vanno aggiornati: `apply_sync` da `app.enforcement.sync`, con `PiholeProvider(admin, cfg)` come store e `SPEC.policies`. `PiholeAdmin` resta qui. In `intel/dns.py`, `analyze` accetta `list[DnsQuery]` e usa `q.blocked`, `q.domain`, `q.time`, `q.qtype`, `q.reply` al posto delle chiavi dei dict; `is_blocked` e `BLOCKED` vanno tolti da lì.

- [ ] **Step 4: Verificare che passi** — Run: `scripts/test.sh tests/providers -v && scripts/test.sh tests/test_dns_analysis.py -v` (adattare `test_dns_analysis.py` a `DnsQuery`)

- [ ] **Step 5: Commit** — `git commit -m "refactor(pihole): Pi-hole becomes the first network provider plugin"`

### Task C4: Configurazione per ruolo, API `/api/providers`, migrazione 0008, feature `providers`

**Files:**
- Create: `backend/app/providers/config.py`, `backend/app/providers/runtime.py`, `backend/app/api/providers.py`, `backend/migrations/versions/0008_provider_settings.py`
- Modify: `backend/app/config.py` (blocco `# --- C ---`: `dhcp_provider: str = ""`, `dns_provider: str = ""`; `pihole_url: str = ""`, senza più il default hardcoded), `backend/app/features.py` (riga `"providers"`), `backend/app/main.py` (router `providers` e router dei singoli provider)
- Test: `backend/tests/test_provider_config.py`, `backend/tests/test_api_providers.py`, `backend/tests/test_migrations.py` (nuovo caso)

**Interfaces:**
- Consumes: `registry`, `secretbox` (F1), `syncmode.set_sync_mode` (esistente)
- Produces:
  - `config.KEY = "providers.config"`. Formato: `{"dhcp": {"kind": "pihole", "config": {override...}} | None, "dns": {"same_as": "dhcp"} | {"kind": …, "config": …} | None}`. Ruolo assente = default env; `None` = disattivato esplicitamente; `{"same_as": "dhcp"}` = il DNS è **lo stesso apparato** del DHCP (caso Pi-hole DNS+DHCP).
  - **Caso Pi-hole DNS + DHCP (default di oggi).** Il ruolo `dns` non ha una config propria: `load_role(db, DNS)` restituisce la `RoleConfig` del DHCP (stesso URL, stessa password, stesso `kind`) con `shared=True`. Così cambiare URL o password del Pi-hole in Settings vale per entrambi i ruoli, non esistono due copie che possono divergere, e una sola sessione Pi-hole (`shared_session(url)`) serve DHCP e DNS: Pi-hole rifiuta i login paralleli. `same_as` è permesso solo se il provider DHCP dichiara anche `Role.DNS`. Se si cambia il provider DHCP verso uno senza DNS (es. UniFi), `save_role` converte `same_as` in una config DNS esplicita del vecchio provider (il Pi-hole resta il DNS) e registra `{"dns_detached": true}` nell'evento `settings.providers`.
  - `config.env_kind(role) -> str | None`: legge `settings.dhcp_provider` o `settings.dns_provider`; `"none"` → `None`; `""` → `"pihole"` se `settings.pihole_password` è impostato, altrimenti `None`. È la compatibilità con le installazioni di oggi.
  - `config.RoleConfig(kind: str, spec: ProviderSpec, config: BaseModel, source: Literal["env","custom"], shared: bool = False)`
  - Default env: se `env_kind(DHCP) == env_kind(DNS)`, il ruolo DNS vale `same_as: "dhcp"` implicito.
  - `config.load_role(db, role) -> RoleConfig | None`. Una config salvata non valida per il modello viene loggata, poi la funzione ripiega sui default env del provider; se anche quelli non validano, restituisce `None` e logga.
  - `config.view_role(db, role) -> dict | None`: `{kind, label, source, config: {…, segreti → bool}, schema: model_json_schema(), secret_fields: [...]}`
  - `config.save_role(db, role, kind: str | None, patch: dict | None, *, same_as: Role | None = None) -> RoleConfig | None` (`same_as` solo per `role is DNS`). Valida con il `config_model`; cifra i campi in `secret_fields` (un valore assente o `None` per un segreto lo mantiene). Se `role is DHCP` e il `kind` cambia, chiama `set_sync_mode(db, "dry-run")` (D9) e registra `settings.providers` con `{role, kind_before, kind_after, forced_dry_run: bool}`. Rifiuta con `ConfigError(ValueError)` un `kind` che non supporta quel ruolo.
  - `runtime.provider_factory(db, role) -> Callable[[], AbstractContextManager[Any]] | None`
  - `runtime.has_capability(db, role, cap) -> bool`; `runtime.policies(db) -> frozenset[Policy]` (quelle del provider `dhcp`, vuoto se non c'è)
  - `runtime.role_ref(db, role) -> dict | None`: `{kind, label, capabilities: [...], policies: [...], shared: bool, down_since}`, con `down_since` letto da `Setting f"{role}.down_since"`. **`capabilities` = `role_capabilities(spec, role)`**: un Pi-hole che fa solo DNS accanto a UniFi non espone `quarantine`, `dhcp_server` né `reservations`, quindi il sito non mostra quarantena né cutover. `policies` compare solo per il ruolo DHCP.
  - `runtime.infrastructure_ips(db) -> set[str]`: host IPv4 dei campi `url` delle config attive. Sostituisce l'uso di `pihole_url` in `api/groups.py:_pinned_ips`.
  - `features["providers"] = lambda db: {"dhcp": role_ref(db, Role.DHCP), "dns": role_ref(db, Role.DNS)}`
  - API:
    - `GET /api/providers` → `{"available": [{kind, label, description, docs_url, roles, capabilities, policies, schema, secret_fields}], "roles": {"dhcp": view|None, "dns": view|None}}`
    - `PUT /api/providers/{role}` con corpo `{"kind": str|null, "config": {...}|null, "same_as": "dhcp"|null}` → `view_role`; 422 su `ConfigError` o `ValidationError` (messaggio `"campo: …"`)
    - `POST /api/providers/{role}/test` → `{"ok": bool, "detail": str}` (chiama `check()`; un `ProviderError` dà `ok=false`)
  - `main.py`: per ogni `spec in registry.all_specs()` con `spec.router`, `include_router(spec.router, prefix=f"/api/providers/{spec.kind}", dependencies=[Depends(require_internal)])`
  - Migrazione `0008` (solo dati, nessuna tabella):
    - `pihole.written_macs` → `provider.pihole.written_macs`
    - `pihole.down_since` → `dhcp.down_since`
    - `pihole_dns.down_since` → `dns.down_since`
    - `pihole_dns.last_ok` → `dns.last_ok`
    - se `network.config` contiene `pihole_url`, lo toglie da lì e scrive `providers.config = {"dhcp": {"kind": "pihole", "config": {"url": …}}, "dns": {"same_as": "dhcp"}}`
    - `downgrade()` fa l'inverso

- [ ] **Step 1: Test che fallisce**

```python
# backend/tests/test_provider_config.py
import pytest

from app.config import settings
from app.models import Setting
from app.providers import config as pc
from app.providers.base import Role
from app.syncmode import load_sync_mode, set_sync_mode


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "internal_token", "test-token")
    monkeypatch.setattr(settings, "dhcp_provider", "")
    monkeypatch.setattr(settings, "dns_provider", "")
    monkeypatch.setattr(settings, "pihole_url", "http://192.168.1.220:1000")
    monkeypatch.setattr(settings, "pihole_password", "pw")


def test_existing_install_defaults_to_pihole_for_both_roles(db):
    for role in Role:
        rc = pc.load_role(db, role)
        assert rc.kind == "pihole" and rc.source == "env" and rc.config.url == "http://192.168.1.220:1000"


def test_no_pihole_password_and_no_env_means_no_provider(db, monkeypatch):
    monkeypatch.setattr(settings, "pihole_password", "")
    assert pc.load_role(db, Role.DHCP) is None


def _demo():
    from app.providers import registry
    from tests.providers import fixture_pkg
    return registry.override({"demo": registry.discover(fixture_pkg)["demo"]})


def test_pihole_dns_and_dhcp_share_one_config(db):
    pc.save_role(db, Role.DHCP, "pihole", {"url": "http://10.0.0.2", "password": "pw2"})
    dns = pc.load_role(db, Role.DNS)
    assert dns.shared and dns.kind == "pihole" and dns.config.url == "http://10.0.0.2" and dns.config.password == "pw2"


def test_role_ref_only_exposes_capabilities_of_that_role(db):
    from app.providers.runtime import role_ref
    dhcp, dns = role_ref(db, Role.DHCP), role_ref(db, Role.DNS)
    assert {"reservations", "quarantine", "dhcp_server"} <= set(dhcp["capabilities"])
    assert set(dns["capabilities"]) == {"dns_query_log", "dns_probe"} and dns["shared"] is True


def test_switching_dhcp_away_from_pihole_keeps_pihole_as_dns(db):
    with _demo():   # demo: DHCP only
        pc.save_role(db, Role.DHCP, "demo", {})
        dns = pc.load_role(db, Role.DNS)
        assert dns.kind == "pihole" and not dns.shared and dns.config.url == "http://192.168.1.220:1000"


def test_same_as_requires_a_dhcp_provider_with_dns(db):
    with _demo():
        pc.save_role(db, Role.DHCP, "demo", {})
        with pytest.raises(pc.ConfigError, match="same_as"):
            pc.save_role(db, Role.DNS, None, None, same_as=Role.DHCP)


def test_explicit_none_disables_a_role(db):
    pc.save_role(db, Role.DNS, None, None)
    assert pc.load_role(db, Role.DNS) is None
    assert pc.load_role(db, Role.DHCP).kind == "pihole"


def test_secret_is_encrypted_and_kept_when_omitted(db):
    pc.save_role(db, Role.DHCP, "pihole", {"url": "http://10.0.0.2", "password": "new"})
    raw = db.get(Setting, pc.KEY).value["dhcp"]["config"]["password"]
    assert raw.startswith("fernet:")
    pc.save_role(db, Role.DHCP, "pihole", {"url": "http://10.0.0.3"})
    assert pc.load_role(db, Role.DHCP).config.password == "new"
    assert pc.view_role(db, Role.DHCP)["config"]["password"] is True


def test_switching_dhcp_provider_forces_dry_run(db):
    with _demo():
        set_sync_mode(db, "apply")
        pc.save_role(db, Role.DHCP, "demo", {})
        assert load_sync_mode(db) == "dry-run"


def test_kind_without_that_role_is_refused(db):
    with _demo(), pytest.raises(pc.ConfigError, match="dns"):
        pc.save_role(db, Role.DNS, "demo", {})   # demo declares only Role.DHCP
```


```python
# in backend/tests/test_migrations.py
def test_migration_0008_preserves_written_macs(migrated_engine_at):  # usa l'helper esistente del file per migrare a una revisione
    engine = migrated_engine_at("0007")
    with engine.begin() as c:
        c.execute(text("INSERT INTO settings(key, value) VALUES ('pihole.written_macs', '[\"00:00:5E:00:53:10\"]'::jsonb),"
                       " ('network.config', '{\"pihole_url\": \"http://10.0.0.2\", \"subnet\": \"10.0.0.0/24\"}'::jsonb),"
                       " ('pihole.down_since', '\"2026-10-01T00:00:00+00:00\"'::jsonb)"))
    upgrade(engine, "0008")
    with engine.begin() as c:
        rows = dict(c.execute(text("SELECT key, value FROM settings")).all())
    assert rows["provider.pihole.written_macs"] == ["00:00:5E:00:53:10"]
    assert "pihole.written_macs" not in rows and rows["dhcp.down_since"] == "2026-10-01T00:00:00+00:00"
    assert rows["network.config"] == {"subnet": "10.0.0.0/24"}
    assert rows["providers.config"] == {"dhcp": {"kind": "pihole", "config": {"url": "http://10.0.0.2"}}, "dns": {"same_as": "dhcp"}}
```

(Leggere `tests/test_migrations.py` e riusare il suo meccanismo reale per migrare a una revisione precisa; i nomi `migrated_engine_at` e `upgrade` sono indicativi.)

```python
# backend/tests/test_api_providers.py
def test_list_shows_pihole_and_current_roles(client):
    body = client.get("/api/providers").json()
    assert "pihole" in [p["kind"] for p in body["available"]]
    assert body["roles"]["dhcp"]["kind"] in ("pihole", None) or body["roles"]["dhcp"] is None
    assert "password" not in str([p["schema"].get("default") for p in body["available"]])


def test_put_invalid_config_is_422(client):
    r = client.put("/api/providers/dhcp", json={"kind": "pihole", "config": {"url": 12}})
    assert r.status_code == 422


def test_features_expose_roles(client):
    client.put("/api/providers/dns", json={"kind": None, "config": None})
    assert client.get("/api/features").json()["providers"]["dns"] is None


def test_pihole_router_is_mounted(client):
    assert client.get("/api/providers/pihole/preflight").status_code in (200, 502)
```

- [ ] **Step 2: Verificare che fallisca** — Run: `scripts/test.sh tests/test_provider_config.py tests/test_api_providers.py tests/test_migrations.py -v` → FAIL

- [ ] **Step 3: Implementazione** — Come da interfacce. Note:
  - `load_role` fonde `spec.env_defaults()` con l'override salvato (segreti decifrati con `secretbox.unseal`) e istanzia `spec.config_model(**merged)`.
  - `view_role` applica `model_dump()` e sostituisce i segreti con `bool`.
  - Nel JSON schema esposto i campi segreti non devono avere `default` (si toglie la chiave).
  - La migrazione usa `op.get_bind()` con SQL testuale sulla tabella `settings`, come fanno le migrazioni esistenti per i dati.
  - In `features.py` registrare `"providers"`.

- [ ] **Step 4: Verificare che passi** — Run: `scripts/test.sh -v` (suite completa: questa migrazione tocca tutto)

- [ ] **Step 5: Commit** — `git commit -m "feat(providers): per-role provider configuration, API and data migration"`

### Task C5: Ricollegare tutti i consumatori al ruolo invece che a Pi-hole

**Files:**
- Modify:
  - `backend/app/worker.py`
  - `backend/app/api/approval.py`
  - `backend/app/api/intel.py`
  - `backend/app/api/sync.py`
  - `backend/app/api/groups.py` (`_pinned_ips`)
  - `backend/app/cli.py`
  - `backend/app/sentinel/main.py`
  - `backend/app/metrics.py`
  - `backend/app/notify/render.py`
  - `backend/app/notify/catalog.py` (testi "Pi-hole" → generici)
  - `backend/app/netconfig.py` (togliere `pihole_url` da `NetConfig` e dalla validazione)
  - `backend/app/api/settings.py` (togliere `pihole_url`; rinominare `status.pihole_down_since` → `status.dhcp_down_since`)
  - `backend/app/cutover.py`, `backend/app/api/cutover.py`, `backend/app/pihole/` (eliminare)
- Test: adattare `tests/test_worker.py`, `test_api_approval.py`, `test_api_intel.py`, `test_api_sync.py`, `test_syncmode.py`, `test_sentinel_main.py`, `test_metrics.py`, `test_netconfig.py`, `test_api_settings.py`, `test_notify_render.py`; eliminare `tests/test_reservations.py` (portato in C2/C3)

**Interfaces:**
- Consumes: `runtime.provider_factory`, `runtime.policies`, `runtime.has_capability`, `enforcement.sync.*` (C2–C4)
- Produces:
  - `worker.reconcile_once(session_factory, factory_for: Callable[[Session], tuple[str, frozenset[Policy], Callable[[], AbstractContextManager]] | None], *, apply: bool | None = None) -> ReservationDiff | None`. Restituisce `None` senza effetti quando non c'è un provider `dhcp` con `RESERVATIONS`. In caso di errore `_mark_down(db, "dhcp", str(exc), provider=label)`.
  - `worker.dns_check_once`: no-op, e chiusura di un eventuale stato down, se il ruolo `dns` non ha `DNS_PROBE`; usa la chiave `dns.last_ok`.
  - `_mark_down(db, service, detail, *, provider: str | None = None)` aggiunge `provider` al payload di `infra.down`/`infra.up`.
  - `api/approval._enforce(db, revoke_mac, revoke_ip) -> str`: `"dry-run"` | `"no provider"` | `"applied"` | `"failed: …"`. La dipendenza FastAPI diventa `get_dhcp(db) -> tuple[str, frozenset[Policy], factory] | None`, sovrascrivibile nei test.
  - Prima di approvare, se la policy risultante (FULL o LAN_ONLY) non è in `runtime.policies(db)` e c'è un provider DHCP → **409** `"<label> does not support <policy>"`.
  - `api/intel`: `/devices/{id}/dns` e `/dns/analysis` → 404 `"no DNS provider with a query log"` se il ruolo `dns` non ha `DNS_QUERY_LOG`; risposta con i campi di `DnsQuery` (`time, domain, qtype, blocked, status, reply`).
  - `sentinel/main.py`: host della sonda = `probe_host()` del provider `dns` (letto all'avvio, come oggi `pihole_url`); se manca, la sonda DNS viene saltata.
  - `metrics.py`: gauge `janus_provider_up{role="dhcp"|"dns"}` al posto di `pihole_up`.
  - `notify/render.py`: `SERVICE_NAMES = {"dhcp": "DHCP", "dns": "DNS", "pihole": "Pi-hole", "pihole_dns": "Pi-hole DNS", ...}` (le vecchie chiavi restano per gli eventi già nel DB). Il titolo diventa `f"{payload.get('provider')} {SERVICE_NAMES[service]}"` quando `provider` è presente.

- [ ] **Step 1: Test che fallisce** (nuovi casi, oltre all'adattamento degli esistenti)

```python
# in tests/test_worker.py
def test_reconcile_without_dhcp_provider_is_noop(db):
    _seed(db)
    assert reconcile_once(lambda: nullcontext(db), lambda _db: None) is None
    assert _count(db, "infra.down") == 0


def test_reconcile_failure_marks_dhcp_down_with_provider_label(db):
    _seed(db)
    factory_for = lambda _db: ("pihole", SPEC.policies, lambda: PiholeProvider(FakePihole(fail=True), CFG))
    reconcile_once(lambda: nullcontext(db), factory_for, apply=True)
    ev = db.scalars(select(Event).where(Event.type == "infra.down")).one()
    assert ev.payload["service"] == "dhcp" and ev.payload["provider"] == "Pi-hole"
```

```python
# in tests/test_api_approval.py
def test_approve_with_unsupported_policy_is_409(client, db, monkeypatch):
    # provider DHCP finto che supporta solo FULL
    app_override_dhcp(client, ("demo", frozenset({Policy.FULL}), lambda: FakeStore()))
    device, group = seed_pending(db)
    r = client.post(f"/api/devices/{device.id}/approve", json={"name": "Plug", "group_id": group.id, "access": "lan_only"})
    assert r.status_code == 409 and "lan_only" in r.json()["detail"]


def test_approve_without_provider_reports_no_provider(client, db):
    app_override_dhcp(client, None)
    device, group = seed_pending(db)
    r = client.post(f"/api/devices/{device.id}/approve", json={"name": "Laptop", "group_id": group.id})
    assert r.status_code == 200 and r.json()["enforcement"] == "no provider"
```

```python
# in tests/test_api_intel.py
def test_dns_routes_are_404_without_dns_provider(client, db):
    app_override_dns(client, None)
    d = seed_device(db)
    assert client.get(f"/api/devices/{d.id}/dns").status_code == 404
```

(`app_override_dhcp(client, value)` e `app_override_dns(client, value)` vanno in `tests/fakes_provider.py`, perché li usano anche D3 ed E2: impostano `client.app.dependency_overrides[get_dhcp] = lambda: value` e lo stesso per `get_dns`. `seed_pending` e `seed_device` sono helper locali ai rispettivi file di test.)

- [ ] **Step 2: Verificare che fallisca** — Run: `scripts/test.sh tests/test_worker.py tests/test_api_approval.py tests/test_api_intel.py -v` → FAIL

- [ ] **Step 3: Implementazione** — Una modifica per file, nell'ordine dell'elenco "Files". Poi `grep -rn "pihole" backend/app | grep -v "app/providers/pihole"` deve restituire solo `notify/render.py` (le vecchie chiavi) e niente altro. Nel `main()` del worker:

```python
def dhcp_for(db: Session):
    rc = load_role(db, Role.DHCP)
    if rc is None or Capability.RESERVATIONS not in rc.spec.capabilities:
        return None
    return rc.kind, rc.spec.policies, lambda: rc.spec.open(rc.config)

jobs = [("reconcile", settings.reconcile_interval_s, lambda: reconcile_once(SessionLocal, dhcp_for)), ...]
```

Il `label` del provider per `_mark_down` si ricava da `registry.get_spec(kind).label`.

- [ ] **Step 4: Verificare che passi** — Run: `scripts/test.sh -v` e `cd backend && uv run --no-project --with ruff ruff check app tests` → tutto verde

- [ ] **Step 5: Commit** — `git commit -m "refactor: consumers talk to the dhcp/dns role, not to Pi-hole"`

### Task C6: Frontend — registro dei provider, pagine dinamiche, menu e stato

**Files:**
- Create:
  - `frontend/providers/types.ts`, `frontend/providers/registry.ts`
  - `frontend/providers/generic-config-form.tsx`, `frontend/providers/generic-config-form.test.tsx`
  - `frontend/providers/pihole/index.ts`, `frontend/providers/pihole/cutover-page.tsx` (contenuto di `components/cutover-readiness.tsx`, con la chiamata spostata su `/providers/pihole/preflight`)
  - `frontend/app/(app)/integrations/[kind]/[[...slug]]/page.tsx`
  - `frontend/app/(app)/settings/sections/providers.tsx`, `frontend/app/(app)/settings/sections/providers.test.tsx`
  - `frontend/lib/provider-status.ts`, `frontend/lib/provider-status.test.ts`
- Delete: `frontend/components/cutover-readiness.tsx` (il test va in `providers/pihole/cutover-page.test.tsx`)
- Modify:
  - `frontend/components/sidebar.tsx` (stato generico, voci extra)
  - `frontend/app/(app)/settings/page.tsx` (togliere il campo `pihole_url` e il blocco cutover da "Access control"; lasciare la riga sync mode con l'etichetta "Enforcement")
  - `frontend/app/(app)/settings/sections/index.ts`
  - `frontend/lib/types.ts`, `frontend/lib/settings-context.tsx`, `frontend/components/settings-network.ts` (+ test; dopo F5 `networkPatch` ha solo due argomenti: togliere `pihole_url` da `NETWORK_FIELDS` e `toDraft`)
  - `frontend/app/(app)/page.tsx`, `frontend/app/(app)/devices/[id]/page.tsx`, `frontend/app/(app)/pending/page.tsx`, `frontend/components/approve-form.tsx`, `frontend/lib/events.ts` (+ test)

**Interfaces:**
- Consumes: `GET /api/providers`, `PUT /api/providers/{role}`, `POST /api/providers/{role}/test`, `features.providers` (C4)
- Produces:

```ts
// frontend/providers/types.ts
import type { LucideIcon } from "lucide-react";
import type { ComponentType } from "react";

export type ProviderPage = { slug: string; label: string; icon: LucideIcon; Component: ComponentType; role: "dhcp" | "dns"; capability?: string };
export type ProviderUi = {
  kind: string;                                   // == backend folder name
  pages: ProviderPage[];                          // shown at /integrations/<kind>/<slug> and in the sidebar
  SettingsForm?: ComponentType<ConfigFormProps>;  // optional: the generic form covers most providers
};
export type ConfigFormProps = {
  schema: JsonSchema; secretFields: string[]; value: Record<string, unknown>;
  onChange: (patch: Record<string, unknown>) => void;
};
export type JsonSchema = { properties: Record<string, { type?: string; title?: string; description?: string; enum?: string[]; default?: unknown; format?: string }>; required?: string[] };
```

  - `registry.ts`: `export const PROVIDER_UI: Record<string, ProviderUi> = { pihole, unifi }` (D aggiunge `unifi`). Un provider senza voce qui funziona comunque: form generico e nessuna pagina extra.
  - `provider-status.ts`: `providerPill(features: Features | null, syncMode: "dry-run" | "apply"): { tone: "bg-ok" | "bg-bad" | "bg-accent" | "bg-muted"; text: string }`. Restituisce:
    - `"DNS down"` se `dns.down_since`
    - `"<label> unreachable"` se `dhcp.down_since`
    - `"<label> DHCP · active"` in apply
    - `"<label> · dry-run"` in dry-run
    - `"No network provider"` se `dhcp` è `null`
  - `providerNav(features: Features | null): NavItem[]`: per ogni ruolo configurato, le `pages` del suo `ProviderUi` con `page.role` uguale a quel ruolo e `page.capability` presente nelle `capabilities` **di quel ruolo**, deduplicate per `kind`+`slug`. Pi-hole DNS+DHCP mostra "DHCP cutover"; un Pi-hole solo DNS accanto a UniFi non lo mostra. Test in `lib/provider-status.test.ts`:

```ts
import { providerNav } from "@/lib/provider-status";

it("shows Pi-hole DHCP pages only when Pi-hole holds the DHCP role", () => {
  const pihole = (role: "dhcp" | "dns") => ref({ capabilities: role === "dhcp" ? ["reservations", "dhcp_server", "quarantine"] : ["dns_query_log", "dns_probe"] });
  expect(providerNav({ providers: { dhcp: pihole("dhcp"), dns: { ...pihole("dns"), shared: true } } }).map((i) => i.href)).toEqual(["/integrations/pihole/cutover"]);
  expect(providerNav({ providers: { dhcp: ref({ kind: "unifi", label: "UniFi", capabilities: ["reservations"] }), dns: pihole("dns") } })
    .some((i) => i.href === "/integrations/pihole/cutover")).toBe(false);
});
```
  - Regole di visibilità (tutte da `features.providers`):
    - widget DNS e pagina `/devices/[id]/dns` solo se `dns?.capabilities` include `dns_query_log`;
    - banda e testi di quarantena (Overview, IP plan, Pending) solo se `dhcp?.capabilities` include `quarantine`;
    - opzione "LAN only" in `approve-form` solo se `dhcp?.policies` include `lan_only`, oppure se `dhcp` è `null` (in quel caso Janus registra soltanto);
    - testo "Reserved IP · source" con il `label` del provider.

- [ ] **Step 1: Test che fallisce**

```ts
// frontend/lib/provider-status.test.ts
import { describe, expect, it } from "vitest";

import { providerPill } from "@/lib/provider-status";

const ref = (over = {}) => ({ kind: "pihole", label: "Pi-hole", capabilities: [], policies: [], down_since: null, ...over });

describe("providerPill", () => {
  it("names the configured provider", () => {
    expect(providerPill({ providers: { dhcp: ref(), dns: ref() } }, "apply").text).toBe("Pi-hole DHCP · active");
    expect(providerPill({ providers: { dhcp: ref({ kind: "unifi", label: "UniFi" }), dns: null } }, "dry-run").text).toBe("UniFi · dry-run");
  });
  it("reports outages first", () => {
    expect(providerPill({ providers: { dhcp: ref({ down_since: "x" }), dns: ref() } }, "apply")).toEqual({ tone: "bg-bad", text: "Pi-hole unreachable" });
    expect(providerPill({ providers: { dhcp: ref(), dns: ref({ down_since: "x" }) } }, "apply").text).toBe("DNS down");
  });
  it("says when nothing is configured", () => {
    expect(providerPill({ providers: { dhcp: null, dns: null } }, "dry-run").text).toBe("No network provider");
  });
});
```

```tsx
// frontend/providers/generic-config-form.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { GenericConfigForm } from "@/providers/generic-config-form";

it("renders fields from the JSON schema and hides secret values", async () => {
  const onChange = vi.fn();
  render(<GenericConfigForm onChange={onChange} secretFields={["password"]}
    value={{ url: "http://pi.hole", password: true, lease: "24h", verify_tls: false }}
    schema={{ properties: { url: { type: "string", title: "Url" }, password: { type: "string", title: "Password" },
                            lease: { type: "string", title: "Lease" }, verify_tls: { type: "boolean", title: "Verify Tls" } } }} />);
  expect(screen.getByLabelText("Url")).toHaveValue("http://pi.hole");
  expect(screen.queryByDisplayValue("true")).toBeNull();
  await userEvent.click(screen.getByLabelText("Verify Tls"));
  expect(onChange).toHaveBeenLastCalledWith({ verify_tls: true });
});
```

```tsx
// frontend/app/(app)/settings/sections/providers.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { ProvidersSection } from "./providers";

const LIST = {
  available: [
    { kind: "pihole", label: "Pi-hole", roles: ["dhcp", "dns"], capabilities: [], policies: ["full", "lan_only"], secret_fields: ["password"],
      schema: { properties: { url: { type: "string", title: "Url" }, password: { type: "string", title: "Password" } } }, description: "", docs_url: "" },
    { kind: "unifi", label: "UniFi", roles: ["dhcp"], capabilities: [], policies: ["full"], secret_fields: ["password"],
      schema: { properties: { url: { type: "string", title: "Url" } } }, description: "", docs_url: "" },
  ],
  roles: { dhcp: { kind: "pihole", label: "Pi-hole", source: "env", config: { url: "http://pi.hole", password: true } }, dns: null },
};

it("offers only kinds that support the role and warns before switching DHCP", async () => {
  vi.spyOn(api, "get").mockResolvedValue(LIST);
  const put = vi.spyOn(api, "put").mockResolvedValue(LIST.roles.dhcp);
  render(<ProvidersSection />);
  const dns = await screen.findByLabelText("DNS provider");
  expect([...dns.querySelectorAll("option")].map((o) => o.textContent)).toEqual(["Same as DHCP (Pi-hole)", "None", "Pi-hole"]);
  await userEvent.selectOptions(screen.getByLabelText("DHCP & access provider"), "unifi");
  expect(screen.getByText(/switches Janus back to dry-run/)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Url"), "https://unifi.example");
  await userEvent.click(screen.getByRole("button", { name: "Save DHCP & access" }));
  expect(put).toHaveBeenCalledWith("/providers/dhcp", { kind: "unifi", config: { url: "https://unifi.example" } });
});
```

- [ ] **Step 2: Verificare che fallisca** — Run: `cd frontend && npx vitest run lib/provider-status.test.ts providers "app/(app)/settings/sections/providers.test.tsx"` → FAIL

- [ ] **Step 3: Implementazione**
  - `generic-config-form.tsx` mappa `type`: `string` → input testo (`SecretInput` per `secretFields`), `integer`/`number` → input numerico, `boolean` → `Checkbox`, `enum` → `Segmented` se ha al massimo 4 valori, altrimenti `select`. L'etichetta è `title`; `description` è il testo di aiuto.
  - Sezione Settings "Network providers": due righe, "DHCP & access" e "DNS". Ognuna ha un `select` con "None" più i kind che supportano quel ruolo. Il `select` DNS ha in testa l'opzione "Same as DHCP (<label>)" quando il provider DHCP supporta anche il DNS: è la scelta predefinita per Pi-hole e non mostra un secondo form. Poi vengono il form del provider (`PROVIDER_UI[kind]?.SettingsForm ?? GenericConfigForm`), i pulsanti "Test connection" e "Save", e un `Notice` che avvisa: "Changing the DHCP provider switches Janus back to dry-run."
  - Pagina dinamica `integrations/[kind]/[[...slug]]`: trova `PROVIDER_UI[kind]?.pages`; senza slug mostra la prima pagina, con slug sconosciuto dà `notFound()`.
  - `pihole/index.ts`: `pages: [{ slug: "cutover", label: "DHCP cutover", icon: Router, Component: CutoverPage, role: "dhcp", capability: "dhcp_server" }]`.
  - Sidebar: `visibleNav(features, providerNav(features))` e `providerPill(...)` al posto del blocco `pihole` di oggi.

- [ ] **Step 4: Verificare che passi** — Run: `cd frontend && npm test && npx tsc --noEmit && npm run build`. Poi `grep -rni "pi-hole\|pihole" frontend --include=*.ts --include=*.tsx -l | grep -v node_modules | grep -v providers/pihole` deve restituire solo `lib/events.ts` (nomi dei vecchi eventi) e i test.

- [ ] **Step 5: Commit** — `git commit -m "feat(web): provider-driven pages, status and settings"`

### Task C7: Guida per chi aggiunge un router, template e test di contratto

**Files:**
- Create:
  - `backend/app/providers/README.md`
  - `backend/app/providers/_template/__init__.py`, `_template/provider.py`, `_template/client.py`
  - `docs/providers/adding-a-provider.md`
  - `backend/tests/providers/test_contract.py`
  - `frontend/providers/README.md`

**Interfaces:**
- Produces: `test_contract.py` è parametrizzato su `registry.all_specs()` e verifica per **ogni** provider reale:
  1. `spec.kind` coincide con la cartella e `spec.label` non è vuoto;
  2. `spec.config_model(**spec.env_defaults())` non solleva, oppure solleva solo `ValidationError` per campi obbligatori senza default env;
  3. ogni `secret_fields` esiste nel modello;
  4. se `Role.DNS in roles`, almeno una tra `DNS_QUERY_LOG` e `DNS_PROBE` è dichiarata;
  5. `spec.provider_class` non è `None` e implementa il protocollo di ogni capability in `CAPABILITY_PROTOCOL`;
  6. se `RESERVATIONS` è dichiarata, `policies` non è vuoto;
  7. **nessun modulo fuori da `app/providers/` importa `app.providers.<kind>`** (scansione AST di `app/**/*.py`).

- [ ] **Step 1: Test che fallisce** — Scrivere `test_contract.py` con i 7 controlli. Il controllo 7 fallisce se C5 ha lasciato import diretti.

```python
# backend/tests/providers/test_contract.py (estratto: controlli 5 e 7)
import ast
from pathlib import Path

import pytest

from app.providers import registry
from app.providers.base import CAPABILITY_PROTOCOL

SPECS = registry.all_specs()
APP = Path(__file__).resolve().parents[2] / "app"


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.kind)
def test_provider_class_implements_declared_capabilities(spec):
    for cap in spec.capabilities:
        proto = CAPABILITY_PROTOCOL.get(cap)
        if proto is not None:
            missing = [m for m in proto.__protocol_attrs__ if not callable(getattr(spec.provider_class, m, None))]
            assert not missing, f"{spec.kind} declares {cap} but lacks {missing}"


def test_core_never_imports_a_specific_provider():
    kinds = {s.kind for s in SPECS}
    offenders = []
    for path in APP.rglob("*.py"):
        if "providers" in path.relative_to(APP).parts[:1]:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = [node.module] if isinstance(node, ast.ImportFrom) and node.module else \
                    [a.name for a in node.names] if isinstance(node, ast.Import) else []
            offenders += [f"{path}: {n}" for n in names if any(n.startswith(f"app.providers.{k}") for k in kinds)]
    assert offenders == []
```

(`__protocol_attrs__` esiste da Python 3.12; il Dockerfile usa 3.12.)

- [ ] **Step 2: Verificare** — Run: `scripts/test.sh tests/providers/test_contract.py -v` → deve passare; se il controllo 7 fallisce, correggere gli import lasciati da C5

- [ ] **Step 3: Scrivere template e guida** — `_template/` contiene un provider minimo e commentato (solo `RESERVATIONS`, con un client httpx fittizio), con un `TODO(provider-author):` solo dove l'autore deve inserire le chiamate del proprio router. È l'unico posto del repo dove è accettabile, perché è un modello da copiare. `docs/providers/adding-a-provider.md` copre:
  - cos'è un ruolo e cos'è una capability, con una tabella per capability: metodo da implementare e pagine del sito che accende;
  - i passi:
    1. copiare `_template` in `backend/app/providers/<kind>/`;
    2. riempire `SPEC`;
    3. implementare i metodi;
    4. scrivere i test con respx sul modello di `tests/providers/pihole/test_client.py`;
    5. lanciare `scripts/test.sh tests/providers` (il contratto si applica da solo);
    6. facoltativo: aggiungere `frontend/providers/<kind>/index.ts` per pagine dedicate e una riga in `registry.ts`;
  - come si mappano le `Policy` sul proprio router;
  - le regole di sicurezza: mai rimuovere voci non gestite, `ProviderError(status=4xx)` per i rifiuti puntuali, e i timeout.

  `backend/app/providers/README.md` è una versione in 15 righe che rimanda alla guida.

- [ ] **Step 4: Verificare che passi** — Run: `scripts/test.sh tests/providers -v`

- [ ] **Step 5: Commit** — `git commit -m "docs(providers): contributor guide, template and contract tests"`; scrivere `docs/superpowers/handoff/C.md` (variabili `JANUS_DHCP_PROVIDER`, `JANUS_DNS_PROVIDER`; default di `JANUS_PIHOLE_URL` rimosso; metrica rinominata; rotta di preflight spostata).

---

## Parte D — Provider UniFi

Riferimenti (l'API "classica" della UniFi Network Application non è documentata ufficialmente): https://ubntwiki.com/products/software/unifi-controller/api e la Integration API ufficiale su `https://<console>/proxy/network/integration/v1` (Network ≥9, header `X-API-KEY`). Il piano usa l'API classica, l'unica che espone IP fissi e blocco, e prevede l'API key solo per il controllo di salute. **Ogni endpoint va verificato sull'hardware dell'amico (D4)** prima del merge in `main`.

### Task D1: Client UniFi

**Files:**
- Create: `backend/app/providers/unifi/__init__.py` (solo `SPEC` provvisorio senza `router`), `backend/app/providers/unifi/client.py`, `backend/tests/providers/unifi/__init__.py`, `backend/tests/providers/unifi/test_client.py`

**Interfaces:**
- Produces:
  - `UnifiError(ProviderError)`
  - `UnifiClient(base_url: str, *, username: str, password: str, site: str = "default", unifi_os: bool = True, verify_tls: bool = False, http: httpx.Client | None = None)`, context manager. Fa login al primo uso: con UniFi OS `POST /api/auth/login` e header `x-csrf-token` letto dalla risposta, poi rimandato nelle scritture; classico `POST /api/login`. Prefisso dei percorsi: `/proxy/network` se `unifi_os`. Su 401 rifà il login e riprova una volta, come `PiholeClient`.
  - `list_known() -> list[dict]` = `GET {p}/api/s/{site}/rest/user` → `data`
  - `list_online() -> list[dict]` = `GET {p}/api/s/{site}/stat/sta` → `data`
  - `list_networks() -> list[dict]` = `GET {p}/api/s/{site}/rest/networkconf` → `data`
  - `list_devices() -> list[dict]` = `GET {p}/api/s/{site}/stat/device` → `data` (AP e switch: `mac`, `name`)
  - `ensure_known(mac: str, name: str) -> dict`: se manca, `POST {p}/api/s/{site}/group/user` con `{"objects": [{"data": {"mac": mac_lower, "name": name}}]}`
  - `set_fixed_ip(user_id: str, *, ip: str | None, network_id: str | None, name: str) -> None` = `PUT {p}/api/s/{site}/rest/user/{user_id}` con `{"use_fixedip": ip is not None, "fixed_ip": ip or "", "network_id": network_id or "", "name": name}`
  - `stamgr(cmd: Literal["block-sta", "unblock-sta", "kick-sta"], mac: str) -> None` = `POST {p}/api/s/{site}/cmd/stamgr`
  - Gli errori HTTP diventano `UnifiError(msg, status=code)`; `meta.rc == "error"` con HTTP 200 diventa `UnifiError(meta.msg, status=400)`.

- [ ] **Step 1: Test che fallisce** (respx, sul modello di `tests/providers/pihole/test_client.py`)

```python
# backend/tests/providers/unifi/test_client.py
import httpx
import pytest
import respx

from app.providers.unifi.client import UnifiClient, UnifiError

BASE = "https://unifi.example"


@respx.mock
def test_unifi_os_login_then_csrf_on_writes():
    respx.post(f"{BASE}/api/auth/login").mock(return_value=httpx.Response(200, headers={"x-csrf-token": "c1", "set-cookie": "TOKEN=t; Path=/"}))
    users = respx.get(f"{BASE}/proxy/network/api/s/default/rest/user").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [{"_id": "u1", "mac": "00:00:5e:00:53:10"}]}))
    put = respx.put(f"{BASE}/proxy/network/api/s/default/rest/user/u1").mock(return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []}))
    with UnifiClient(BASE, username="janus", password="pw") as c:
        assert c.list_known()[0]["_id"] == "u1"
        c.set_fixed_ip("u1", ip="192.168.1.10", network_id="n1", name="laptop-a")
    assert put.calls[0].request.headers["x-csrf-token"] == "c1"
    assert put.calls[0].request.read() == b'{"use_fixedip":true,"fixed_ip":"192.168.1.10","network_id":"n1","name":"laptop-a"}'
    assert users.called


@respx.mock
def test_rc_error_is_a_rejection():
    respx.post(f"{BASE}/api/auth/login").mock(return_value=httpx.Response(200))
    respx.post(f"{BASE}/proxy/network/api/s/default/cmd/stamgr").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "error", "msg": "api.err.UnknownStation"}}))
    with UnifiClient(BASE, username="janus", password="pw") as c, pytest.raises(UnifiError) as exc:
        c.stamgr("kick-sta", "00:00:5e:00:53:10")
    assert exc.value.rejected and "UnknownStation" in str(exc.value)


@respx.mock
def test_unreachable_is_not_a_rejection():
    respx.post(f"{BASE}/api/auth/login").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(UnifiError) as exc, UnifiClient(BASE, username="janus", password="pw") as c:
        c.list_known()
    assert not exc.value.rejected
```

- [ ] **Step 2: Verificare che fallisca** — Run: `scripts/test.sh tests/providers/unifi -v` → FAIL

- [ ] **Step 3: Implementazione** — Su `httpx.Client(base_url=..., verify=verify_tls, timeout=10)`, i cookie restano nel client. Il login è lazy al primo request.

- [ ] **Step 4: Verificare che passi** — Run: `scripts/test.sh tests/providers/unifi -v`

- [ ] **Step 5: Commit** — `git commit -m "feat(unifi): UniFi Network API client"`

### Task D2: Provider UniFi (prenotazioni, policy, riconnessione)

**Files:**
- Create: `backend/app/providers/unifi/provider.py`, `backend/tests/providers/unifi/test_provider.py`, `backend/tests/providers/unifi/fake.py`
- Modify: `backend/app/providers/unifi/__init__.py` (`SPEC` completo)

**Interfaces:**
- Consumes: `UnifiClient` (D1), `base.*`
- Produces:
  - `UnifiConfig(BaseModel)`: `url: str`, `username: str`, `password: str = ""`, `site: str = "default"`, `unifi_os: bool = True`, `verify_tls: bool = False`, `network_id: str = ""` (vuoto = la rete il cui `ip_subnet` contiene la `subnet` di Janus)
  - `UnifiProvider(client, config)` implementa `ReservationStore`, `LeaseControl`, `HealthCheck`, più `clients() -> list[dict]` per la pagina.
  - Mappatura delle policy:

| Policy | Su UniFi | `CurrentEntry.reservation` letto da |
|---|---|---|
| FULL | `use_fixedip=true`, `fixed_ip=ip`, `network_id`, `blocked=false` | utente con `use_fixedip` |
| GUEST | utente noto, `use_fixedip=false`, `blocked=false`: indirizzo dal range DHCP della rete | utente con `note == "janus:guest"` (campo `note` scritto da Janus) |
| BLOCKED | `stamgr block-sta` | utente con `blocked=true` |
| LAN_ONLY | **non supportata** (su UniFi richiede VLAN o regole firewall; fuori ambito) | — |

  - `list_reservations()`: una `CurrentEntry` per ogni utente con `use_fixedip`, `blocked` o nota Janus. `key = user["_id"]`, `display = f"{name} ({mac})"`. Gli altri utenti non sono prenotazioni e non vengono restituiti: l'inventario non è un sistema di prenotazioni.
  - `add_reservation(r)`: `ensure_known` → `set_fixed_ip` (FULL) / `set_fixed_ip(ip=None)` + nota guest (GUEST) / `stamgr("block-sta")` (BLOCKED).
  - `remove_reservation(e)`: l'inverso (togliere l'IP fisso / `unblock-sta` / togliere la nota). **Mai** `forget-sta`.
  - `force_renew(mac, ip)` → `stamgr("kick-sta", mac)`. `UnknownStation` (device offline) non è un errore: va ignorato.
  - `SPEC = ProviderSpec(kind="unifi", label="UniFi", roles={DHCP}, capabilities={RESERVATIONS, FORCE_RENEW, CLIENT_INVENTORY}, policies={FULL, GUEST, BLOCKED}, secret_fields={"password"}, env_defaults=lambda: {"url": os.environ.get("JANUS_UNIFI_URL", ""), "username": os.environ.get("JANUS_UNIFI_USERNAME", ""), "password": os.environ.get("JANUS_UNIFI_PASSWORD", "")}, provider_class=UnifiProvider, open=open_unifi, router=api.router)`

- [ ] **Step 1: Test che fallisce**

```python
# backend/tests/providers/unifi/test_provider.py
from app.enforcement.sync import apply_sync
from app.models import Access, Device, Group
from app.providers.base import Policy, Reservation
from app.providers.unifi import SPEC
from app.providers.unifi.provider import UnifiConfig, UnifiProvider
from tests.providers.unifi.fake import FakeUnifi

CFG = UnifiConfig(url="https://unifi.example", username="janus", password="pw", network_id="n1")


def test_full_reservation_sets_fixed_ip_on_the_lan_network():
    fake = FakeUnifi()
    UnifiProvider(fake, CFG).add_reservation(Reservation("00:00:5E:00:53:10", "laptop-a", "192.168.1.10"))
    assert fake.users["00:00:5e:00:53:10"].items() >= {"use_fixedip": True, "fixed_ip": "192.168.1.10", "network_id": "n1"}.items()


def test_blocked_uses_block_sta_and_removal_unblocks():
    fake = FakeUnifi()
    p = UnifiProvider(fake, CFG)
    p.add_reservation(Reservation("00:00:5E:00:53:30", "bad", None, Policy.BLOCKED))
    [entry] = p.list_reservations()
    p.remove_reservation(entry)
    assert fake.commands == [("block-sta", "00:00:5e:00:53:30"), ("unblock-sta", "00:00:5e:00:53:30")]


def test_unrelated_known_clients_are_not_reservations():
    fake = FakeUnifi(users=[{"_id": "x", "mac": "00:00:5e:00:53:99", "name": "tv"}])
    assert UnifiProvider(fake, CFG).list_reservations() == []


def test_force_renew_on_offline_device_is_quiet():
    fake = FakeUnifi(offline={"00:00:5e:00:53:10"})
    UnifiProvider(fake, CFG).force_renew("00:00:5E:00:53:10", None)


def test_spec_does_not_claim_lan_only():
    assert Policy.LAN_ONLY not in SPEC.policies


def test_end_to_end_apply(db):
    g = Group(name="People", color="#6FB7FF", icon="device", range_start="192.168.1.10", range_end="192.168.1.19",
              default_access=Access.authorized)
    db.add(g)
    db.flush()
    db.add(Device(mac="00:00:5E:00:53:10", name="LAPTOP_A", hostname="laptop-a", group=g, static_ip="192.168.1.10",
                  access=Access.authorized))
    db.flush()
    fake = FakeUnifi()
    diff = apply_sync(db, UnifiProvider(fake, CFG), "unifi", SPEC.policies)
    assert len(diff.to_add) == 1 and fake.users["00:00:5e:00:53:10"]["fixed_ip"] == "192.168.1.10"
```

(`FakeUnifi` ha la stessa interfaccia pubblica di `UnifiClient` e tiene `users: dict[mac, dict]`, `commands: list` e `offline: set`. `stamgr("kick-sta")` su un MAC offline solleva `UnifiError("api.err.UnknownStation", status=400)`.)

- [ ] **Step 2: Verificare che fallisca** — Run: `scripts/test.sh tests/providers/unifi -v` → FAIL

- [ ] **Step 3: Implementazione** — Come da tabella. Quando `network_id` è vuoto, `open_unifi` lo risolve con `list_networks()` cercando la rete il cui `ip_subnet` contiene il gateway di `load_netconfig`. Se non la trova, `check()` solleva `UnifiError("no UniFi network matches subnet …", status=400)`.

- [ ] **Step 4: Verificare che passi** — Run: `scripts/test.sh tests/providers -v` (incluso il test di contratto C7)

- [ ] **Step 5: Commit** — `git commit -m "feat(unifi): reservations, guest and block policies, reconnect"`

### Task D3: Pagina "Clients" di UniFi

**Files:**
- Create: `backend/app/providers/unifi/api.py`, `backend/tests/providers/unifi/test_api.py`, `frontend/providers/unifi/index.ts`, `frontend/providers/unifi/clients-page.tsx`, `frontend/providers/unifi/clients-page.test.tsx`
- Modify: `frontend/providers/registry.ts` (una riga)

**Interfaces:**
- Produces:
  - `GET /api/providers/unifi/clients` → `[{mac, name, ip, online, uplink: "AP <name>" | "Switch <name> port <n>" | null, ssid, signal, uptime_s, device_id: uuid | null}]`. `device_id` collega il client al device Janus con lo stesso MAC. Risponde 404 se il provider `dhcp` attivo non è UniFi e 502 su `UnifiError`.
  - `unifi/index.ts`: `pages: [{ slug: "clients", label: "UniFi clients", icon: Wifi, Component: ClientsPage, role: "dhcp", capability: "client_inventory" }]`
  - `ClientsPage`: tabella con ricerca (riusare `lib/filter.ts`) e link a `/devices/<device_id>`; i client senza device mostrano il badge "not in Janus".

- [ ] **Step 1: Test che fallisce**

```python
# backend/tests/providers/unifi/test_api.py
from app.models import Access, Device
from app.providers.unifi import SPEC
from app.providers.unifi.provider import UnifiConfig, UnifiProvider
from tests.fakes_provider import app_override_dhcp
from tests.providers.unifi.fake import FakeUnifi

CFG = UnifiConfig(url="https://unifi.example", username="janus", password="pw", network_id="n1")


def test_clients_name_their_uplink_and_link_known_devices(client, db):
    d = Device(mac="00:00:5E:00:53:10", name="LAPTOP_A", hostname="laptop-a", access=Access.authorized)
    db.add(d)
    db.flush()
    fake = FakeUnifi(
        online=[{"mac": "00:00:5e:00:53:10", "ip": "192.168.1.10", "ap_mac": "00:00:5e:00:53:a0", "essid": "Home",
                 "signal": -55, "uptime": 120},
                {"mac": "00:00:5e:00:53:11", "ip": "192.168.1.240", "sw_mac": "00:00:5e:00:53:b0", "sw_port": 4,
                 "uptime": 60}],
        devices=[{"mac": "00:00:5e:00:53:a0", "name": "Living room"}, {"mac": "00:00:5e:00:53:b0", "name": "Office"}])
    app_override_dhcp(client, ("unifi", SPEC.policies, lambda: UnifiProvider(fake, CFG)))
    rows = {r["mac"]: r for r in client.get("/api/providers/unifi/clients").json()}
    assert rows["00:00:5E:00:53:10"]["uplink"] == "AP Living room" and rows["00:00:5E:00:53:10"]["device_id"] == str(d.id)
    assert rows["00:00:5E:00:53:11"]["uplink"] == "Switch Office port 4" and rows["00:00:5E:00:53:11"]["device_id"] is None


def test_clients_is_404_when_dhcp_is_not_unifi(client):
    app_override_dhcp(client, ("pihole", frozenset(), lambda: None))
    assert client.get("/api/providers/unifi/clients").status_code == 404
```

(`FakeUnifi` riceve anche `online` e `devices`; il client reale ha `list_devices()` = `GET {p}/api/s/{site}/stat/device`, da aggiungere a D1. `app_override_dhcp` deve vivere in `tests/fakes_provider.py`.)

```tsx
// frontend/providers/unifi/clients-page.test.tsx
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { ClientsPage } from "@/providers/unifi/clients-page";

it("links known clients and flags the others", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json([
    { mac: "00:00:5E:00:53:10", name: "laptop-a", ip: "192.168.1.10", online: true, uplink: "AP Living room", ssid: "Home", signal: -55, uptime_s: 120, device_id: "d1" },
    { mac: "00:00:5E:00:53:11", name: "", ip: "192.168.1.240", online: true, uplink: "Switch Office port 4", ssid: null, signal: null, uptime_s: 60, device_id: null },
  ]));
  render(<ClientsPage />);
  expect(await screen.findByRole("link", { name: "laptop-a" })).toHaveAttribute("href", "/devices/d1");
  expect(screen.getByText("not in Janus")).toBeInTheDocument();
});
```

- [ ] **Step 2: Verificare che fallisca** — Run: `scripts/test.sh tests/providers/unifi/test_api.py -v` e `cd frontend && npx vitest run providers/unifi` → FAIL

- [ ] **Step 3: Implementazione** — `api.py` ha `GET /clients`, con dipendenza `get_dhcp` (C5) e 404 se il `kind` non è `unifi`. Unisce `list_online()` con `list_devices()` (nomi di AP e switch per MAC) e con i device Janus per MAC normalizzato. `ClientsPage` usa `useResource("/providers/unifi/clients", { refreshMs: 15_000 })`.

- [ ] **Step 4: Verificare che passi** — Run: `scripts/test.sh tests/providers/unifi -v && cd frontend && npm test && npx tsc --noEmit`

- [ ] **Step 5: Commit** — `git commit -m "feat(unifi): live clients page"`

### Task D4: Verifica sull'hardware dell'amico (manuale)

- [ ] Creare un utente locale UniFi con ruolo "Site Admin", senza 2FA (le API classiche non supportano la 2FA) e con un nome come `janus`.
- [ ] Settings → Network providers: DHCP = UniFi (URL della console, utente, password); DNS = Pi-hole oppure None. Premere "Test connection" → `ok`, e il dettaglio deve citare la rete risolta.
- [ ] `sync_mode` resta `dry-run`: aprire `GET /api/sync/plan` e verificare che `unmanaged` contenga gli IP fissi già impostati a mano e che `to_remove` sia **vuoto**.
- [ ] Approvare un device di prova → `apply` → controllare nella UI di UniFi l'IP fisso; bloccarlo → client bloccato in UniFi; sbloccarlo.
- [ ] Ospite di prova (dopo il flusso E): nessun IP fisso, nota `janus:guest`, rimozione alla scadenza.
- [ ] Annotare in `docs/superpowers/handoff/D.md` la versione di UniFi Network, le differenze di endpoint trovate e le correzioni applicate.
