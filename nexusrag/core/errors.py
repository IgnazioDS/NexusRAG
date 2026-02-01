from __future__ import annotations


class NexusError(Exception):
    """Base error for NexusRAG."""


class ProviderConfigError(NexusError):
    """Missing or invalid provider configuration."""


class RetrievalError(NexusError):
    """Retrieval layer failure."""


class DatabaseError(NexusError):
    """Database layer failure."""


class SessionTenantMismatchError(NexusError):
    """Session tenant mismatch; never mutate tenant_id for an existing session."""
