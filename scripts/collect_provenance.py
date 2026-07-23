from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ProvenanceError(RuntimeError):
    pass


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run(command: list[str], *, cwd: Path) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ProvenanceError(f"Command failed: {' '.join(command)}: {exc}") from exc
    return completed.stdout.strip()


def git_provenance(repo_root: Path) -> dict[str, Any]:
    commit = run(["git", "rev-parse", "HEAD"], cwd=repo_root)
    changed = [
        line
        for line in run(["git", "status", "--porcelain"], cwd=repo_root).splitlines()
        if line.strip()
    ]
    return {
        "commit": commit,
        "short_commit": commit[:12],
        "state": "dirty" if changed else "clean",
        "changed_path_count": len(changed),
    }


def image_provenance(repo_root: Path, reference: str) -> dict[str, Any]:
    payload = json.loads(run(["docker", "image", "inspect", reference], cwd=repo_root))
    if len(payload) != 1:
        raise ProvenanceError(f"Expected exactly one image for {reference}")
    image = payload[0]
    image_id = str(image.get("Id") or "")
    if not image_id.startswith("sha256:"):
        raise ProvenanceError(f"Image {reference} has no immutable image ID")
    repo_digests = sorted(str(item) for item in image.get("RepoDigests") or [])
    return {
        "reference": reference,
        "image_id": image_id,
        "repo_digests": repo_digests,
        "immutable_reference": repo_digests[0] if repo_digests else image_id,
        "source_commit_label": (image.get("Config") or {}).get("Labels", {}).get(
            "org.opencontainers.image.revision"
        ),
    }


