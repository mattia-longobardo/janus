import hashlib
import ipaddress
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app import secretbox
from app.config import settings
from app.models import Setting

KEY = "auth.config"
ID_RE = re.compile(r"^[a-z0-9-]{2,32}$")
WELL_KNOWN = ".well-known/openid-configuration"


@dataclass(frozen=True)
class OidcProvider:
    id: str
    name: str
    discovery_url: str
    client_id: str
    client_secret: str
    scopes: list[str]
    enabled: bool
    source: Literal["env", "custom"]


@dataclass(frozen=True)
class AuthConfig:
    allowed_emails: list[str]
    allowed_emails_source: Literal["env", "custom"]
    providers: list[OidcProvider]


def _emails(raw: str | list[str]) -> list[str]:
    items = raw.replace("\n", ",").split(",") if isinstance(raw, str) else raw
    out: list[str] = []
    for item in items:
        email = str(item).strip().lower()
        if email and email not in out:
            out.append(email)
    return out


def _discovery(issuer: str) -> str:
    issuer = issuer.strip()
    return issuer if issuer.endswith(WELL_KNOWN) else issuer.rstrip("/") + "/" + WELL_KNOWN


def _env_provider() -> OidcProvider | None:
    if not (settings.oidc_id and settings.oidc_issuer.strip()):
        return None
    return OidcProvider(
        id="authentik", name=settings.oidc_name or "Authentik", discovery_url=_discovery(settings.oidc_issuer),
        client_id=settings.oidc_id, client_secret=settings.oidc_secret, scopes=["openid", "email", "profile"],
        enabled=True, source="env",
    )


def _stored(db: Session) -> dict[str, Any]:
    row = db.get(Setting, KEY)
    return row.value if row is not None and isinstance(row.value, dict) else {}


def load(db: Session) -> AuthConfig:
    stored = _stored(db)
    providers: dict[str, OidcProvider] = {}
    env = _env_provider()
    if env is not None:
        providers[env.id] = env
    for raw in stored.get("providers", []):
        sealed = raw.get("client_secret") or ""
        secret = secretbox.unseal(sealed) if sealed else None
        env_twin = providers.get(raw["id"])
        if secret is None and env_twin is not None and env_twin.client_id == raw["client_id"]:
            secret = env_twin.client_secret  # same client as the env one: the env secret still applies
        providers[raw["id"]] = OidcProvider(
            id=raw["id"], name=raw["name"], discovery_url=raw["discovery_url"], client_id=raw["client_id"],
            client_secret=secret or "", scopes=list(raw["scopes"]), enabled=bool(raw["enabled"]), source="custom",
        )
    custom_emails = "allowed_emails" in stored
    return AuthConfig(
        allowed_emails=_emails(stored["allowed_emails"] if custom_emails else settings.allowed_emails),
        allowed_emails_source="custom" if custom_emails else "env",
        providers=list(providers.values()),
    )


def _check_discovery(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme == "https" and parsed.hostname:
        return
    if parsed.scheme == "http" and parsed.hostname:
        try:
            if ipaddress.ip_address(parsed.hostname).is_private:
                return
        except ValueError:
            pass
        raise ValueError("discovery_url: http is only allowed for private IP addresses")
    raise ValueError("discovery_url: must be an https:// URL")


def _validate(raw: dict[str, Any]) -> dict[str, Any]:
    pid = str(raw.get("id", ""))
    if not ID_RE.match(pid):
        raise ValueError("id: use 2-32 lowercase letters, digits or dashes")
    _check_discovery(str(raw.get("discovery_url", "")))
    scopes = [str(s).strip() for s in raw.get("scopes", []) if str(s).strip()]
    if "openid" not in scopes:
        raise ValueError("scopes: must include openid")
    name = str(raw.get("name", "")).strip()
    client_id = str(raw.get("client_id", "")).strip()
    if not name:
        raise ValueError("name: required")
    if not client_id:
        raise ValueError("client_id: required")
    return {"id": pid, "name": name, "discovery_url": str(raw["discovery_url"]).strip(), "client_id": client_id,
            "scopes": scopes, "enabled": bool(raw.get("enabled", True))}


def save(db: Session, allowed_emails: list[str] | None, providers: list[dict[str, Any]]) -> AuthConfig:
    stored = _stored(db)
    previous = {p["id"]: p for p in stored.get("providers", [])}
    new_providers = []
    ids: set[str] = set()
    for raw in providers:
        item = _validate(raw)
        if item["id"] in ids:
            raise ValueError(f"id: duplicate provider {item['id']}")
        ids.add(item["id"])
        env = _env_provider()
        secret = raw.get("client_secret")
        if env is not None and item["id"] == env.id and secret in (None, "", env.client_secret) and {
            k: item[k] for k in ("name", "discovery_url", "client_id", "scopes", "enabled")
        } == {
            "name": env.name, "discovery_url": env.discovery_url, "client_id": env.client_id,
            "scopes": env.scopes, "enabled": env.enabled,
        }:
            continue  # identical to the env provider: no override
        if secret:
            item["client_secret"] = secretbox.seal(secret)
        elif item["id"] in previous:
            item["client_secret"] = previous[item["id"]].get("client_secret", "")
        else:
            item["client_secret"] = ""
        new_providers.append(item)
    value: dict[str, Any] = {"providers": new_providers}
    if allowed_emails is not None:
        if set(_emails(allowed_emails)) != set(_emails(settings.allowed_emails)):  # equal to env: drop the override
            value["allowed_emails"] = _emails(allowed_emails)
    elif "allowed_emails" in stored:
        value["allowed_emails"] = stored["allowed_emails"]
    row = db.get(Setting, KEY)
    if row is None:
        db.add(Setting(key=KEY, value=value))
    else:
        row.value = value
    db.commit()
    return load(db)


def internal_view(cfg: AuthConfig) -> dict[str, Any]:
    providers = [
        {k: v for k, v in asdict(p).items() if k not in ("enabled", "source")}
        for p in cfg.providers if p.enabled and p.client_secret
    ]
    body = {"allowed_emails": cfg.allowed_emails, "providers": providers}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return {**body, "version": digest}
