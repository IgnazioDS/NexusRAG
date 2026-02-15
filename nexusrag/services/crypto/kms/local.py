from __future__ import annotations

import hashlib
import hmac
import os
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from nexusrag.core.config import get_settings
from nexusrag.services.crypto.utils import b64decode_str, b64encode_bytes, decode_key_material


class LocalKmsProvider:
    provider: Final[str] = "local_kms"

    def __init__(self) -> None:
        self._master_key = _load_master_key()

    def build_key_ref(self, *, tenant_id: str, key_alias: str, key_version: int) -> str:
        return f"local://{tenant_id}/{key_alias}/v{key_version}"

    def wrap_key(self, *, tenant_id: str, dek: bytes, key_ref: str) -> str:
        kek = _derive_kek(self._master_key, tenant_id=tenant_id, key_ref=key_ref)
        nonce = os.urandom(12)
        aad = f"{tenant_id}:{key_ref}".encode("utf-8")
        aesgcm = AESGCM(kek)
        ciphertext = aesgcm.encrypt(nonce, dek, aad)
        return b64encode_bytes(nonce + ciphertext)

    def unwrap_key(self, *, tenant_id: str, wrapped_dek: str, key_ref: str) -> bytes:
        payload = b64decode_str(wrapped_dek)
        nonce, ciphertext = payload[:12], payload[12:]
        kek = _derive_kek(self._master_key, tenant_id=tenant_id, key_ref=key_ref)
        aad = f"{tenant_id}:{key_ref}".encode("utf-8")
        aesgcm = AESGCM(kek)
        return aesgcm.decrypt(nonce, ciphertext, aad)


def _load_master_key() -> bytes:
    settings = get_settings()
    if settings.crypto_local_master_key:
        return _ensure_32_bytes(decode_key_material(settings.crypto_local_master_key))
    if settings.backup_encryption_key:
        return _ensure_32_bytes(decode_key_material(settings.backup_encryption_key))
    # Deterministic fallback for dev/test to avoid breaking local workflows.
    seed = f"{settings.app_name}-local-kms".encode("utf-8")
    return hashlib.sha256(seed).digest()


def _derive_kek(master_key: bytes, *, tenant_id: str, key_ref: str) -> bytes:
    # HMAC-based derivation keeps KEKs deterministic without persisting key material.
    message = f"{tenant_id}:{key_ref}".encode("utf-8")
    return hmac.new(master_key, message, hashlib.sha256).digest()


def _ensure_32_bytes(value: bytes) -> bytes:
    if len(value) == 32:
        return value
    return hashlib.sha256(value).digest()
