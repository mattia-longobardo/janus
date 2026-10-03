"""Contract every provider under app/providers/ must honour; it applies to new providers without any edit here."""
import argparse
import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.providers import registry
from app.providers.base import CAPABILITY_PROTOCOL, Capability, Role

SPECS = registry.all_specs()
APP = Path(__file__).resolve().parents[2] / "app"
PROVIDERS = APP / "providers"
CORE_COMMANDS = {"import-csv", "sync"}   # the subcommands app/cli.py defines itself


def test_there_is_at_least_one_provider():
    assert SPECS


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.kind)
def test_kind_matches_folder_and_label_is_set(spec):
    assert (PROVIDERS / spec.kind / "__init__.py").is_file(), f"{spec.kind} has no folder of that name"
    assert spec.label.strip()


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.kind)
def test_config_model_accepts_env_defaults(spec):
    try:
        spec.config_model(**spec.env_defaults())
    except ValidationError as exc:
        # Only a required field without an env default may be missing; anything else is a broken model.
        assert all(err["type"] == "missing" for err in exc.errors()), exc


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.kind)
def test_secret_fields_exist_in_the_model(spec):
    assert spec.secret_fields <= set(spec.config_model.model_fields)


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.kind)
def test_dns_role_declares_a_dns_capability(spec):
    if Role.DNS in spec.roles:
        assert spec.capabilities & {Capability.DNS_QUERY_LOG, Capability.DNS_PROBE}


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.kind)
def test_provider_class_implements_declared_capabilities(spec):
    assert spec.provider_class is not None
    for cap in spec.capabilities:
        proto = CAPABILITY_PROTOCOL.get(cap)
        if proto is not None:
            missing = [m for m in proto.__protocol_attrs__ if not callable(getattr(spec.provider_class, m, None))]
            assert not missing, f"{spec.kind} declares {cap} but lacks {missing}"


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.kind)
def test_reservations_come_with_policies(spec):
    if Capability.RESERVATIONS in spec.capabilities:
        assert spec.policies


def test_cli_commands_are_unique_and_do_not_shadow_core_commands():
    parser = argparse.ArgumentParser(prog="janus")
    sub = parser.add_subparsers(dest="command")
    for name in CORE_COMMANDS:
        sub.add_parser(name)
    for spec in SPECS:
        if spec.cli is not None:
            try:
                spec.cli(sub)   # argparse refuses a subcommand name that is already taken
            except (argparse.ArgumentError, ValueError) as exc:
                pytest.fail(f"{spec.kind} registers a CLI command that already exists: {exc}")


def _imported_modules(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
            names += [f"{node.module}.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
    return names


def test_core_never_imports_a_specific_provider():
    """Only app/providers/** may import app.providers.<kind>; the core goes through base, registry, config, runtime."""
    kinds = {s.kind for s in SPECS}
    offenders = []
    for path in APP.rglob("*.py"):
        if path.is_relative_to(PROVIDERS):
            continue
        for name in _imported_modules(ast.parse(path.read_text(encoding="utf-8"))):
            if any(name == f"app.providers.{k}" or name.startswith(f"app.providers.{k}.") for k in kinds):
                offenders.append(f"{path.relative_to(APP)}: {name}")
    assert offenders == []


def test_template_is_skipped_by_discovery_but_stays_a_valid_provider():
    from app.providers._template import SPEC

    assert "template" not in {s.kind for s in SPECS}
    assert SPEC.kind == "template" and SPEC.policies and SPEC.provider_class is not None
    assert SPEC.secret_fields <= set(SPEC.config_model.model_fields)
    for cap in SPEC.capabilities:
        proto = CAPABILITY_PROTOCOL.get(cap)
        assert proto is None or all(callable(getattr(SPEC.provider_class, m, None)) for m in proto.__protocol_attrs__)
