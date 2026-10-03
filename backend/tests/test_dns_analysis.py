import time
from zoneinfo import ZoneInfo

import pytest

from app.api.sync import get_pihole
from app.intel.dns import analyze, base_domain, bucket_seconds
from app.models import Access, Device
from app.providers.base import DnsQuery
from tests.fakes import FakePihole

ROME = ZoneInfo("Europe/Rome")


def _q(time, domain, status, qtype, reply=None, blocked=False):
    return DnsQuery(time=time, domain=domain, qtype=qtype, blocked=blocked, status=status, reply=reply,
                    client_ip="192.168.1.41")


@pytest.mark.parametrize(("domain", "base"), [
    ("api.example.org", "example.org"),
    ("a.b.c.example.com", "example.com"),
    ("www.bbc.co.uk", "bbc.co.uk"),
    ("example.org.", "example.org"),
    ("localhost", "localhost"),
])
def test_base_domain(domain, base):
    assert base_domain(domain) == base


def test_bucket_size_follows_period():
    assert (bucket_seconds(1), bucket_seconds(6), bucket_seconds(24)) == (600, 600, 3600)


def test_analyze_counts_buckets_and_breakdowns():
    until = 1_790_000_000 - 1_790_000_000 % 3600 + 3600
    since = until - 3 * 3600
    queries = [
        _q(since + 10, "api.example.org", "FORWARDED", "A", "IP"),
        _q(since + 20, "cdn.example.org", "CACHE", "AAAA", "IP"),
        _q(since + 3700, "ads.tracker.net", "GRAVITY", "A", "BLOB", blocked=True),
        _q(since + 7300, "api.example.org", "FORWARDED", "HTTPS"),
    ]
    body = analyze(queries, 10, since, until, 3, ROME)
    assert body["totals"] == {"total": 10, "sampled": 4, "truncated": True, "blocked": 1, "blocked_pct": 25.0,
                              "unique_domains": 3}
    assert body["bucket_seconds"] == 600
    assert sum(b["total"] for b in body["timeline"]) == 4
    assert sum(b["blocked"] for b in body["timeline"]) == 1
    assert body["timeline"][0]["start"].endswith(("+01:00", "+02:00"))
    assert body["domains"][0]["domain"] == "api.example.org"
    assert body["domains"][0]["count"] == 2
    assert body["domains"][0]["base"] == "example.org"
    assert body["blocked_domains"] == [{"domain": "ads.tracker.net", "count": 1}]
    assert body["base_domains"][0] == {"domain": "example.org", "count": 3}
    assert {t["type"]: t["count"] for t in body["query_types"]} == {"A": 2, "AAAA": 1, "HTTPS": 1}
    assert {s["status"]: s["blocked"] for s in body["statuses"]} == {"FORWARDED": False, "CACHE": False, "GRAVITY": True}
    assert {r["type"]: r["count"] for r in body["replies"]} == {"IP": 2, "BLOB": 1}


def test_analyze_handles_no_queries():
    body = analyze([], 0, 0, 3600, 1, ROME)
    assert body["totals"]["blocked_pct"] == 0.0
    assert body["domains"] == [] and len(body["timeline"]) == 6


def test_analysis_endpoint(client, db):
    device = Device(mac="00:00:5E:00:53:41", name="TV", hostname="tv", access=Access.authorized, online=True,
                    last_ip="192.168.1.41")
    db.add(device)
    db.flush()
    fake = FakePihole()
    fake.queries = [{"time": time.time() - 30, "domain": "ads.example.net", "status": "GRAVITY", "type": "A",
                     "client": {"ip": "192.168.1.41"}}]
    client.app.dependency_overrides[get_pihole] = lambda: fake
    body = client.get(f"/api/devices/{device.id}/dns/analysis", params={"hours": 72}).json()
    assert body["totals"]["blocked"] == 1
    assert body["hours"] == 72 and len(body["timeline"]) in (72, 73)
    assert fake.last_query["disk"] is True
    assert client.get(f"/api/devices/{device.id}/dns/analysis", params={"hours": 200}).status_code == 422
    client.app.dependency_overrides[get_pihole] = lambda: FakePihole(fail=True)
    assert client.get(f"/api/devices/{device.id}/dns/analysis").status_code == 502
