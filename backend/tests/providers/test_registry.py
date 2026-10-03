import dataclasses

import pytest

from app.providers import registry
from tests.providers import fixture_pkg


def test_discovers_packages_and_skips_underscored_ones():
    specs = registry.discover(fixture_pkg)
    assert list(specs) == ["demo"]
    assert specs["demo"].label == "Demo router"


def test_kind_must_match_folder(monkeypatch):
    import tests.providers.fixture_pkg.demo as demo
    monkeypatch.setattr(demo, "SPEC", dataclasses.replace(demo.SPEC, kind="other"))
    with pytest.raises(registry.RegistryError, match="demo"):
        registry.discover(fixture_pkg)


def test_override_adds_fakes_temporarily():
    demo = registry.discover(fixture_pkg)["demo"]
    with registry.override({"demo": demo}):
        assert registry.get_spec("demo") is demo
    with pytest.raises(registry.UnknownProvider):
        registry.get_spec("demo")


def test_unknown_kind():
    with pytest.raises(registry.UnknownProvider):
        registry.get_spec("does-not-exist")
