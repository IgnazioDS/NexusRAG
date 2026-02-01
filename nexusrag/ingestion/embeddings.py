from __future__ import annotations

import hashlib
import math
import re

_DIM = 768
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _hash_token(token: str) -> tuple[int, float]:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    idx = int(digest[:8], 16) % _DIM
    sign = 1.0 if int(digest[8:12], 16) % 2 == 0 else -1.0
    magnitude = (int(digest[12:20], 16) % 1000) / 1000.0
    return idx, sign * (0.2 + magnitude)


def embed_text(text: str) -> list[float]:
    vector = [0.0] * _DIM
    tokens = _TOKEN_RE.findall(text.lower())
    if not tokens:
        return vector

    for token in tokens:
        idx, value = _hash_token(token)
        vector[idx] += value

    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector

    return [v / norm for v in vector]
