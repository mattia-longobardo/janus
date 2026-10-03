from collections.abc import Iterator
from dataclasses import dataclass
from ipaddress import AddressValueError, IPv4Address, IPv4Network
from typing import Protocol


class AssignmentError(ValueError):
    pass


@dataclass(frozen=True)
class IpRange:
    start: IPv4Address
    end: IPv4Address

    @classmethod
    def parse(cls, start: str, end: str) -> "IpRange":
        s, e = IPv4Address(start.strip()), IPv4Address(end.strip())
        if s > e:
            raise ValueError(f"range start {s} is after end {e}")
        return cls(s, e)

    def __contains__(self, item: object) -> bool:
        return isinstance(item, IPv4Address) and self.start <= item <= self.end

    def __iter__(self) -> Iterator[IPv4Address]:
        for n in range(int(self.start), int(self.end) + 1):
            yield IPv4Address(n)

    def size(self) -> int:
        return int(self.end) - int(self.start) + 1

    def overlaps(self, other: "IpRange") -> bool:
        return self.start <= other.end and other.start <= self.end

    def __str__(self) -> str:
        return f"{self.start}–{self.end}"


class _PlanSettings(Protocol):
    subnet: str
    gateway: str
    quarantine_start: str
    quarantine_end: str
    guest_start: str
    guest_end: str


@dataclass(frozen=True)
class NetworkPlan:
    subnet: IPv4Network
    gateway: IPv4Address
    quarantine: IpRange
    guest: IpRange | None = None

    @classmethod
    def from_settings(cls, s: _PlanSettings) -> "NetworkPlan":
        guest = IpRange.parse(s.guest_start, s.guest_end) if s.guest_start and s.guest_end else None
        return cls(IPv4Network(s.subnet), IPv4Address(s.gateway), IpRange.parse(s.quarantine_start, s.quarantine_end), guest)


def check_assignment(plan: NetworkPlan, ip: str, group_range: IpRange, taken: set[IPv4Address]) -> IPv4Address:
    try:
        addr = IPv4Address(ip.strip())
    except (AddressValueError, ValueError):
        raise AssignmentError(f"{ip!r} is not an IPv4 address") from None
    if addr not in plan.subnet:
        raise AssignmentError(f"{addr} is outside {plan.subnet}")
    if addr in (plan.subnet.network_address, plan.subnet.broadcast_address):
        raise AssignmentError(f"{addr} is the network or broadcast address")
    if addr == plan.gateway:
        raise AssignmentError(f"{addr} is the gateway")
    if addr in plan.quarantine:
        raise AssignmentError(f"{addr} is inside the quarantine pool {plan.quarantine}")
    if plan.guest is not None and addr in plan.guest:
        raise AssignmentError(f"{addr} is inside the guest pool {plan.guest}")
    if addr not in group_range:
        raise AssignmentError(f"{addr} is outside the group range {group_range}")
    if addr in taken:
        raise AssignmentError(f"{addr} is already assigned")
    return addr


def check_group_range(plan: NetworkPlan, rng: IpRange, others: list[IpRange]) -> None:
    for addr in (rng.start, rng.end):
        if addr not in plan.subnet:
            raise AssignmentError(f"{addr} is outside {plan.subnet}")
    if rng.overlaps(plan.quarantine):
        raise AssignmentError(f"range {rng} overlaps the quarantine pool {plan.quarantine}")
    if plan.guest is not None and rng.overlaps(plan.guest):
        raise AssignmentError(f"range {rng} overlaps the guest pool {plan.guest}")
    for other in others:
        if rng.overlaps(other):
            raise AssignmentError(f"range {rng} overlaps {other}")


def next_free(plan: NetworkPlan, group_range: IpRange, taken: set[IPv4Address]) -> IPv4Address | None:
    for addr in group_range:
        try:
            return check_assignment(plan, str(addr), group_range, taken)
        except AssignmentError:
            continue
    return None


def infer_group_range(plan: NetworkPlan, ips: list[IPv4Address]) -> IpRange:
    base = int(plan.subnet.network_address)
    last = plan.subnet.num_addresses - 2
    low = max(1, (int(min(ips)) - base) // 10 * 10)
    high = min(last, (int(max(ips)) - base) // 10 * 10 + 9)
    return IpRange(IPv4Address(base + low), IPv4Address(base + high))
