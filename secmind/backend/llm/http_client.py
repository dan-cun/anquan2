from __future__ import annotations

import httpx


def create_http_client() -> httpx.AsyncClient:
    """Create a short-lived client for one bounded model request."""
    return httpx.AsyncClient()
