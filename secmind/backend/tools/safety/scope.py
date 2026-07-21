from __future__ import annotations

import fnmatch
import ipaddress
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from app.schemas.tools import UnifiedToolDefinition, UnifiedToolInvocation

PATH_KEYS = {"cwd", "directory", "file", "filename", "path", "workspace"}
HOST_KEYS = {"endpoint", "host", "hostname", "url", "uri"}
TARGET_KEYS = {"target", "targets"}


@dataclass(frozen=True, slots=True)
class ScopeDecision:
    allowed: bool
    reason: str
    policy_ids: tuple[str, ...]


class ToolScopeGuard:
    """Enforce declared invocation/definition scope without limiting undeclared MCP tools."""

    def evaluate(
        self,
        definition: UnifiedToolDefinition,
        invocation: UnifiedToolInvocation,
    ) -> ScopeDecision:
        policies = self._policies(definition, invocation)
        if not policies:
            return ScopeDecision(
                True,
                "No explicit scope constraint was declared.",
                ("SCOPE-OPEN",),
            )

        candidates = list(_scope_candidates(invocation.arguments))
        for policy in policies:
            denied = self._first_denied(candidates, policy)
            if denied is not None:
                key, value = denied
                return ScopeDecision(
                    False,
                    f"Argument {key} is outside the declared tool scope: {value}",
                    ("SCOPE-DECLARED-DENY",),
                )
        return ScopeDecision(
            True,
            "All target-like arguments are inside the declared tool scope.",
            ("SCOPE-DECLARED-ALLOW",),
        )

    @staticmethod
    def _policies(
        definition: UnifiedToolDefinition,
        invocation: UnifiedToolInvocation,
    ) -> list[dict[str, Any]]:
        values: list[Any] = [definition.annotations.get("scope"), invocation.metadata.get("scope")]
        return [dict(item) for item in values if isinstance(item, Mapping) and item]

    def _first_denied(
        self,
        candidates: list[tuple[str, str]],
        policy: dict[str, Any],
    ) -> tuple[str, str] | None:
        allowed_paths = _strings(policy.get("allowed_paths"))
        allowed_hosts = _strings(policy.get("allowed_hosts"))
        allowed_targets = _strings(policy.get("allowed_targets"))
        workspace = str(policy.get("workspace") or (allowed_paths[0] if allowed_paths else ""))

        for key, value in candidates:
            if key in PATH_KEYS and allowed_paths:
                if not _path_allowed(value, allowed_paths, workspace):
                    return key, value
            elif key in HOST_KEYS and allowed_hosts:
                if not _host_allowed(value, allowed_hosts):
                    return key, value
            elif key in TARGET_KEYS:
                if allowed_targets and not _target_allowed(value, allowed_targets):
                    return key, value
                if (
                    not allowed_targets
                    and allowed_hosts
                    and not _host_allowed(value, allowed_hosts)
                ):
                    return key, value
                if not allowed_targets and not allowed_hosts and allowed_paths:
                    if not _path_allowed(value, allowed_paths, workspace):
                        return key, value
        return None


def _scope_candidates(value: Any, parent_key: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in PATH_KEYS | HOST_KEYS | TARGET_KEYS:
                if isinstance(item, str):
                    yield normalized, item
                elif isinstance(item, list):
                    for element in item:
                        if isinstance(element, str):
                            yield normalized, element
            yield from _scope_candidates(item, normalized)
    elif isinstance(value, list):
        for item in value:
            yield from _scope_candidates(item, parent_key)


def _path_allowed(value: str, roots: list[str], workspace: str) -> bool:
    if value.startswith("file://"):
        value = unquote(urlsplit(value).path)
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = Path(workspace or roots[0]) / candidate
    try:
        resolved = candidate.resolve(strict=False)
    except OSError:
        return False
    for root in roots:
        try:
            allowed = Path(root).resolve(strict=False)
        except OSError:
            continue
        if resolved == allowed or allowed in resolved.parents:
            return True
    return False


def _host_allowed(value: str, allowed: list[str]) -> bool:
    raw = value if "://" in value else f"//{value}"
    try:
        host = (urlsplit(raw).hostname or value).rstrip(".").lower()
    except ValueError:
        return False
    for rule in allowed:
        normalized = rule.strip().rstrip(".").lower()
        try:
            if ipaddress.ip_address(host) in ipaddress.ip_network(normalized, strict=False):
                return True
        except ValueError:
            pass
        if fnmatch.fnmatchcase(host, normalized):
            return True
    return False


def _target_allowed(value: str, allowed: list[str]) -> bool:
    normalized = value.strip().lower()
    return any(fnmatch.fnmatchcase(normalized, item.strip().lower()) for item in allowed)


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
