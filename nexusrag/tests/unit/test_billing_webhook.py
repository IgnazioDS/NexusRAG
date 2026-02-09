from __future__ import annotations

import hmac
import hashlib

from nexusrag.services.billing_webhook import build_billing_signature


def test_build_billing_signature_matches_hmac() -> None:
    secret = "supersecret"
    payload = b'{"event":"test"}'
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    assert build_billing_signature(secret, payload) == expected
