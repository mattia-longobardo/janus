"""dhcp-host lines as Pi-hole stores them: `mac[,set:lanonly],ip,hostname,lease`."""
from ipaddress import IPv4Address

from app.net.mac import normalize_mac
from app.providers.base import CurrentEntry, Policy, Reservation

LAN_ONLY_TAG = "set:lanonly"


def render(r: Reservation, lease: str) -> str:
    parts = [r.mac.lower()]
    if r.policy is Policy.LAN_ONLY:
        parts.append(LAN_ONLY_TAG)
    parts += [r.ip or "", r.hostname, lease]
    return ",".join(parts)


def parse(raw: str, lease: str) -> CurrentEntry:
    """A line Janus can read becomes a reservation; it is canonical when it carries the configured lease (MAC case
    and spacing do not matter: the diff compares parsed fields). Any other line keeps its MAC and IP, so additions
    that would duplicate them are refused."""
    # entry.ip always comes from _identity: the duplicate guard must see the address whatever field holds it.
    found_mac, found_ip = _identity(raw)
    parts = [p.strip() for p in raw.split(",")]
    lan_only = LAN_ONLY_TAG in parts
    parts = [p for p in parts if p != LAN_ONLY_TAG]
    if len(parts) == 4:
        raw_mac, ip, hostname, line_lease = parts
        try:
            mac = normalize_mac(raw_mac)
        except ValueError:
            pass
        else:
            policy = Policy.LAN_ONLY if lan_only else Policy.FULL
            return CurrentEntry(raw, raw, mac, found_ip, Reservation(mac, hostname, ip, policy), line_lease == lease)
    return CurrentEntry(raw, raw, found_mac, found_ip, None)


def _identity(raw: str) -> tuple[str | None, str | None]:
    """MAC and IPv4 address of any dhcp-host style line, whatever its other fields."""
    mac = ip = None
    for part in (p.strip() for p in raw.split(",")):
        if mac is None:
            try:
                mac = normalize_mac(part)
                continue
            except ValueError:
                pass
        if ip is None:
            try:
                ip = str(IPv4Address(part))
            except ValueError:
                pass
    return mac, ip
