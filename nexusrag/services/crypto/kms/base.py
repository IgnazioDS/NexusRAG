from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class KmsKeyRef:
    key_ref: str
    key_alias: str
    key_version: int
    provider: str


class KmsProvider(Protocol):
    provider: str

    def build_key_ref(self, *, tenant_id: str, key_alias: str, key_version: int) -> str:
        ...

    def wrap_key(self, *, tenant_id: str, dek: bytes, key_ref: str) -> str:
        ...

    def unwrap_key(self, *, tenant_id: str, wrapped_dek: str, key_ref: str) -> bytes:
        ...
