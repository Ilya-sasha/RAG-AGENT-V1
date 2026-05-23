from __future__ import annotations

import json
import logging
from typing import Any


def build_log_payload(
    message: str,
    *,
    component: str,
    context: dict[str, Any],
    fields: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {"message": message, "component": component}
    payload.update(context)
    payload.update(fields)
    return payload


def emit_structured_log(
    logger: logging.Logger,
    message: str,
    *,
    component: str,
    context: dict[str, Any],
    fields: dict[str, Any],
) -> None:
    try:
        payload = build_log_payload(
            message,
            component=component,
            context=context,
            fields=fields,
        )
        logger.info(json.dumps(payload, sort_keys=True, default=str))
    except Exception:
        return
