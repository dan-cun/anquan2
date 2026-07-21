from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REDACTED = "[REDACTED]"
SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "cookie",
    "credentials",
    "passwd",
    "password",
    "passphrase",
    "private_key",
    "refresh_token",
    "secret",
    "session_id",
    "session_token",
    "set_cookie",
    "token",
    "access_token",
}
SENSITIVE_COMPACT_KEYS = {item.replace("_", "") for item in SENSITIVE_KEYS}
SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "code",
    "key",
    "password",
    "secret",
    "signature",
    "sig",
    "token",
}
AUTH_PATTERN = re.compile(
    r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=-]{4,}"
)
INLINE_SECRET_PATTERN = re.compile(
    r"(?i)\b(password|passwd|api[_-]?key|secret|token)\s*[:=]\s*([^\s,;]+)"
)
PEM_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
URL_PATTERN = re.compile(r"https?://[^\s'\"<>]+")


def redact_tool_value(value: Any) -> Any:
    """Return a JSON-compatible copy with common credentials removed."""

    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _sensitive_key(str(key)) else redact_tool_value(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_tool_value(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def safe_error_message(error: BaseException | str, *, max_length: int = 2_000) -> str:
    raw = str(error)
    safe = str(redact_tool_value(raw)).strip()
    return safe[:max_length] or type(error).__name__


def _sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
    compact = normalized.replace("_", "")
    if normalized in SENSITIVE_KEYS or compact in SENSITIVE_COMPACT_KEYS:
        return True
    return any(
        normalized.endswith(f"_{suffix}")
        for suffix in ("password", "secret", "token", "api_key", "private_key")
    )


def _redact_string(value: str) -> str:
    result = PEM_PRIVATE_KEY_PATTERN.sub(REDACTED, value)
    result = AUTH_PATTERN.sub(lambda match: f"{match.group(1)} {REDACTED}", result)
    result = INLINE_SECRET_PATTERN.sub(lambda match: f"{match.group(1)}={REDACTED}", result)
    return URL_PATTERN.sub(_redact_url, result)


def _redact_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    trailing = ""
    while raw and raw[-1] in ".,;)}":
        trailing = raw[-1] + trailing
        raw = raw[:-1]
    try:
        parts = urlsplit(raw)
        hostname = parts.hostname or ""
        port = f":{parts.port}" if parts.port is not None else ""
        netloc = f"{hostname}{port}"
        query_items = parse_qsl(parts.query, keep_blank_values=True)
        if parts.query == REDACTED or any(
            _sensitive_query_key(key) for key, _ in query_items
        ):
            query = REDACTED
        else:
            query = urlencode(query_items, doseq=True, safe="[]")
        return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment)) + trailing
    except (TypeError, ValueError):
        return "[REDACTED_URL]" + trailing


def _sensitive_query_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
    return normalized in SENSITIVE_QUERY_KEYS or any(
        normalized.endswith(f"_{suffix}")
        for suffix in ("credential", "key", "password", "secret", "signature", "token")
    )
