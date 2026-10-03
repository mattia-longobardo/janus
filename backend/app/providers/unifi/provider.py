"""Janus policies on a UniFi Network controller, expressed on its known clients (`rest/user`).

FULL is a fixed IP on the LAN network, GUEST a known client without fixed IP carrying Janus' guest note (the address
comes from the network's DHCP range), BLOCKED the controller's block flag. LAN_ONLY would need a VLAN or firewall rules
and is not supported. Known clients carrying none of these are not reservations; Janus never forgets a client.

Janus writes `note = "janus:<policy>"` on every client it reserves. Only an entry with that note is canonical: a fixed
IP or block set by hand looks exactly like Janus' own otherwise, and the first sync would adopt (and later remove) it.
"""
from collections.abc import Callable
from ipaddress import AddressValueError, IPv4Address, IPv4Network
from typing import Any, Protocol, Self

from pydantic import BaseModel

from app.net.mac import normalize_mac
from app.providers.base import CurrentEntry, Policy, Reservation
from app.providers.unifi.client import UnifiError

KIND = "unifi"
POLICIES = frozenset({Policy.FULL, Policy.GUEST, Policy.BLOCKED})
NOTE_PREFIX = "janus:"
GUEST_NOTE = f"{NOTE_PREFIX}{Policy.GUEST}"   # the guest note, read back as GUEST
OFFLINE = "UnknownStation"   # stamgr answer for a station that is not connected
LanLoader = Callable[[], tuple[str, str]]   # Janus' (subnet, gateway)


class UnifiConfig(BaseModel):
    url: str
    username: str
    password: str = ""
    site: str = "default"
    unifi_os: bool = True
    verify_tls: bool = False
    network_id: str = ""   # empty: the network whose ip_subnet contains Janus' gateway


class UnifiApi(Protocol):
    def __enter__(self) -> Any: ...
    def __exit__(self, *exc_info: object) -> Any: ...
    def list_known(self) -> list[dict[str, Any]]: ...
    def list_online(self) -> list[dict[str, Any]]: ...
    def list_networks(self) -> list[dict[str, Any]]: ...
    def list_devices(self) -> list[dict[str, Any]]: ...
    def ensure_known(self, mac: str, name: str) -> dict[str, Any]: ...
    def update_user(self, user_id: str, fields: dict[str, Any]) -> None: ...
    def set_fixed_ip(self, user_id: str, *, ip: str | None, network_id: str | None, name: str) -> None: ...
    def stamgr(self, cmd: Any, mac: str) -> None: ...


def _note(policy: Policy) -> str:
    return f"{NOTE_PREFIX}{policy}"


def _mac(raw: object) -> str | None:
    try:
        return normalize_mac(str(raw or ""))
    except ValueError:
        return None


