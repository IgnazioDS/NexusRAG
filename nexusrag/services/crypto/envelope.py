from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from nexusrag.services.crypto.kms import get_kms_provider
from nexusrag.services.crypto.utils import b64decode_str, b64encode_bytes, sha256_hex, stable_json


@dataclass(frozen=True)
class EnvelopeResult:
    wrapped_dek: str
    key_ref: str
    key_version: int
    provider: str
    nonce: str
    tag: str
    cipher_text: str
    aad_json: dict[str, Any]
    checksum_sha256: str


def encrypt_payload(
    *,
    tenant_id: str,
    resource_type: str,
    resource_id: str,
    plaintext: bytes,
    key_ref: str,
    key_version: int,
    provider: str,
    created_at: datetime,
) -> EnvelopeResult:
    # Encrypt payload with per-object DEK and wrap the DEK with the KMS provider.
    kms = get_kms_provider()
    dek = os.urandom(32)
    aad_json = {
        "tenant_id": tenant_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "key_version": key_version,
        "created_at": created_at.isoformat(),
    }
    nonce = os.urandom(12)
    aesgcm = AESGCM(dek)
    ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext, stable_json(aad_json))
    cipher_text = ciphertext_with_tag[:-16]
    tag = ciphertext_with_tag[-16:]
    wrapped_dek = kms.wrap_key(tenant_id=tenant_id, dek=dek, key_ref=key_ref)
    checksum = sha256_hex(cipher_text)
    return EnvelopeResult(
        wrapped_dek=wrapped_dek,
        key_ref=key_ref,
        key_version=key_version,
        provider=provider,
        nonce=b64encode_bytes(nonce),
        tag=b64encode_bytes(tag),
        cipher_text=b64encode_bytes(cipher_text),
        aad_json=aad_json,
        checksum_sha256=checksum,
    )


def decrypt_payload(result: EnvelopeResult, *, tenant_id: str) -> bytes:
    # Decrypt payload using the wrapped DEK and AAD.
    kms = get_kms_provider()
    dek = kms.unwrap_key(tenant_id=tenant_id, wrapped_dek=result.wrapped_dek, key_ref=result.key_ref)
    nonce = b64decode_str(result.nonce)
    tag = b64decode_str(result.tag)
    cipher_text = b64decode_str(result.cipher_text)
    if sha256_hex(cipher_text) != result.checksum_sha256:
        raise ValueError("checksum mismatch")
    aesgcm = AESGCM(dek)
    return aesgcm.decrypt(nonce, cipher_text + tag, stable_json(result.aad_json))