def _runtime_contract(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "config" / "runtime-contract.json"
    return json.loads(path.read_text(encoding="utf-8"))


def source_prompt_provenance(repo_root: Path) -> dict[str, Any]:
    manifest_path = repo_root / "secmind" / "backend" / "prompts" / "native" / "zh-CN" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    contract = _runtime_contract(repo_root)
    version = str(contract["version_sources"]["prompt"]["version"])
    records = sorted(
        [
            str(item["key"]),
            version,
            str(item["checksum"]),
            str(item.get("sourcePath") or item.get("path") or "bundled:zh-CN"),
        ]
        for item in manifest.get("prompts") or []
    )
    return {
        "active_count": len(records),
        "canonical_sha256": canonical_sha256(records),
        "records": records,
        "manifest": manifest_path.relative_to(repo_root).as_posix(),
    }


def _public_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ProvenanceError(f"Invalid environment entry at {path}:{line_number}")
        key, value = (part.strip() for part in line.split("=", 1))
        if any(marker in key.upper() for marker in ("KEY", "SECRET", "TOKEN", "PASSWORD")):
            raise ProvenanceError(f"Secret-like field is forbidden in public model config: {key}")
        values[key] = value
    return dict(sorted(values.items()))


def _key_configured() -> bool:
    if bool(os.getenv("SECMIND_LLM_API_KEY", "").strip()):
        return True
    key_file = os.getenv("SECMIND_LLM_API_KEY_FILE", "").strip()
    return bool(key_file and Path(key_file).is_file() and Path(key_file).stat().st_size > 0)


def source_model_provenance(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "config" / "model-public.env"
    values = _public_env(path)
    provider = values.get("SECMIND_LLM_PROVIDER", "null")
    api_key_configured = _key_configured()
    summary = {
        "provider": provider,
        "model": values.get("SECMIND_LLM_MODEL", ""),
        "base_url": values.get("SECMIND_LLM_BASE_URL", ""),
        "api_key_configured": api_key_configured,
        "configured": provider not in {"", "null", "none", "disabled"} and api_key_configured,
    }
    return {
        **summary,
        "canonical_sha256": canonical_sha256(summary),
        "public_config_sha256": canonical_sha256(values),
        "source": path.relative_to(repo_root).as_posix(),
    }


def _request_json(url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"Cannot read provenance endpoint {url}: {exc}") from exc


def _runtime_prompt_provenance(base_url: str) -> dict[str, Any]:
    query = """
    query ProvenancePrompts {
      prompts {
        promptKey
        activeVersionId
        versions { versionId version checksum status source }
      }
    }
    """
    payload = _request_json(f"{base_url}/graphql", {"query": query})
    if payload.get("errors"):
        raise ProvenanceError(f"GraphQL prompt provenance failed: {payload['errors']}")
    records: list[list[Any]] = []
    for prompt in (payload.get("data") or {}).get("prompts") or []:
        active_id = prompt.get("activeVersionId")
        active = next(
            (
                item
                for item in prompt.get("versions") or []
                if item.get("versionId") == active_id or str(item.get("status", "")).upper() == "ACTIVE"
            ),
            None,
        )
        if active is None:
            continue
        records.append(
            [
                str(prompt["promptKey"]),
                int(active["version"]),
                str(active["checksum"]),
                str(active["source"]),
            ]
        )
    records.sort(key=lambda item: item[0])
    return {
        "active_count": len(records),
        "canonical_sha256": canonical_sha256(records),
        "records": records,
    }


def _tool_provenance(tools: list[dict[str, Any]]) -> dict[str, Any]:
    definitions = sorted(
        (
            {
                "schema_version": item.get("schema_version"),
                "tool_id": item.get("tool_id"),
                "name": item.get("name"),
                "description": item.get("description"),
                "origin": item.get("origin"),
                "input_schema": item.get("input_schema") or {},
                "output_schema": item.get("output_schema") or {},
                "server_id": item.get("server_id"),
                "annotations": item.get("annotations") or {},
            }
            for item in tools
            if item.get("tool_id")
        ),
        key=lambda item: str(item["tool_id"]),
    )
    versions = [
        {
            "tool_id": item["tool_id"],
            "version": (item["annotations"].get("version") or item["schema_version"] or "unavailable"),
        }
        for item in definitions
    ]
    return {
        "count": len(definitions),
        "versions": versions,
        "canonical_sha256": canonical_sha256(definitions),
    }


def runtime_provenance(base_url: str) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    info = _request_json(f"{base_url}/api/v1/info")
    model = _request_json(f"{base_url}/api/v1/model-config")
    extensions = info.get("extensions") or {}
    model_summary = {
        "provider": model.get("provider"),
        "model": model.get("model"),
        "base_url": model.get("base_url"),
        "api_key_configured": bool(model.get("api_key_configured")),
        "configured": bool(model.get("configured")),
    }
    return {
        "url": base_url,
        "build": extensions.get("build") or {},
        "prompt": _runtime_prompt_provenance(base_url),
        "model": {**model_summary, "canonical_sha256": canonical_sha256(model_summary)},
        "tool": _tool_provenance(extensions.get("tools") or []),
    }


def parse_named_value(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("expected NAME=VALUE")
    name, raw_value = value.split("=", 1)
    if not name.strip() or not raw_value.strip():
        raise argparse.ArgumentTypeError("expected non-empty NAME=VALUE")
    return name.strip(), raw_value.strip()


def collect(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve()
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "collected_at": datetime.now(UTC).isoformat(),
        "source": {
            "git": git_provenance(repo_root),
            "prompt": source_prompt_provenance(repo_root),
            "model": source_model_provenance(repo_root),
            "tool": {
                "count": "unavailable",
                "versions": "unavailable",
                "canonical_sha256": "unavailable",
                "reason": "The full tool catalog is discovered at runtime; see runtime provenance.",
            },
        },
        "images": {
            name: image_provenance(repo_root, reference) for name, reference in args.image
        },
        "runtime": {name: runtime_provenance(url) for name, url in args.runtime},
    }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect non-secret SecMind change provenance")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--image", action="append", type=parse_named_value, default=[])
    parser.add_argument("--runtime", action="append", type=parse_named_value, default=[])
    args = parser.parse_args(argv)
    try:
        result = collect(args)
    except ProvenanceError as exc:
        print(f"provenance error: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        output = args.output if args.output.is_absolute() else args.repo_root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
