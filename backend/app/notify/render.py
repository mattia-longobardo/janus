from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.models import Event
from app.notify.catalog import CATALOG

# "pihole" and "pihole_dns" name the services of events recorded before the provider roles existed.
SERVICE_NAMES = {"dhcp": "DHCP", "dns": "DNS", "pihole": "Pi-hole", "pihole_dns": "Pi-hole DNS", "sentinel": "Scanner"}
ACCESS_NAMES = {"authorized": "full network", "lan_only": "LAN only"}


@dataclass(frozen=True)
class Message:
    title: str
    body: str
    priority: int
    url: str | None = None


def _local(value: str | None, tz: ZoneInfo) -> str:
    if not value:
        return "unknown"
    return datetime.fromisoformat(value).astimezone(tz).strftime("%d/%m %H:%M")


def render(event: Event, device_name: str | None, *, base_url: str, tz: ZoneInfo, quarantine_active: bool) -> Message:
    p = event.payload or {}
    priority = CATALOG[event.type].priority
    name = device_name or p.get("name") or event.mac or "device"
    url = f"{base_url}/devices/{p['device_id']}" if p.get("device_id") else base_url
    service = SERVICE_NAMES.get(p.get("service", ""), "Service")
    if p.get("provider"):
        service = f"{p['provider']} {service}"
    kind = event.type

    if kind == "device.new":
        bits = [f"MAC {event.mac}", f"IP {p.get('ip') or '—'}"]
        if p.get("private_mac"):
            bits.append("private MAC")
        tail = ("No internet access until you approve it." if quarantine_active
                else "Detected on the network; quarantine is not active yet.")
        return Message(f"New device: {name}", " · ".join(bits) + "\n" + tail, priority, url)
    if kind == "device.approved":
        access = ACCESS_NAMES.get(p.get("access", ""), p.get("access", ""))
        return Message(f"Approved: {name}", f"{p.get('ip') or '—'} · {access}", priority, url)
    if kind == "device.blocked":
        return Message(f"Blocked: {name}", f"MAC {event.mac}", priority, url)
    if kind == "device.offline":
        return Message(f"Offline: {name}",
                       f"Not seen for more than {p.get('hours')} h (last seen {_local(p.get('last_seen'), tz)})", priority, url)
    if kind == "ip.conflict":
        claimant, owner = p.get("claimant"), p.get("owner")
        if claimant and owner:
            relation = "which is assigned to" if p.get("reserved") else "which is already used by"
            return Message(
                f"{claimant['name']} is trying to take {p.get('ip')}",
                f"{claimant['name']} ({claimant['mac']}) is trying to take {p.get('ip')}, "
                f"{relation} {owner['name']} ({owner['mac']}).",
                priority,
                f"{base_url}/devices/{claimant['device_id']}",
            )
        return Message(f"IP conflict on {p.get('ip')}", "Claimed by " + ", ".join(p.get("macs", [])), priority, base_url)
    if kind == "device.ip_mismatch":
        return Message(f"{name} is using {p.get('ip')}", f"Its reserved address is {p.get('expected')}", priority, url)
    if kind == "device.private_mac":
        return Message(
            f"{name} changed its MAC",
            f"It looks like {p.get('previous_name')} ({p.get('previous_mac')}). "
            "Set a fixed private address for the home Wi-Fi on the device.",
            priority, url,
        )
    if kind == "infra.down":
        return Message(f"{service} unreachable", str(p.get("error", "")), priority, base_url)
    if kind == "infra.up":
        return Message(f"{service} reachable again", f"Down since {_local(p.get('down_since'), tz)}", priority, base_url)
    if kind == "security.new_port":
        detail = " ".join(part for part in (p.get("service"), p.get("version")) if part) or "unknown service"
        return Message(f"New open port on {name}", f"{p.get('port')}/{p.get('proto')} {detail}", priority, url)
    if kind == "security.risky_service" and p.get("ports"):
        ports = p["ports"]
        lines = [f"{item['port']}/{item['proto']} {item.get('service') or 'unknown'}: {item['reason']}" for item in ports]
        title = f"Risky service on {name}" if len(ports) == 1 else f"Risky services on {name}"
        return Message(title, "\n".join(lines), priority, url)
    if kind == "security.risky_service":
        return Message(f"Risky service on {name}",
                       f"{p.get('port')}/{p.get('proto')} {p.get('service') or 'unknown'}: {p.get('reason')}", priority, url)
    return Message("Janus test notification", "If you can read this, the channel works.", priority, base_url)
