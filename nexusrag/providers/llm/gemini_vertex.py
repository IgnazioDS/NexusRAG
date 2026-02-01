from __future__ import annotations

from typing import Iterable

from nexusrag.core.config import get_settings
from nexusrag.core.errors import ProviderConfigError


class GeminiVertexProvider:
    def __init__(self) -> None:
        self._settings = get_settings()

    def _format_messages(self, messages: list[dict]) -> str:
        lines = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            lines.append(f"{role.upper()}: {content}")
        return "\n".join(lines)

    def stream(self, messages: list[dict]) -> Iterable[str]:
        if not self._settings.google_cloud_project or not self._settings.google_cloud_location:
            raise ProviderConfigError(
                "Vertex AI configuration missing: set GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION."
            )

        try:
            from vertexai import init
            from vertexai.generative_models import GenerativeModel
        except Exception as exc:  # pragma: no cover - import errors are environment-specific
            raise ProviderConfigError(
                "Vertex AI SDK not available. Install google-cloud-aiplatform."
            ) from exc

        try:
            init(project=self._settings.google_cloud_project, location=self._settings.google_cloud_location)
            model = GenerativeModel(self._settings.gemini_model)

            prompt = self._format_messages(messages)
            responses = model.generate_content(
                prompt,
                stream=True,
            )

            for response in responses:
                delta = getattr(response, "text", None)
                if delta:
                    yield delta
        except ProviderConfigError:
            raise
        except Exception as exc:
            raise ProviderConfigError(
                "Vertex AI request failed. Check credentials and model access."
            ) from exc
