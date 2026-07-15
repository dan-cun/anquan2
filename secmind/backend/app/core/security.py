from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from app.core.config import Settings

HTTP_EXEMPT_PATHS = {"/", "/health", "/docs", "/openapi.json", "/redoc"}


def is_valid_api_key(settings: Settings, supplied: str | None) -> bool:
    expected = settings.resolved_api_key
    if expected is None:
        return True
    if supplied is None:
        return False
    return hmac.compare_digest(supplied, expected)


class InMemoryRateLimiter:
    def __init__(self, *, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        cutoff = now - self.window_seconds
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= self.max_requests:
            return False
        hits.append(now)
        return True


def install_security_middleware(app: object, settings: Settings) -> None:
    limiter = InMemoryRateLimiter(
        max_requests=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )

    @app.middleware("http")  # type: ignore[attr-defined]
    async def security_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path in HTTP_EXEMPT_PATHS:
            return await call_next(request)

        if not is_valid_api_key(settings, request.headers.get("x-api-key")):
            return JSONResponse({"detail": "Invalid or missing API key"}, status_code=401)

        if settings.rate_limit_enabled:
            client_host = request.client.host if request.client else "unknown"
            key = f"{client_host}:{request.url.path}"
            if not limiter.allow(key):
                return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)

        return await call_next(request)
