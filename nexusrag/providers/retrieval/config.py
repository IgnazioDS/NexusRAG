from __future__ import annotations

from typing import Any

from nexusrag.core.errors import RetrievalConfigError


DEFAULT_PROVIDER = "local_pgvector"
DEFAULT_TOP_K = 5
ALLOWED_PROVIDERS = {"local_pgvector", "aws_bedrock_kb", "gcp_vertex"}


def normalize_provider_config(config_json: dict[str, Any] | None) -> dict[str, Any]:
    # Treat empty config as a signal to use safe local defaults for bootstrapping.
    if config_json == {}:
        return {"retrieval": {"provider": DEFAULT_PROVIDER, "top_k_default": DEFAULT_TOP_K}}
    if config_json is None:
        raise RetrievalConfigError("retrieval config missing")

    if not isinstance(config_json, dict):
        raise RetrievalConfigError("retrieval config must be an object")

    retrieval = config_json.get("retrieval")
    if retrieval is None:
        raise RetrievalConfigError("retrieval config missing")
    if not isinstance(retrieval, dict):
        raise RetrievalConfigError("retrieval config must be an object")

    provider = retrieval.get("provider")
    if provider not in ALLOWED_PROVIDERS:
        raise RetrievalConfigError("unsupported retrieval provider")

    top_k_default = retrieval.get("top_k_default")
    if top_k_default is not None and not isinstance(top_k_default, int):
        raise RetrievalConfigError("top_k_default must be an integer")

    if provider == "aws_bedrock_kb":
        if not retrieval.get("knowledge_base_id") or not retrieval.get("region"):
            raise RetrievalConfigError("knowledge_base_id and region are required")

    if provider == "gcp_vertex":
        if not retrieval.get("project") or not retrieval.get("location") or not retrieval.get("resource_id"):
            raise RetrievalConfigError("project, location, and resource_id are required")

    normalized = dict(config_json)
    normalized_retrieval = dict(retrieval)
    if normalized_retrieval.get("top_k_default") is None:
        normalized_retrieval["top_k_default"] = DEFAULT_TOP_K
    normalized["retrieval"] = normalized_retrieval
    return normalized


def parse_retrieval_config(config_json: dict[str, Any] | None) -> dict[str, Any]:
    # Keep a single validation path so router and API stay consistent.
    normalized = normalize_provider_config(config_json)
    return normalized["retrieval"]
