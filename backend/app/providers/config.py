"""Which provider holds each role, and its configuration.

Env values are the defaults; the `providers.config` setting holds only what the user changed:
`{"dhcp": {"kind": ..., "config": {overrides}} | None, "dns": {"same_as": "dhcp"} | {"kind": ..., "config": ...} | None}`.
A missing role follows the env, `None` turns the role off, and `{"same_as": "dhcp"}` means DNS is the very same
appliance as DHCP (Pi-hole doing both): one config, one session, nothing that can drift apart.
"""
import copy
import logging
from dataclasses import dataclass, replace
from typing import Any, Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app import secretbox
from app.config import settings
from app.events import record_event
from app.models import Setting
from app.providers import registry
from app.providers.base import Capability, ProviderError, ProviderSpec, Role, role_capabilities
from app.syncmode import load_sync_mode, set_sync_mode

KEY = "providers.config"
SAME_AS_DHCP = {"same_as": Role.DHCP.value}
LEGACY_KIND = "pihole"   # today's installs: Pi-hole holds both roles whenever its password is set
log = logging.getLogger(__name__)


class ConfigError(ValueError):
    pass


class ProviderInUse(ConfigError):
    """The change would leave a second DHCP server running: the current provider must be rolled back first."""


@dataclass(frozen=True)
class RoleConfig:
    kind: str
    spec: ProviderSpec
    config: BaseModel
    source: Literal["env", "custom"]
    shared: bool = False   # DNS served by the DHCP provider's own config


def env_kind(role: Role) -> str | None:
    value = (settings.dhcp_provider if role is Role.DHCP else settings.dns_provider).strip().lower()
    if value == "none":
        return None
    if not value:
        return LEGACY_KIND if settings.pihole_password else None
    return value


def config_schema(spec: ProviderSpec) -> dict[str, Any]:
    """JSON schema of the config model, without the defaults of secret fields (they come from the env)."""
    schema = copy.deepcopy(spec.config_model.model_json_schema())
    for name in spec.secret_fields:
        schema.get("properties", {}).get(name, {}).pop("default", None)
    return schema


def _stored(db: Session) -> dict[str, Any]:
    row = db.get(Setting, KEY)
    value = row.value if row is not None and isinstance(row.value, dict) else {}
    return {k: v for k, v in value.items() if k in {r.value for r in Role}}


def _entry(stored: dict[str, Any], role: Role) -> dict[str, Any] | None:
    if role.value in stored:
        entry = stored[role.value]
        return entry if isinstance(entry, dict) else None
    kind = env_kind(role)
    if kind is None:
        return None
    if role is Role.DNS and kind == env_kind(Role.DHCP):
        return dict(SAME_AS_DHCP)
    return {"kind": kind, "config": {}}


def _overrides(entry: dict[str, Any] | None) -> dict[str, Any]:
    config = entry.get("config") if isinstance(entry, dict) else None
    return dict(config) if isinstance(config, dict) else {}


def _decode(spec: ProviderSpec, overrides: dict[str, Any]) -> dict[str, Any]:
    return {name: (secretbox.unseal(value) or "") if name in spec.secret_fields and isinstance(value, str) and value
            else value for name, value in overrides.items()}


def _build(role: Role, entry: dict[str, Any]) -> RoleConfig | None:
    kind = entry.get("kind")
    try:
        spec = registry.get_spec(str(kind))
    except registry.UnknownProvider:
        log.error("provider %r for the %s role is not installed", kind, role)
        return None
    if role not in spec.roles:
        log.error("provider %s cannot hold the %s role", kind, role)
        return None
    overrides = _overrides(entry)
    defaults = spec.env_defaults()
    try:
        config = spec.config_model(**{**defaults, **_decode(spec, overrides)})
        source: Literal["env", "custom"] = "custom" if overrides or kind != env_kind(role) else "env"
    except ValidationError:
        log.exception("saved %s config for the %s role is invalid; using the env defaults", kind, role)
        try:
            config = spec.config_model(**defaults)
            source = "env"
        except ValidationError:
            log.exception("env defaults of %s are not a valid config either: the %s role is off", kind, role)
            return None
    return RoleConfig(kind=spec.kind, spec=spec, config=config, source=source)


def _resolve(stored: dict[str, Any], role: Role) -> RoleConfig | None:
    entry = _entry(stored, role)
    if entry is None:
        return None
    if role is Role.DNS and entry.get("same_as") == Role.DHCP.value:
        dhcp = _resolve(stored, Role.DHCP)
        if dhcp is not None and Role.DNS in dhcp.spec.roles:
            return replace(dhcp, shared=True)
        if role.value in stored:
            log.error("DNS is set to follow the DHCP provider, which does not serve DNS: the DNS role is off")
            return None
        entry = {"kind": env_kind(Role.DNS), "config": {}}   # implicit default: DNS stands on its own env config
    return _build(role, entry)


def load_role(db: Session, role: Role) -> RoleConfig | None:
    return _resolve(_stored(db), role)


