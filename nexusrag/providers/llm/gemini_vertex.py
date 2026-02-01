from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Iterable

from nexusrag.core.config import get_settings
from nexusrag.core.errors import ProviderConfigError, VertexAuthError, VertexTimeoutError

logger = logging.getLogger(__name__)


class GeminiVertexProvider:
    def __init__(self, request_id: str | None = None, cancel_event: threading.Event | None = None) -> None:
        self._settings = get_settings()
        self._request_id = request_id
        # Optional cancellation signal from the caller to stop streaming early.
        self._cancel_event = cancel_event

    def _format_messages(self, messages: list[dict]) -> str:
        # Preserve roles and keep system guidance at the top of the prompt.
        system_lines: list[str] = []
        other_lines: list[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            line = f"{role.upper()}: {content}"
            if role == "system":
                system_lines.append(line)
            else:
                other_lines.append(line)
        return "\n".join(system_lines + other_lines)

    def _validate_config(self) -> tuple[str, str, str]:
        # Fail fast to avoid confusing downstream SDK errors.
        project = self._settings.google_cloud_project
        location = self._settings.google_cloud_location
        model = self._settings.gemini_model
        missing = []
        if not project:
            missing.append("GOOGLE_CLOUD_PROJECT")
        if not location:
            missing.append("GOOGLE_CLOUD_LOCATION")
        if not model:
            missing.append("GEMINI_MODEL")
        if missing:
            raise ProviderConfigError(
                f"Vertex config missing: set {', '.join(missing)} in .env."
            )
        return project, location, model

    def stream(self, messages: list[dict]) -> Iterable[str]:
        project, location, model_name = self._validate_config()
        timeout_s = max(1, int(self._settings.vertex_stream_timeout_s))

        try:
            from vertexai import init
            from vertexai.generative_models import GenerativeModel
            from google.auth.exceptions import DefaultCredentialsError, RefreshError
            from google.api_core.exceptions import PermissionDenied, Unauthenticated
        except Exception as exc:  # pragma: no cover - import errors are environment-specific
            raise ProviderConfigError(
                "Vertex AI SDK not available. Install google-cloud-aiplatform."
            ) from exc

        try:
            logger.info("vertex_stream_start request_id=%s model=%s", self._request_id, model_name)
            init(project=project, location=location)
            model = GenerativeModel(model_name)

            prompt = self._format_messages(messages)
            responses = model.generate_content(
                prompt,
                stream=True,
            )

            deadline = time.monotonic() + timeout_s
            for response in responses:
                if self._cancel_event is not None and self._cancel_event.is_set():
                    # Propagate cancellation to stop the caller's stream promptly.
                    raise asyncio.CancelledError
                if time.monotonic() > deadline:
                    raise VertexTimeoutError("Vertex stream timed out.")
                delta = getattr(response, "text", None)
                if delta:
                    # Yield token deltas immediately to preserve streaming behavior.
                    yield delta
        except ProviderConfigError:
            raise
        except (DefaultCredentialsError, RefreshError, PermissionDenied, Unauthenticated) as exc:
            logger.warning("vertex_stream_auth_error request_id=%s", self._request_id)
            raise VertexAuthError(
                "Vertex auth error: run `gcloud auth application-default login`."
            ) from exc
        except VertexTimeoutError:
            logger.warning("vertex_stream_timeout request_id=%s", self._request_id)
            raise
        except asyncio.CancelledError:
            # Allow caller cancellation to bubble up for disconnect handling.
            raise
        except Exception as exc:
            logger.error("vertex_stream_error request_id=%s", self._request_id)
            raise ProviderConfigError(
                "Vertex AI request failed. Check credentials and model access."
            ) from exc
