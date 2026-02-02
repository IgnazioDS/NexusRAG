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


class RetrievalConfigError(RetrievalError):
    """Invalid or missing retrieval configuration for a corpus."""


class AwsConfigMissingError(RetrievalError):
    """AWS retrieval configuration missing required fields."""


class AwsAuthError(RetrievalError):
    """AWS retrieval authentication/authorization failure."""


class AwsRetrievalError(RetrievalError):
    """AWS retrieval request failure."""


class VertexRetrievalConfigError(RetrievalError):
    """Vertex retrieval configuration missing required fields."""


class VertexRetrievalAuthError(RetrievalError):
    """Vertex retrieval authentication/authorization failure."""


class VertexRetrievalError(RetrievalError):
    """Vertex retrieval request failure."""


class TTSConfigMissingError(NexusError):
    """TTS provider configuration missing required fields."""


class TTSAuthError(NexusError):
    """TTS provider authentication/authorization failure."""


class TTSError(NexusError):
    """TTS provider request failure."""


class DatabaseError(NexusError):
    """Database layer failure."""


class SessionTenantMismatchError(NexusError):
    """Session tenant mismatch; never mutate tenant_id for an existing session."""
