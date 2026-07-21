from types import SimpleNamespace

from app.schemas.runtime import CapabilityStatus, CompletionMode, InputArtifact, TaskRequest
from app.services.capabilities import CapabilityRouter


def artifact(path: str) -> InputArtifact:
    return InputArtifact(
        original_name=path,
        relative_path=path,
        sha256="0" * 64,
        size_bytes=10,
        media_type="text/plain",
    )


def test_bandit_is_only_available_for_python_workspaces() -> None:
    router = CapabilityRouter()
    tools = [
        {"tool_id": "native:bandit_python_audit"},
        {"tool_id": "native:notes.record"},
    ]

    java = router.route(
        TaskRequest(objective="Audit this Java repository"),
        [artifact("Main.java")],
        tools,
        CompletionMode.FINDINGS,
    )
    python = router.route(
        TaskRequest(objective="Audit this Python repository"),
        [artifact("main.py")],
        tools,
        CompletionMode.FINDINGS,
    )

    assert "native:bandit_python_audit" not in java.allowed_tool_ids
    assert "native:bandit_python_audit" in python.allowed_tool_ids


def test_dynamic_web_and_missing_oracle_are_explicitly_routed() -> None:
    router = CapabilityRouter()
    web = router.route(
        TaskRequest(objective="Audit https://example.test for web vulnerabilities"),
        [],
        [{"tool_id": "mcp:local-web-security:nmap_service_scan"}],
        CompletionMode.FINDINGS,
    )
    pwn = router.route(
        TaskRequest(objective="Exploit the pwn binary and return the flag"),
        [],
        [],
        CompletionMode.FINAL_ANSWER,
    )

    assert web.status == CapabilityStatus.READY
    assert web.dynamic_target is True
    assert pwn.status == CapabilityStatus.UNAVAILABLE
    assert pwn.unavailable_reason is not None
    assert "unavailable" in pwn.unavailable_reason.lower()


def test_missing_optional_crypto_tool_degrades_without_blocking() -> None:
    plan = CapabilityRouter().route(
        TaskRequest(objective="Decode this cipher text"),
        [],
        [],
        CompletionMode.FINAL_ANSWER,
    )

    assert plan.task_kind == "crypto"
    assert plan.status == CapabilityStatus.DEGRADED
    assert plan.unavailable_reason is None
    assert len(plan.requirements) == 1
    assert plan.requirements[0].required is False
    assert plan.requirements[0].satisfied is False


def test_dfir_routes_wiremcp_and_filters_unrelated_tools() -> None:
    tools = [
        SimpleNamespace(tool_id="mcp:local-wiremcp:analyze_pcap"),
        {"tool_id": "mcp:local-web-security:nuclei_scan"},
        {"tool_id": "native:notes.record"},
    ]

    plan = CapabilityRouter().route(
        TaskRequest(objective="Perform DFIR analysis of the supplied PCAP"),
        [artifact("traffic.pcap")],
        tools,
        CompletionMode.FINDINGS,
    )

    assert plan.task_kind == "dfir"
    assert plan.status == CapabilityStatus.READY
    assert plan.requirements[0].matched_tool_ids == ["mcp:local-wiremcp:analyze_pcap"]
    assert plan.allowed_tool_ids == [
        "mcp:local-wiremcp:analyze_pcap",
        "native:notes.record",
    ]


def test_dynamic_web_without_matching_tool_is_unavailable() -> None:
    plan = CapabilityRouter().route(
        TaskRequest(objective="Assess https://example.test for XSS"),
        [],
        [{"tool_id": "native:notes.record"}],
        CompletionMode.FINDINGS,
    )

    assert plan.task_kind == "web"
    assert plan.dynamic_target is True
    assert plan.status == CapabilityStatus.UNAVAILABLE
    assert plan.allowed_tool_ids == ["native:notes.record"]
    assert plan.requirements[0].satisfied is False
