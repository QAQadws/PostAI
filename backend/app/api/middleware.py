from __future__ import annotations

import json
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from app.core.logging import get_logger

logger = get_logger("api")

MAX_BODY_LOG_CHARS = 2000
SENSITIVE_HEADERS = {"authorization", "x-api-key", "cookie", "set-cookie"}


def _mask_headers(headers: dict[str, str]) -> dict[str, str]:
    masked: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in SENSITIVE_HEADERS:
            masked[key] = value[:12] + "***" if len(value) > 12 else "***"
        else:
            masked[key] = value
    return masked


def _truncate(text: str, max_chars: int = MAX_BODY_LOG_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"... [truncated, total {len(text)} chars]"


def _safe_json(body: bytes) -> str:
    try:
        obj = json.loads(body)
        return json.dumps(obj, ensure_ascii=False)
    except (json.JSONDecodeError, UnicodeDecodeError):
        text = body.decode("utf-8", errors="replace")
        return _truncate(text)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()

        # ---- Log request ----
        body_bytes = await request.body()
        body_display = _safe_json(body_bytes) if body_bytes else "(empty)"
        logger.info(
            "--> REQUEST  | %s %s | client=%s | headers=%s | body=%s",
            request.method,
            str(request.url),
            request.client.host if request.client else "-",
            json.dumps(_mask_headers(dict(request.headers)), ensure_ascii=False),
            _truncate(body_display),
        )

        # ---- Call downstream ----
        response = await call_next(request)
        elapsed = (time.perf_counter() - start) * 1000

        # ---- Log response (skip body for streaming) ----
        if isinstance(response, StreamingResponse):
            logger.info(
                "<-- RESPONSE | %s %s | status=%d | duration=%.1fms | body=(streaming)",
                request.method,
                str(request.url),
                response.status_code,
                elapsed,
            )
            return response

        # Collect response body
        resp_body = b""
        async for chunk in response.body_iterator:
            resp_body += chunk

        resp_display = _safe_json(resp_body) if resp_body else "(empty)"
        logger.info(
            "<-- RESPONSE | %s %s | status=%d | duration=%.1fms | body=%s",
            request.method,
            str(request.url),
            response.status_code,
            elapsed,
            _truncate(resp_display),
        )

        return Response(
            content=resp_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
