from __future__ import annotations

from typing import Iterable


# Chunking constants keep ingestion deterministic across runs.
CHUNK_SIZE_CHARS = 1200
CHUNK_OVERLAP_CHARS = 150


def _window_text(text: str, size: int, overlap: int) -> Iterable[tuple[str, int, int]]:
    # Use a stable sliding window for long paragraphs to preserve order.
    start = 0
    length = len(text)
    while start < length:
        end = min(length, start + size)
        yield text[start:end], start, end
        if end == length:
            break
        start = max(0, end - overlap)


def chunk_text(text: str) -> Iterable[tuple[str, int, int]]:
    # Prefer paragraph boundaries for readability; fall back to windows for long blocks.
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    cursor = 0
    for paragraph in paragraphs:
        if len(paragraph) <= CHUNK_SIZE_CHARS:
            start = text.find(paragraph, cursor)
            end = start + len(paragraph)
            cursor = end
            yield paragraph, start, end
            continue
        for chunk, start, end in _window_text(paragraph, CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS):
            yield chunk, start, end
