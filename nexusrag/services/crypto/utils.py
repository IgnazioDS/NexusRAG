from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Any


def decode_key_material(value: str) -> bytes:
    """Decode base64 or hex key material into raw bytes."""
    stripped = value.strip()
    if not stripped:
        raise ValueError("key material is empty")
    try:
        return bytes.fromhex(stripped)
    except ValueError:
        try:
            return base64.b64decode(stripped, validate=True)
        except (binascii.Error, ValueError) as exc:  # pragma: no cover - defensive.
            raise ValueError("key material must be base64 or hex") from exc


def b64encode_bytes(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def b64decode_str(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"))


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def stable_json(value: dict[str, Any]) -> bytes:
    import json

    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
