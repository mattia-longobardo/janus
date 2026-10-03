from dataclasses import dataclass

CHANNELS = ("email", "gotify")


@dataclass(frozen=True)
class EventSpec:
    label: str
    priority: int = 5
    always: bool = False
    maintenance_muted: bool = False
    email: bool = False
    gotify: bool = True


CATALOG: dict[str, EventSpec] = {
    "device.new": EventSpec("New device waiting for approval", priority=8, always=True, email=True),
    "device.approved": EventSpec("Device approved", priority=4),
    "device.blocked": EventSpec("Device blocked", priority=4),
    "device.offline": EventSpec("Known device offline", maintenance_muted=True),
    "ip.conflict": EventSpec("IP conflict detected", priority=8, email=True),
    "device.ip_mismatch": EventSpec("IP outside the plan", email=True, gotify=False),
    "device.private_mac": EventSpec("Private MAC detected or changed"),
    "infra.down": EventSpec("Scanner, DHCP or DNS unreachable", priority=8, maintenance_muted=True, email=True),
    "infra.up": EventSpec("Scanner, DHCP or DNS reachable again", priority=4, maintenance_muted=True, email=True),
    "security.new_port": EventSpec("New open port on a device", priority=6),
    "security.risky_service": EventSpec("Risky service exposed", priority=8, email=True),
    "notify.test": EventSpec("Test notification", always=True, email=True),
}
