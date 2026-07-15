from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from app.schemas.runtime import (
    Evidence,
    Finding,
    RiskLevel,
    RuntimeToolContext,
    RuntimeToolResult,
    Scenario,
    ToolManifest,
    ToolStatus,
)
from tools.runtime import RuntimeTool, RuntimeToolError, RuntimeToolRegistry

REMEDIATIONS = {
    "B105": "Move hard-coded secrets to an injected secret store and rotate exposed values.",
    "B301": "Avoid unsafe deserialization; use a safe, schema-validated format such as JSON.",
    "B602": "Avoid shell=True and pass a fixed argument vector to subprocess APIs.",
    "B608": "Use parameterized queries rather than constructing SQL with string interpolation.",
}


class BanditTool(RuntimeTool):
    manifest = ToolManifest(
        name="bandit_python_audit",
        version="1",
        description=(
            "Run Bandit static security analysis over Python source in the controlled workspace."
        ),
        scenarios=[Scenario.CODE_AUDIT],
        input_schema={
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": ["target"],
            "additionalProperties": False,
        },
        output_schema={"type": "object", "properties": {"findings": {"type": "array"}}},
        risk_level=RiskLevel.R1,
        permissions=["workspace:read"],
        timeout_seconds=120,
        idempotent=True,
        requires_network=False,
    )

    async def invoke(self, args: dict[str, Any], context: RuntimeToolContext) -> RuntimeToolResult:
        started = time.monotonic()
        try:
            target = self._resolve_target(str(args.get("target", ".")), context)
        except RuntimeToolError as exc:
            return RuntimeToolResult(
                status=ToolStatus.DENIED,
                error_code="TOOL_SCOPE_VIOLATION",
                error_message=str(exc),
            )
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "bandit",
            "-r",
            str(target),
            "-f",
            "json",
            "-q",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=context.workspace,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.manifest.timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            return RuntimeToolResult(
                status=ToolStatus.TIMEOUT,
                duration_ms=int((time.monotonic() - started) * 1000),
                error_code="TOOL_TIMEOUT",
                error_message="Bandit exceeded its execution deadline.",
            )
        if process.returncode not in {0, 1}:
            return RuntimeToolResult(
                status=ToolStatus.ERROR,
                duration_ms=int((time.monotonic() - started) * 1000),
                error_code="BANDIT_FAILED",
                error_message=stderr.decode(errors="replace")[-2000:],
            )
        try:
            body = json.loads(stdout.decode(errors="replace") or "{}")
        except json.JSONDecodeError as exc:
            return RuntimeToolResult(
                status=ToolStatus.ERROR,
                duration_ms=int((time.monotonic() - started) * 1000),
                error_code="BANDIT_INVALID_JSON",
                error_message=str(exc),
            )
        evidence: list[Evidence] = []
        findings: list[dict[str, Any]] = []
        for item in body.get("results", []):
            evidence_id = hashlib.sha256(
                json.dumps(item, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()[:24]
            ev = Evidence(
                evidence_id=evidence_id,
                source=f"bandit:{self.manifest.version}",
                summary=(
                    f"{item.get('test_id', 'UNKNOWN')} at "
                    f"{item.get('filename')}:{item.get('line_number')}"
                ),
                metadata={
                    "tool_version": self.manifest.version,
                    "test_id": item.get("test_id"),
                    "test_name": item.get("test_name"),
                },
            )
            evidence.append(ev)
            finding = Finding(
                rule_id=item.get("test_id", "UNKNOWN"),
                severity=item.get("issue_severity", "UNKNOWN"),
                confidence=item.get("issue_confidence", "UNKNOWN"),
                path=item.get("filename", "unknown"),
                line=item.get("line_number"),
                title=item.get("test_name", item.get("test_id", "Bandit finding")),
                description=item.get("issue_text", ""),
                remediation=REMEDIATIONS.get(item.get("test_id")),
                evidence_ids=[evidence_id],
                raw=item,
            )
            findings.append(finding.model_dump(mode="json"))
        return RuntimeToolResult(
            status=ToolStatus.SUCCESS,
            data={"findings": findings, "metrics": body.get("metrics", {})},
            summary=f"Bandit completed with {len(findings)} finding(s).",
            evidence=evidence,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    @staticmethod
    def _resolve_target(value: str, context: RuntimeToolContext) -> Path:
        workspace = Path(context.workspace).resolve()
        candidate = (
            (workspace / value).resolve()
            if not Path(value).is_absolute()
            else Path(value).resolve()
        )
        allowed = [Path(path).resolve() for path in context.allowed_paths]
        if not any(candidate == root or root in candidate.parents for root in allowed):
            raise RuntimeToolError("Tool target is outside the allowed workspace")
        if not candidate.exists():
            raise RuntimeToolError("Tool target does not exist")
        return candidate


def default_runtime_registry() -> RuntimeToolRegistry:
    registry = RuntimeToolRegistry()
    registry.register(BanditTool())
    return registry
