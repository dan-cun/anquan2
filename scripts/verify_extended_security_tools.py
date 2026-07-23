from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


ENDPOINT = "http://127.0.0.1:9017/mcp"
EXPECTED_TOOLS = {
    "extended_tool_versions", "trivy_scan", "osv_scan", "yara_scan",
    "volatility_plugins", "volatility_analyze", "ghidra_headless_analyze",
    "gdb_inspect", "mitmproxy_flow_summary", "subfinder_discover",
    "dnsx_resolve", "naabu_scan", "zap_baseline_scan", "binwalk_scan",
    "capa_analyze", "floss_extract", "oletools_analyze", "checksec_binary",
    "ropgadget_scan", "pwntools_elf_summary", "pwndbg_check",
}


def prepare_smoke_data(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    sample = root / "sample.txt"
    sample.write_text("SecMind harmless smoke sample\nmarker=SECMIND_TEST_ONLY\n", encoding="utf-8")
    rules = root / "smoke.yar"
    rules.write_text(
        'rule SecMindSmoke { strings: $marker = "SECMIND_TEST_ONLY" condition: $marker }\n',
        encoding="utf-8",
    )
    flow = root / "empty.mitm"
    flow.write_bytes(b"")
    package_lock = root / "package-lock.json"
    package_lock.write_text(
        json.dumps(
            {
                "name": "secmind-smoke",
                "version": "1.0.0",
                "lockfileVersion": 3,
                "requires": True,
                "packages": {
                    "": {
                        "name": "secmind-smoke",
                        "version": "1.0.0",
                        "dependencies": {"lodash": "4.17.21"},
                    },
                    "node_modules/lodash": {"version": "4.17.21"},
                },
                "dependencies": {"lodash": {"version": "4.17.21"}},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {"sample": sample, "rules": rules, "flow": flow}


def _payload(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured
    content = getattr(result, "content", None) or []
    return [getattr(item, "text", str(item)) for item in content]


async def verify(args: argparse.Namespace) -> dict[str, Any]:
    smoke = prepare_smoke_data(args.smoke_root.resolve())
    calls: list[tuple[str, dict[str, Any]]] = [
        ("extended_tool_versions", {}),
        ("trivy_scan", {"path": str(args.smoke_root), "scanners": "secret", "timeout_seconds": 300}),
        ("yara_scan", {"rules_path": str(smoke["rules"]), "target_path": str(smoke["sample"])}),
        ("volatility_plugins", {"filter_text": "pslist"}),
        ("gdb_inspect", {"binary_path": str(args.pe_sample), "mode": "files"}),
        ("mitmproxy_flow_summary", {"flow_path": str(smoke["flow"])}),
        ("dnsx_resolve", {"hosts": ["localhost"], "timeout_seconds": 60}),
        ("naabu_scan", {"target": "127.0.0.1", "ports": str(args.local_port), "timeout_seconds": 60}),
        ("capa_analyze", {"file_path": str(args.pe_sample), "timeout_seconds": 300}),
        ("floss_extract", {"file_path": str(args.pe_sample), "timeout_seconds": 300}),
        ("oletools_analyze", {"file_path": str(smoke["sample"]), "analyzer": "oleid"}),
    ]
    if args.elf_sample and args.elf_sample.exists():
        calls += [
            ("binwalk_scan", {"file_path": str(args.elf_sample)}),
            ("checksec_binary", {"file_path": str(args.elf_sample)}),
            ("ropgadget_scan", {"file_path": str(args.elf_sample), "depth": 6}),
            ("pwntools_elf_summary", {"file_path": str(args.elf_sample)}),
            ("pwndbg_check", {}),
        ]
    if args.include_network:
        calls += [("osv_scan", {"path": str(args.smoke_root), "timeout_seconds": 300})]
    if args.include_heavy:
        calls += [
            ("ghidra_headless_analyze", {"binary_path": str(args.pe_sample), "timeout_seconds": 600}),
            ("zap_baseline_scan", {"target_url": f"http://127.0.0.1:{args.local_port}/", "timeout_seconds": 600}),
        ]

    report: dict[str, Any] = {
        "verified_at": datetime.now(UTC).isoformat(),
        "endpoint": ENDPOINT,
        "tools": {},
        "calls": {},
    }
    async with streamable_http_client(ENDPOINT) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            initialized = await session.initialize()
            listed = await session.list_tools()
            names = {tool.name for tool in listed.tools}
            report["protocol_version"] = initialized.protocolVersion
            report["tools"] = {
                "count": len(names),
                "names": sorted(names),
                "missing": sorted(EXPECTED_TOOLS - names),
                "unexpected": sorted(names - EXPECTED_TOOLS),
            }
            for name, arguments in calls:
                try:
                    result = await session.call_tool(name, arguments=arguments)
                    report["calls"][name] = {
                        "protocol_error": bool(getattr(result, "isError", False)),
                        "payload": _payload(result),
                    }
                except Exception as error:  # Keep validating remaining independent tools.
                    report["calls"][name] = {"protocol_error": True, "exception": repr(error)}
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify SecMind extended security MCP tools")
    parser.add_argument("--smoke-root", type=Path, default=Path(r"D:\SecMind\workspaces\extended-smoke"))
    parser.add_argument(
        "--pe-sample",
        type=Path,
        default=Path(r"D:\SecMind\security-tools\ghidra\12.1.2\ghidra_12.1.2_PUBLIC\docs\GhidraClass\ExerciseFiles\WinhelloCPP\WinHelloCPP.exe"),
    )
    parser.add_argument("--elf-sample", type=Path, default=Path(r"D:\SecMind\workspaces\extended-smoke\ls.elf"))
    parser.add_argument("--local-port", type=int, default=15173)
    parser.add_argument("--include-network", action="store_true")
    parser.add_argument("--include-heavy", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(verify(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failed = report["tools"]["missing"] or any(
        item["protocol_error"]
        or (isinstance(item.get("payload"), dict) and item["payload"].get("ok") is False)
        for item in report["calls"].values()
    )
    print(json.dumps({"tool_count": report["tools"]["count"], "calls": len(report["calls"]), "failed": bool(failed)}))
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
