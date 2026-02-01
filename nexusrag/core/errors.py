from __future__ import annotations


class NexusError(Exception):
    """Base error for NexusRAG."""


class ProviderConfigError(NexusError):
    """Missing or invalid provider configuration."""


class VertexAuthError(NexusError):
    """Vertex authentication/authorization failure."""


class VertexTimeoutError(NexusError):
    """Vertex streaming request timed out."""


class RetrievalError(NexusError):
    """Retrieval layer failure."""


class DatabaseError(NexusError):
    """Database layer failure."""


class SessionTenantMismatchError(NexusError):
    """Session tenant mismatch; never mutate tenant_id for an existing session."""