def view_role(db: Session, role: Role) -> dict[str, Any] | None:
    rc = load_role(db, role)
    if rc is None:
        return None
    values = rc.config.model_dump(mode="json")
    return {
        "kind": rc.kind,
        "label": rc.spec.label,
        "source": rc.source,
        "shared": rc.shared,
        "config": {k: bool(v) if k in rc.spec.secret_fields else v for k, v in values.items()},
        "schema": config_schema(rc.spec),
        "secret_fields": sorted(rc.spec.secret_fields),
    }


def _describe(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors())


def _spec_for(role: Role, kind: str) -> ProviderSpec:
    try:
        spec = registry.get_spec(kind)
    except registry.UnknownProvider:
        raise ConfigError(f"unknown provider {kind!r}") from None
    if role not in spec.roles:
        raise ConfigError(f"{spec.label} cannot hold the {role} role")
    return spec


def _merge(spec: ProviderSpec, overrides: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    unknown = set(patch) - set(spec.config_model.model_fields)
    if unknown:
        raise ConfigError(f"unknown fields: {', '.join(sorted(unknown))}")
    plain = _decode(spec, overrides)
    for name, value in patch.items():
        if value is None:
            if name not in spec.secret_fields:   # a missing secret keeps the saved one
                plain.pop(name, None)
            continue
        plain[name] = value
    defaults = spec.env_defaults()
    try:
        values = spec.config_model(**{**defaults, **plain}).model_dump(mode="json")
    except ValidationError as exc:
        raise ConfigError(_describe(exc)) from exc
    stored: dict[str, Any] = {}
    for name in plain:
        if values[name] == defaults.get(name):
            continue   # same as env: follow env again
        if name in spec.secret_fields and values[name]:
            kept = name in overrides and patch.get(name) is None
            stored[name] = overrides[name] if kept else secretbox.seal(values[name])
        else:
            stored[name] = values[name]
    return stored


def _ensure_not_serving_dhcp(rc: RoleConfig) -> None:
    """Ask the box itself, whatever the sync mode says: a dry-run switch never turns its DHCP server off, and
    switching away while it serves would leave two DHCP servers on the LAN."""
    label = rc.spec.label
    try:
        with rc.spec.open(rc.config) as provider:
            active = provider.dhcp_server_active()
    except ProviderError as exc:
        raise ProviderInUse(f"cannot verify that {label} stopped serving DHCP ({exc}): "
                            "run janus rollback or check it first") from exc
    if active:
        raise ProviderInUse(f"{label} is still serving DHCP: run janus rollback first")


def save_role(db: Session, role: Role, kind: str | None, patch: dict[str, Any] | None, *,
              same_as: Role | None = None) -> RoleConfig | None:
    before_stored = _stored(db)
    stored = dict(before_stored)
    before = _resolve(before_stored, role)
    if same_as is not None:
        if role is not Role.DNS or same_as is not Role.DHCP:
            raise ConfigError("same_as: only the DNS role can follow the DHCP provider")
        dhcp = _resolve(before_stored, Role.DHCP)
        if dhcp is None or Role.DNS not in dhcp.spec.roles:
            label = dhcp.spec.label if dhcp else "no provider"
            raise ConfigError(f"same_as: the DHCP role is held by {label}, which does not serve DNS")
        stored[role.value] = dict(SAME_AS_DHCP)
    elif kind is None:
        stored[role.value] = None
    else:
        spec = _spec_for(role, kind)
        current = before_stored.get(role.value)
        overrides = _overrides(current) if isinstance(current, dict) and current.get("kind") == kind else {}
        stored[role.value] = {"kind": kind, "config": _merge(spec, overrides, patch or {})}

    after = _resolve(stored, role)
    kind_before, kind_after = (before.kind if before else None), (after.kind if after else None)
    if (role is Role.DHCP and kind_before != kind_after and before is not None
            and Capability.DHCP_SERVER in role_capabilities(before.spec, role)):
        _ensure_not_serving_dhcp(before)
    payload: dict[str, Any] = {"role": role.value, "kind_before": kind_before, "kind_after": kind_after,
                               "forced_dry_run": False}
    if role is Role.DHCP and kind_before != kind_after:
        dns = _resolve(before_stored, Role.DNS)
        if dns is not None and dns.shared and (after is None or Role.DNS not in after.spec.roles):
            # The old appliance keeps serving DNS on its own copy of the config it had as DHCP provider.
            stored[Role.DNS.value] = {"kind": kind_before, "config": _overrides(_entry(before_stored, Role.DHCP))}
            payload["dns_detached"] = True
        payload["forced_dry_run"] = load_sync_mode(db) == "apply"
        set_sync_mode(db, "dry-run", "dhcp provider changed")   # D9: never write a new provider without a review
    db.merge(Setting(key=KEY, value=stored))
    if stored != before_stored:
        record_event(db, "settings.providers", None, payload)
    db.flush()
    return after