class UnifiProvider:
    def __init__(self, client: UnifiApi, config: UnifiConfig, *, lan: LanLoader | None = None) -> None:
        self.client = client
        self.config = config
        self._lan = lan
        self._network_id: str | None = config.network_id or None

    def __enter__(self) -> Self:
        self.client.__enter__()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.client.__exit__(*exc_info)

    # LAN network
    def network_id(self) -> str:
        """The network fixed IPs are bound to; resolved from Janus' gateway on first use when not configured."""
        if self._network_id is None:
            self._network_id = self._resolve_network()
        return self._network_id

    def _resolve_network(self) -> str:
        if self._lan is None:
            raise UnifiError("network_id is not set and Janus' subnet is unknown", status=400)
        subnet, gateway = self._lan()
        try:
            address = IPv4Address(gateway)
        except (AddressValueError, ValueError) as exc:
            raise UnifiError(f"Janus' gateway {gateway!r} is not an IPv4 address", status=400) from exc
        for network in self.client.list_networks():
            try:
                if network.get("_id") and address in IPv4Network(str(network.get("ip_subnet") or ""), strict=False):
                    return str(network["_id"])
            except ValueError:
                continue
        raise UnifiError(f"no UniFi network matches subnet {subnet} (gateway {gateway}); set network_id",
                         status=400)

    def _network_or_none(self) -> str | None:
        try:
            return self.network_id()
        except UnifiError as exc:
            if not exc.rejected:
                raise
            return None

    # ReservationStore
    def list_reservations(self) -> list[CurrentEntry]:
        users = self.client.list_known()
        flagged = [u for u in users if u.get("blocked") or u.get("use_fixedip") or u.get("note") == GUEST_NOTE]
        if not flagged:
            return []
        network_id = self._network_or_none()   # unknown network: cannot judge, writes report it
        return [self._entry(u, network_id) for u in flagged]

    def _entry(self, user: dict[str, Any], network_id: str | None) -> CurrentEntry:
        key, name = str(user.get("_id", "")), str(user.get("name") or "")
        fixed = bool(user.get("use_fixedip"))
        ip = (str(user.get("fixed_ip") or "") or None) if fixed else None
        mac = _mac(user.get("mac"))
        if mac is None:
            return CurrentEntry(key, f"{name} ({user.get('mac')})", None, ip, None)
        display = f"{name} ({mac})"
        if user.get("blocked"):
            reservation = Reservation(mac, name, None, Policy.BLOCKED)
        elif fixed:
            reservation = Reservation(mac, name, ip, Policy.FULL)
        else:
            reservation = Reservation(mac, name, None, Policy.GUEST)
        canonical = user.get("note") == _note(reservation.policy)
        if reservation.policy is Policy.FULL and network_id is not None:
            canonical = canonical and user.get("network_id") == network_id
        return CurrentEntry(key, display, mac, ip, reservation, canonical)

    def add_reservation(self, reservation: Reservation) -> None:
        r = reservation
        user = self.client.ensure_known(r.mac, r.hostname)
        user_id = str(user["_id"])
        if r.policy is Policy.FULL:
            if not r.ip:
                raise UnifiError(f"{r.mac}: a full reservation needs an address", status=400)
            self.client.set_fixed_ip(user_id, ip=r.ip, network_id=self.network_id(), name=r.hostname)
        elif r.policy is Policy.GUEST:
            self.client.set_fixed_ip(user_id, ip=None, network_id=None, name=r.hostname)
        elif r.policy is Policy.BLOCKED:
            self.client.stamgr("block-sta", r.mac)
        else:
            raise UnifiError(f"{r.mac}: UniFi cannot enforce the {r.policy} policy", status=400)
        mark: dict[str, Any] = {"note": _note(r.policy), "noted": True}
        if r.policy is Policy.BLOCKED and user.get("name") != r.hostname:
            mark["name"] = r.hostname
        self.client.update_user(user_id, mark)

    def remove_reservation(self, entry: CurrentEntry) -> None:
        """Undo what the entry's policy stands for and drop Janus' note (a note Janus did not write stays); the
        client itself is never forgotten."""
        r = entry.reservation
        if r is None:
            return
        if r.policy is Policy.BLOCKED:
            self.client.stamgr("unblock-sta", r.mac)
        elif r.policy is Policy.FULL:
            self.client.set_fixed_ip(entry.key, ip=None, network_id=None, name=r.hostname)
        if entry.canonical:
            self.client.update_user(entry.key, {"note": "", "noted": False})

    def describe(self, reservation: Reservation) -> str:
        r = reservation
        what = {Policy.FULL: f"fixed IP {r.ip}", Policy.GUEST: "guest", Policy.BLOCKED: "blocked"}.get(r.policy, r.policy)
        return f"{r.hostname} ({r.mac}) {what}"

    # LeaseControl
    def force_renew(self, mac: str, ip: str | None) -> None:
        """Disconnect the station so it reconnects and asks for a lease; an offline station needs nothing."""
        if not mac:
            return
        try:
            self.client.stamgr("kick-sta", mac)
        except UnifiError as exc:
            if not (exc.rejected and OFFLINE in str(exc)):
                raise

    # HealthCheck
    def check(self) -> str:
        users = self.client.list_known()
        network_id = self.network_id()
        reservations = self.list_reservations()
        return f"{len(reservations)} reservations, {len(users)} known clients, network {network_id}"

    # Client inventory (the provider's clients page)
    def clients(self) -> list[dict[str, Any]]:
        """Known and connected clients with the AP or switch port they hang off; MACs normalised."""
        devices = {str(d.get("mac", "")).lower(): str(d.get("name") or d.get("mac")) for d in self.client.list_devices()}
        known = {str(u.get("mac", "")).lower(): u for u in self.client.list_known()}
        online = {str(s.get("mac", "")).lower(): s for s in self.client.list_online()}
        rows = []
        for raw in [*known, *(m for m in online if m not in known)]:
            mac = _mac(raw)
            if mac is None:
                continue
            user, sta = known.get(raw, {}), online.get(raw)
            name = user.get("name") or (sta or {}).get("name") or (sta or {}).get("hostname") or ""
            if sta is not None:
                ip = sta.get("ip")
            else:
                ip = (user.get("fixed_ip") if user.get("use_fixedip") else user.get("last_ip")) or None
            rows.append({
                "mac": mac,
                "name": str(name),
                "ip": ip,
                "online": sta is not None,
                "uplink": self._uplink(sta, devices),
                "ssid": (sta or {}).get("essid"),
                "signal": (sta or {}).get("signal"),
                "uptime_s": (sta or {}).get("uptime"),
            })
        return rows

    @staticmethod
    def _uplink(sta: dict[str, Any] | None, devices: dict[str, str]) -> str | None:
        if sta is None:
            return None
        if sta.get("ap_mac"):
            ap = str(sta["ap_mac"]).lower()
            return f"AP {devices.get(ap, ap)}"
        if sta.get("sw_mac"):
            sw = str(sta["sw_mac"]).lower()
            port = sta.get("sw_port")
            return f"Switch {devices.get(sw, sw)}" + (f" port {port}" if port is not None else "")
        return None
