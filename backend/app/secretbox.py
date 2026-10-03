import base64
import logging

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings

PREFIX = "fernet:"
log = logging.getLogger(__name__)


class SecretBoxError(RuntimeError):
    pass


def _fernet() -> Fernet:
    material = settings.secret_key or settings.internal_token
    if not material:
        raise SecretBoxError("set JANUS_SECRET_KEY (or JANUS_INTERNAL_TOKEN) to store secrets")
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"janus-settings-v1").derive(material.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def seal(plain: str) -> str:
    return PREFIX + _fernet().encrypt(plain.encode()).decode()


def unseal(token: str) -> str | None:
    if not token.startswith(PREFIX):
        return None
    try:
        return _fernet().decrypt(token[len(PREFIX):].encode()).decode()
    except (InvalidToken, SecretBoxError):
        log.warning("stored secret cannot be decrypted; was the key rotated?")
        return None
