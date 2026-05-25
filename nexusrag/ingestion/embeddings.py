from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import Any

from nexusrag.core.config import EMBED_DIM, get_settings
from nexusrag.core.errors import ProviderConfigError

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _hash_token(token: str) -> tuple[int, float]:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    # Hash to a stable index within the fixed embedding dimension.
    idx = int(digest[:8], 16) % EMBED_DIM
    sign = 1.0 if int(digest[8:12], 16) % 2 == 0 else -1.0
    magnitude = (int(digest[12:20], 16) % 1000) / 1000.0
    return idx, sign * (0.2 + magnitude)


def _embed_text_fake(text: str) -> list[float]:
    """Deterministic hashed-bag-of-words embedding.

    NOT semantic: it captures lexical token overlap only (synonyms and
    paraphrases hash to unrelated buckets). It requires no credentials, so
    it is the default for local/dev/CI. Real semantic retrieval requires
    embedding_provider="vertex".
    """
    # Always allocate the full embedding dimension to match the DB schema.
    vector = [0.0] * EMBED_DIM
    tokens = _TOKEN_RE.findall(text.lower())
    if not tokens:
        return vector

    for token in tokens:
        idx, value = _hash_token(token)
        vector[idx] += value

    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector

    normalized = [v / norm for v in vector]
    if len(normalized) != EMBED_DIM:
        # Defensive guard: retrieval expects a fixed-size vector.
        raise ValueError("embedding dimension mismatch")
    return normalized


# Lazy, cached Vertex embedding model. init() + from_pretrained() are
# expensive, so build once per process and reuse across calls.
_vertex_model: Any = None
_vertex_model_name: str | None = None


def _get_vertex_model() -> Any:
    global _vertex_model, _vertex_model_name
    settings = get_settings()
    project = settings.google_cloud_project
    location = settings.google_cloud_location
    model_name = settings.vertex_embedding_model
    missing = []
    if not project:
        missing.append("GOOGLE_CLOUD_PROJECT")
    if not location:
        missing.append("GOOGLE_CLOUD_LOCATION")
    if missing:
        raise ProviderConfigError(
            f"Vertex embeddings config missing: set {', '.join(missing)} in .env."
        )
    if _vertex_model is not None and _vertex_model_name == model_name:
        return _vertex_model
    try:
        from vertexai import init
        from vertexai.language_models import TextEmbeddingModel
    except Exception as exc:  # pragma: no cover - environment-specific
        raise ProviderConfigError(
            "Vertex AI SDK not available. Install google-cloud-aiplatform."
        ) from exc
    init(project=project, location=location)
    _vertex_model = TextEmbeddingModel.from_pretrained(model_name)
    _vertex_model_name = model_name
    return _vertex_model


def _embed_text_vertex(text: str) -> list[float]:
    """Real semantic embedding via Vertex AI text-embedding.

    Raises ProviderConfigError when creds/SDK are missing and ValueError on a
    dimension mismatch. It NEVER silently falls back to the fake provider: a
    hidden fallback would publish lexical vectors as if they were semantic,
    which is exactly the kind of dishonest telemetry this system forbids.
    """
    model = _get_vertex_model()
    from google.api_core.exceptions import PermissionDenied, Unauthenticated
    from google.auth.exceptions import DefaultCredentialsError, RefreshError

    try:
        result = model.get_embeddings([text])
    except (DefaultCredentialsError, RefreshError, PermissionDenied, Unauthenticated) as exc:
        raise ProviderConfigError(
            "Vertex embeddings auth error: run `gcloud auth application-default login`."
        ) from exc

    values = list(result[0].values)
    if len(values) != EMBED_DIM:
        raise ValueError(
            f"Vertex embedding dim {len(values)} != EMBED_DIM {EMBED_DIM}; "
            f"pick a {EMBED_DIM}-dim vertex_embedding_model."
        )
    return values


def embed_text(text: str) -> list[float]:
    """Embed text into a fixed EMBED_DIM vector.

    Dispatches on settings.embedding_provider: "vertex" for real semantic
    embeddings (requires GOOGLE_CLOUD_* creds), otherwise the deterministic
    hashed-bag-of-words fallback. Same signature for every caller (ingestion
    + query-time retrieval), so flipping the provider needs no call-site edits.
    """
    provider = (get_settings().embedding_provider or "fake").lower()
    if provider == "vertex":
        return _embed_text_vertex(text)
    return _embed_text_fake(text)
