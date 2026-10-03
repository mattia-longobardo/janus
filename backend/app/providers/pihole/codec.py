"""dhcp-host lines as Pi-hole stores them: `mac[,set:lanonly],ip,hostname,lease`, and for guests
`mac,set:guest,hostname,lease` (no address: dnsmasq picks one from the `tag:guest` range)."""
from ipaddress import IPv4Address

from app.net.mac import normalize_mac
from app.providers.base import CurrentEntry, Policy, Reservation

LAN_ONLY_TAG = "set:lanonly"
GUEST_TAG = "set:guest"


def render(r: Reservation, lease: str) -> str:
    if r.policy is Policy.GUEST:
        return ",".join([r.mac.lower(), GUEST_TAG, r.hostname, lease])
    parts = [r.mac.lower()]
    if r.policy is Policy.LAN_ONLY:
        parts.append(LAN_ONLY_TAG)
    parts += [r.ip or "", r.hostname, lease]
    return ",".join(parts)


def parse(raw: str, lease: str) -> CurrentEntry:
    """A line Janus can read becomes a reservation; it is canonical when it carries the configured lease (MAC case
    and spacing do not matter: the diff compares parsed fields). Any other line keeps its MAC and IP, so additions
    that would duplicate them are refused."""
    # entry.ip of a non-guest line always comes from _identity: the duplicate guard must see the address whatever
    # field holds it. A guest line holds no address.
    found_mac, found_ip = _identity(raw)
    parts = [p.strip() for p in raw.split(",")]
    lan_only, guest = LAN_ONLY_TAG in parts, GUEST_TAG in parts
    fields = [p for p in parts if p not in (LAN_ONLY_TAG, GUEST_TAG)]
    if guest and not lan_only and len(fields) == 3:
        raw_mac, hostname, line_lease = fields
        ip, entry_ip, policy = None, None, Policy.GUEST
    elif not guest and len(fields) == 4:
        raw_mac, ip, hostname, line_lease = fields
        entry_ip, policy = found_ip, Policy.LAN_ONLY if lan_only else Policy.FULL
    else:
        return CurrentEntry(raw, raw, found_mac, found_ip, None)
    try:
        mac = normalize_mac(raw_mac)
    except ValueError:
        return CurrentEntry(raw, raw, found_mac, found_ip, None)
    return CurrentEntry(raw, raw, mac, entry_ip, Reservation(mac, hostname, ip, policy), line_lease == lease)


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
