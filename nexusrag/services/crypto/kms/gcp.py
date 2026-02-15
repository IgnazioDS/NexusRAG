from __future__ import annotations

from typing import Final


class GcpKmsProvider:
    provider: Final[str] = "gcp_kms"

    def build_key_ref(self, *, tenant_id: str, key_alias: str, key_version: int) -> str:
        raise NotImplementedError("GCP KMS provider is not configured")

    def wrap_key(self, *, tenant_id: str, dek: bytes, key_ref: str) -> str:
        raise NotImplementedError("GCP KMS provider is not configured")

    def unwrap_key(self, *, tenant_id: str, wrapped_dek: str, key_ref: str) -> bytes:
        raise NotImplementedError("GCP KMS provider is not configured")
