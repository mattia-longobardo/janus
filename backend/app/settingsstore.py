from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from app import secretbox
from app.models import Setting


class SettingsError(ValueError):
    pass


@dataclass(frozen=True)
class StoreField:
    name: str
    default: Callable[[], Any]
    secret: bool = False
    validate: Callable[[Any], Any] | None = None


class OverlayStore:
    """Env values are defaults; the settings row holds only the overrides."""

    def __init__(self, key: str, fields: Sequence[StoreField]):
        self.key = key
        self.fields = {f.name: f for f in fields}

    def _stored(self, db: Session) -> dict[str, Any]:
        row = db.get(Setting, self.key)
        value = row.value if row is not None and isinstance(row.value, dict) else {}
        return {k: v for k, v in value.items() if k in self.fields}

    def _decode(self, field: StoreField, raw: Any) -> Any:
        if field.secret and raw:
            return secretbox.unseal(raw) or ""
        return raw

    def load(self, db: Session) -> dict[str, Any]:
        stored = self._stored(db)
        return {name: self._decode(f, stored[name]) if name in stored else f.default()
                for name, f in self.fields.items()}

    def view(self, db: Session) -> dict[str, Any]:
        values = self.load(db)
        return {name: bool(values[name]) if f.secret else values[name] for name, f in self.fields.items()}

    def sources(self, db: Session) -> dict[str, Literal["env", "custom"]]:
        stored = self._stored(db)
        return {name: "custom" if name in stored else "env" for name in self.fields}

    def update(self, db: Session, patch: Mapping[str, Any]) -> dict[str, Any]:
        unknown = set(patch) - set(self.fields)
        if unknown:
            raise SettingsError(f"unknown fields: {', '.join(sorted(unknown))}")
        stored = self._stored(db)
        for name, value in patch.items():
            field = self.fields[name]
            if value is None:
                stored.pop(name, None)
                continue
            if field.validate is not None and value != "":
                value = field.validate(value)
            if value == field.default():
                stored.pop(name, None)   # same as env: follow env again
                continue
            stored[name] = secretbox.seal(value) if field.secret and value else value
        db.merge(Setting(key=self.key, value=stored))
        db.flush()
        return self.view(db)
