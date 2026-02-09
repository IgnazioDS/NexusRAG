from __future__ import annotations

import pytest
from fastapi import HTTPException

from nexusrag.services.self_serve import enforce_key_limit


def test_enforce_key_limit_allows_under_limit() -> None:
    enforce_key_limit(active_count=2, max_active=5)


def test_enforce_key_limit_blocks_at_limit() -> None:
    with pytest.raises(HTTPException) as exc:
        enforce_key_limit(active_count=3, max_active=3)

    detail = exc.value.detail
    assert detail["code"] == "KEY_LIMIT_REACHED"
    assert detail["max_active"] == 3
