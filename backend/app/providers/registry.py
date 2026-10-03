import importlib
import pkgutil
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache
from types import ModuleType

from app.providers.base import ProviderSpec


class RegistryError(RuntimeError):
    pass


class UnknownProvider(KeyError):
    pass


def discover(package: ModuleType | None = None) -> dict[str, ProviderSpec]:
    if package is None:
        return _discover_default()
    specs: dict[str, ProviderSpec] = {}
    for info in pkgutil.iter_modules(package.__path__):
        if not info.ispkg or info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package.__name__}.{info.name}")
        spec = getattr(module, "SPEC", None)
        if not isinstance(spec, ProviderSpec):
            continue
        if spec.kind != info.name:
            raise RegistryError(f"provider folder {info.name!r} declares kind {spec.kind!r}")
        specs[spec.kind] = spec
    return dict(sorted(specs.items()))


@cache
def _discover_default() -> dict[str, ProviderSpec]:
    import app.providers
    return discover(app.providers)


_extra: dict[str, ProviderSpec] = {}


@contextmanager
def override(extra: dict[str, ProviderSpec]) -> Iterator[None]:
    """Tests only: register fake providers on top of the discovered ones."""
    _extra.update(extra)
    try:
        yield
    finally:
        for kind in extra:
            _extra.pop(kind, None)


def _all() -> dict[str, ProviderSpec]:
    return {**_discover_default(), **_extra}


def get_spec(kind: str) -> ProviderSpec:
    try:
        return _all()[kind]
    except KeyError:
        raise UnknownProvider(kind) from None


def all_specs() -> list[ProviderSpec]:
    return sorted(_all().values(), key=lambda s: s.label)
