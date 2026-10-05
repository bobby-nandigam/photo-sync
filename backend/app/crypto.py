"""Encryption of OAuth tokens at rest.

Tokens are NEVER stored in plaintext and NEVER sent to the frontend. We use
Fernet (AES-128-CBC + HMAC) with a key from settings. In dev, if no key is
provided, we persist a generated one so restarts keep working.
"""
from __future__ import annotations

import json
from pathlib import Path

from cryptography.fernet import Fernet

from .config import settings
from .logging_conf import get_logger

log = get_logger(__name__)


def _load_or_create_key() -> bytes:
    if settings.fernet_key:
        return settings.fernet_key.encode()
    key_file = Path(settings.sqlite_path).parent / ".fernet_key"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if key_file.exists():
        return key_file.read_bytes().strip()
    key = Fernet.generate_key()
    key_file.write_bytes(key)
    log.warning(
        "No FERNET_KEY set; generated one at %s. Set FERNET_KEY in production "
        "so encrypted tokens survive redeploys.",
        key_file,
    )
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt_dict(data: dict) -> str:
    return _fernet.encrypt(json.dumps(data).encode()).decode()


def decrypt_dict(token: str) -> dict:
    return json.loads(_fernet.decrypt(token.encode()).decode())
