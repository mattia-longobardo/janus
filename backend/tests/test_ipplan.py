from ipaddress import IPv4Address as A

import pytest

from app.config import Settings
from app.net.ipplan import (
    AssignmentError,
    IpRange,
    NetworkPlan,
    check_assignment,
    check_group_range,
    infer_group_range,
    next_free,
)

PLAN = NetworkPlan.from_settings(Settings())
PEOPLE = IpRange.parse("192.168.1.10", "192.168.1.19")


def test_range_parse_and_contains():
    assert A("192.168.1.10") in PEOPLE and A("192.168.1.19") in PEOPLE
    assert A("192.168.1.20") not in PEOPLE
    assert PEOPLE.size() == 10
    with pytest.raises(ValueError):
        IpRange.parse("192.168.1.19", "192.168.1.10")


@pytest.mark.parametrize(
    ("ip", "reason"),
    [
        ("banana", "not an IPv4 address"),
        ("10.0.0.5", "outside 192.168.1.0/24"),
        ("192.168.1.0", "network or broadcast"),
        ("192.168.1.255", "network or broadcast"),
        ("192.168.1.1", "gateway"),
        ("192.168.1.245", "quarantine pool"),
        ("192.168.1.30", "outside the group range"),
        ("192.168.1.11", "already assigned"),
    ],
)
def test_check_assignment_rejects(ip, reason):
    group = IpRange.parse("192.168.1.0", "192.168.1.19") if reason in ("gateway", "network or broadcast") else PEOPLE
    if reason == "quarantine pool":
        group = IpRange.parse("192.168.1.240", "192.168.1.250")
    with pytest.raises(AssignmentError, match=reason):
        check_assignment(PLAN, ip, group, {A("192.168.1.11")})


def test_check_assignment_accepts_and_returns_address():
    assert check_assignment(PLAN, " 192.168.1.12 ", PEOPLE, {A("192.168.1.11")}) == A("192.168.1.12")


def test_next_free_skips_taken_and_reports_full():
    assert next_free(PLAN, PEOPLE, {A("192.168.1.10"), A("192.168.1.11")}) == A("192.168.1.12")
    assert next_free(PLAN, PEOPLE, {A(f"192.168.1.{i}") for i in range(10, 20)}) is None


def test_group_range_must_not_overlap_quarantine_or_others():
    check_group_range(PLAN, IpRange.parse("192.168.1.20", "192.168.1.29"), [PEOPLE])
    with pytest.raises(AssignmentError, match="overlaps 192.168.1.10"):
        check_group_range(PLAN, IpRange.parse("192.168.1.15", "192.168.1.25"), [PEOPLE])
    with pytest.raises(AssignmentError, match="quarantine"):
        check_group_range(PLAN, IpRange.parse("192.168.1.230", "192.168.1.241"), [])
    with pytest.raises(AssignmentError, match="outside"):
        check_group_range(PLAN, IpRange.parse("192.168.0.250", "192.168.1.5"), [])


def test_infer_group_range_uses_decade_blocks_clamped_to_subnet():
    assert infer_group_range(PLAN, [A("192.168.1.12"), A("192.168.1.15")]) == IpRange.parse("192.168.1.10", "192.168.1.19")
    assert infer_group_range(PLAN, [A("192.168.1.2")]) == IpRange.parse("192.168.1.1", "192.168.1.9")
    assert infer_group_range(PLAN, [A("192.168.1.100"), A("192.168.1.113")]) == IpRange.parse("192.168.1.100", "192.168.1.119")


def test_static_assignment_inside_guest_pool_is_refused():
    plan = NetworkPlan(PLAN.subnet, PLAN.gateway, PLAN.quarantine, guest=IpRange.parse("192.168.1.200", "192.168.1.229"))
    with pytest.raises(AssignmentError, match="guest"):
        check_assignment(plan, "192.168.1.210", IpRange.parse("192.168.1.2", "192.168.1.239"), set())


def test_group_range_overlapping_guest_pool_is_refused():
    plan = NetworkPlan(PLAN.subnet, PLAN.gateway, PLAN.quarantine, guest=IpRange.parse("192.168.1.200", "192.168.1.229"))
    with pytest.raises(AssignmentError, match="guest"):
        check_group_range(plan, IpRange.parse("192.168.1.190", "192.168.1.200"), [])


def test_plan_guest_defaults_to_none():
    assert PLAN.guest is None
