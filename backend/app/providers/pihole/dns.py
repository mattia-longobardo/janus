from typing import Any

from app.providers.base import DnsQuery

BLOCKED = {"GRAVITY", "REGEX", "DENYLIST", "GRAVITY_CNAME", "REGEX_CNAME", "DENYLIST_CNAME", "SPECIAL_DOMAIN",
           "EXTERNAL_BLOCKED_IP", "EXTERNAL_BLOCKED_NULL", "EXTERNAL_BLOCKED_NXRA", "EXTERNAL_BLOCKED_EDE15"}


def normalize(raw: dict[str, Any]) -> DnsQuery:
    """One entry of Pi-hole's /api/queries."""
    status = str(raw.get("status") or "UNKNOWN")
    reply = raw.get("reply")
    client = raw.get("client")
    return DnsQuery(
        time=float(raw.get("time") or 0),
        domain=str(raw.get("domain") or ""),
        qtype=str(raw.get("type") or "UNKNOWN"),
        blocked=status in BLOCKED,
        status=status,
        reply=str(reply["type"]) if isinstance(reply, dict) and reply.get("type") else None,
        client_ip=str(client.get("ip") or "") if isinstance(client, dict) else "",
    )
