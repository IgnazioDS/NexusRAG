from __future__ import annotations

from typing import Iterable


def simple_chunk(text: str, max_tokens: int = 200) -> Iterable[str]:
    words = text.split()
    for i in range(0, len(words), max_tokens):
        yield " ".join(words[i : i + max_tokens])
