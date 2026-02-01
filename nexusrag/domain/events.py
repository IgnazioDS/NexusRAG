from __future__ import annotations

from typing import Any, TypedDict, Literal


class TokenDeltaData(TypedDict):
    delta: str


class MessageFinalData(TypedDict):
    text: str
    citations: list[dict[str, Any]]


class ErrorData(TypedDict):
    message: str
    code: str


class EventPayload(TypedDict, total=False):
    type: Literal["token.delta", "message.final", "error"]
    data: dict[str, Any]
