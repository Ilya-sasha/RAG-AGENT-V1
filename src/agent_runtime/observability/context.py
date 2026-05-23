from __future__ import annotations

from contextvars import ContextVar, Token

_REQUEST_CONTEXT: ContextVar[dict[str, str]] = ContextVar("request_context", default={})


def get_request_context() -> dict[str, str]:
    return dict(_REQUEST_CONTEXT.get())


def bind_request_context(**fields: str | None) -> Token[dict[str, str]]:
    current = get_request_context()
    current.update({key: value for key, value in fields.items() if value is not None})
    return _REQUEST_CONTEXT.set(current)


def reset_request_context(token: Token[dict[str, str]]) -> None:
    _REQUEST_CONTEXT.reset(token)
