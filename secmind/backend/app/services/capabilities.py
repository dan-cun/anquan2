from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from app.schemas.runtime import (
    CapabilityPlan,
    CapabilityRequirement,
    CapabilityStatus,
    CompletionMode,
    InputArtifact,
    TaskRequest,
)

LANGUAGE_BY_SUFFIX = {
    "c": "c",
    "cc": "cpp",
    "cpp": "cpp",
    "cs": "csharp",
    "go": "go",
    "java": "java",
    "js": "javascript",
    "php": "php",
    "py": "python",
    "rs": "rust",
    "ts": "typescript",
}

STATE_TOOL_TERMS = ("notes", "todo", "skill", "context")
TASK_TOOL_TERMS = {
    "code_audit": (
        "bandit",
        "semgrep",
        "gitleaks",
        "osv",
        "trivy",
        "independent_verify",
        *STATE_TOOL_TERMS,
    ),
    "web": ("chrome", "http-fetch", "web-security", *STATE_TOOL_TERMS),
    "crypto": ("cyberchef", *STATE_TOOL_TERMS),
    "dfir": (
        "exiftool",
        "volatility",
        "tshark",
        "wiremcp",
        "pcap",
        "forensic",
        *STATE_TOOL_TERMS,
    ),
    "pwn": ("pwn", "gdb", *STATE_TOOL_TERMS),
    "reverse": ("ghidra", "radare", "rizin", "reverse", *STATE_TOOL_TERMS),
}


class CapabilityRouter:
    def route(
        self,
        task: TaskRequest,
        artifacts: list[InputArtifact],
        tool_definitions: Iterable[Any],
        completion_mode: CompletionMode,
        unavailable_tool_ids: set[str] | None = None,
    ) -> CapabilityPlan:
        unavailable_tool_ids = unavailable_tool_ids or set()
        tool_ids = sorted(
            {
                str(getattr(item, "tool_id", None) or item.get("tool_id") or "")
                for item in tool_definitions
                if (
                    getattr(item, "tool_id", None)
                    or (isinstance(item, dict) and item.get("tool_id"))
                )
                and str(getattr(item, "tool_id", None) or item.get("tool_id") or "")
                not in unavailable_tool_ids
            }
        )
        languages = sorted(
            {
                LANGUAGE_BY_SUFFIX[suffix]
                for item in artifacts
                if (suffix := item.relative_path.rpartition(".")[2].lower()) in LANGUAGE_BY_SUFFIX
            }
        )
        text = " ".join(
            [task.objective, *task.constraints, *task.expected_outputs, *task.target_scope]
        ).lower()
        language_terms = {
            "python": ("python", ".py", "bandit"),
            "java": ("java", ".java"),
            "javascript": ("javascript", "node.js", ".js"),
            "typescript": ("typescript", ".ts"),
            "c": (" c code", ".c"),
            "cpp": ("c++", "cpp", ".cc", ".cpp"),
            "go": ("golang", ".go"),
            "rust": ("rust", ".rs"),
        }
        languages = sorted(
            set(languages)
            | {
                language
                for language, terms in language_terms.items()
                if any(term in text for term in terms)
            }
        )
        task_kind = self._task_kind(text, completion_mode)
        dynamic_target = bool(re.search(r"(?:https?://|\b\d{1,3}(?:\.\d{1,3}){3}\b)", text))
        requirements = self._requirements(task_kind, dynamic_target, tool_ids)
        missing = [item for item in requirements if item.required and not item.satisfied]
        optional_missing = [
            item for item in requirements if not item.required and not item.satisfied
        ]
        if missing:
            status = CapabilityStatus.UNAVAILABLE
            unavailable_reason = "; ".join(item.reason for item in missing)
        elif optional_missing:
            status = CapabilityStatus.DEGRADED
            unavailable_reason = None
        else:
            status = CapabilityStatus.READY
            unavailable_reason = None
        allowed = self._allowed_tools(task_kind, languages, tool_ids)
        return CapabilityPlan(
            task_kind=task_kind,
            languages=languages,
            dynamic_target=dynamic_target,
            status=status,
            requirements=requirements,
            allowed_tool_ids=allowed,
            unavailable_reason=unavailable_reason,
        )

    @staticmethod
    def _task_kind(text: str, completion_mode: CompletionMode) -> str:
        if "agentdojo" in text or "agent dojo" in text:
            return "agentdojo"
        if "splunk" in text:
            return "splunk"
        if any(term in text for term in ("pwn", "binary exploit", "buffer overflow", "栈溢出")):
            return "pwn"
        if any(term in text for term in ("reverse", "逆向", "反编译", "firmware")):
            return "reverse"
        if any(term in text for term in ("dfir", "forensic", "取证", "evtx", "pcap")):
            return "dfir"
        if any(term in text for term in ("crypto", "密码", "cipher", "decode")):
            return "crypto"
        if any(term in text for term in ("web", "xss", "sql injection", "http", "网页")):
            return "web"
        if completion_mode == CompletionMode.FINDINGS:
            return "code_audit"
        return "general"

    @staticmethod
    def _requirements(
        task_kind: str,
        dynamic_target: bool,
        tool_ids: list[str],
    ) -> list[CapabilityRequirement]:
        def matches(*terms: str) -> list[str]:
            return [tool_id for tool_id in tool_ids if any(term in tool_id for term in terms)]

        specs: list[tuple[str, bool, list[str], str]] = []
        if task_kind == "agentdojo":
            specs.append(
                (
                    "agentdojo_target",
                    True,
                    matches("agentdojo"),
                    "AgentDojo target is not provisioned",
                )
            )
        elif task_kind == "splunk":
            specs.append(
                ("splunk_runtime", True, matches("splunk"), "Splunk runtime is not provisioned")
            )
        elif task_kind == "pwn":
            specs.append(
                (
                    "binary_exploitation",
                    True,
                    matches("gdb", "pwntools", "pwn"),
                    "Pwn debugger/exploitation tools are unavailable",
                )
            )
        elif task_kind == "reverse":
            specs.append(
                (
                    "binary_analysis",
                    True,
                    matches("ghidra", "radare", "rizin", "reverse"),
                    "Binary analysis tools are unavailable",
                )
            )
        elif task_kind == "dfir":
            specs.append(
                (
                    "forensic_analysis",
                    True,
                    matches("exiftool", "volatility", "tshark", "wiremcp", "pcap", "forensic"),
                    "DFIR analysis tools are unavailable",
                )
            )
        elif task_kind == "crypto":
            specs.append(
                (
                    "crypto_transform",
                    False,
                    matches("cyberchef", "python", "crypto"),
                    "Cryptographic helper tools are unavailable",
                )
            )
        elif task_kind == "web" and dynamic_target:
            specs.append(
                (
                    "dynamic_web_target",
                    True,
                    matches("chrome", "http-fetch", "web-security"),
                    "Dynamic web target tools are unavailable",
                )
            )
        return [
            CapabilityRequirement(
                capability=name,
                required=required,
                satisfied=bool(found),
                matched_tool_ids=found,
                reason="" if found else reason,
            )
            for name, required, found, reason in specs
        ]

    @staticmethod
    def _allowed_tools(task_kind: str, languages: list[str], tool_ids: list[str]) -> list[str]:
        allowed = list(tool_ids)
        if "python" not in languages:
            allowed = [item for item in allowed if "bandit_python_audit" not in item]
        terms = TASK_TOOL_TERMS.get(task_kind)
        if terms is not None:
            allowed = [item for item in allowed if any(term in item for term in terms)]
        return sorted(allowed)
