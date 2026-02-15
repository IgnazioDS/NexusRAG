from __future__ import annotations

from nexusrag.core.config import get_settings
from nexusrag.services.crypto.kms.aws import AwsKmsProvider
from nexusrag.services.crypto.kms.base import KmsProvider
from nexusrag.services.crypto.kms.gcp import GcpKmsProvider
from nexusrag.services.crypto.kms.local import LocalKmsProvider


_KMS_PROVIDERS: dict[str, type[KmsProvider]] = {
    "local_kms": LocalKmsProvider,
    "aws_kms": AwsKmsProvider,
    "gcp_kms": GcpKmsProvider,
}


def get_kms_provider() -> KmsProvider:
    settings = get_settings()
    provider_name = settings.crypto_provider
    provider_cls = _KMS_PROVIDERS.get(provider_name)
    if provider_cls is None:
        raise ValueError(f"Unsupported KMS provider: {provider_name}")
    return provider_cls()
