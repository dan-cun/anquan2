from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from app.schemas.runtime import AgentState, InputArtifact

TEXT_SUFFIXES = {
    ".c",
    ".cc",
    ".conf",
    ".cpp",
    ".cs",
    ".go",
    ".html",
    ".java",
    ".js",
    ".json",
    ".log",
    ".md",
    ".php",
    ".properties",
    ".py",
    ".rs",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

GENERIC_TASK_TERMS = {
    "audit",
    "code",
    "finding",
    "findings",
    "repository",
    "security",
    "source",
    "task",
    "this",
    "that",
    "with",
    "from",
}
SOURCE_DIRECTORY_HINTS = {
    "app",
    "backend",
    "core",
    "lib",
    "server",
    "src",
}
LOW_PRIORITY_DIRECTORY_HINTS = {
    ".git",
    "build",
    "dist",
    "docs",
    "examples",
    "fixtures",
    "node_modules",
    "tests",
    "test",
    "vendor",
}
SECURITY_PATH_HINTS = {
    "auth",
    "config",
    "handler",
    "http",
    "parser",
    "permission",
    "protocol",
    "request",
    "security",
    "server",
    "session",
    "token",
}


def workspace_manifest_projection(
    state: AgentState,
    *,
    max_files: int = 64,
) -> dict[str, object]:
    """Return a bounded workspace index without embedding file contents."""

    keywords = _task_keywords(state)
    artifacts = _ranked_artifacts(state.input_artifacts, keywords)
    suffix_counts = Counter(
        Path(item.relative_path).suffix.lower() or "[no-extension]" for item in artifacts
    )
    selected = artifacts[:max_files]
    return {
        "file_count": len(artifacts),
        "total_size_bytes": sum(item.size_bytes for item in artifacts),
        "suffix_counts": dict(sorted(suffix_counts.items())),
        "files": [
            {
                "artifact_id": item.artifact_id,
                "path": item.relative_path,
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
                "media_type": item.media_type,
                "relevance_score": _artifact_relevance(item, keywords),
            }
            for item in selected
        ],
        "omitted_file_count": max(0, len(artifacts) - len(selected)),
    }


def relevant_workspace_chunks(
    state: AgentState,
    *,
    max_files: int = 8,
    max_chars_per_file: int = 8_000,
    max_total_chars: int = 24_000,
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    workspace = Path(state.workspace).resolve()
    keywords = _task_keywords(state)

    chunks: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    remaining = max_total_chars
    seen_paths: set[str] = set()
    for artifact in _ranked_artifacts(state.input_artifacts, keywords):
        if len(chunks) >= max_files or remaining <= 0:
            break
        normalized_path = artifact.relative_path.replace("\\", "/")
        if normalized_path in seen_paths:
            continue
        seen_paths.add(normalized_path)
        candidate = (workspace / artifact.relative_path).resolve()
        if workspace not in candidate.parents or not candidate.is_file() or candidate.is_symlink():
            failures.append(
                {
                    "path": artifact.relative_path,
                    "error_type": "WorkspaceBoundaryError",
                    "error_message": "Artifact is unavailable inside the controlled workspace",
                }
            )
            continue
        if candidate.suffix.lower() not in TEXT_SUFFIXES and not artifact.media_type.startswith(
            "text/"
        ):
            continue
        limit = min(max_chars_per_file, remaining)
        try:
            content = candidate.read_text(encoding="utf-8", errors="replace")[:limit]
        except OSError as error:
            failures.append(
                {
                    "path": artifact.relative_path,
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                }
            )
            continue
        if not content:
            continue
        chunks.append(
            {
                "artifact_id": artifact.artifact_id,
                "path": artifact.relative_path,
                "sha256": artifact.sha256,
                "start_line": 1,
                "end_line": content.count("\n") + 1,
                "content": content,
                "truncated": artifact.size_bytes > len(content.encode("utf-8")),
                "relevance_score": _artifact_relevance(artifact, keywords),
            }
        )
        remaining -= len(content)
    return chunks, failures


def _task_keywords(state: AgentState) -> set[str]:
    task_text = " ".join(
        [
            state.task.objective,
            *state.task.constraints,
            *state.task.expected_outputs,
            *state.task.target_scope,
        ]
    ).lower()
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9_]{3,}", task_text)
        if token not in GENERIC_TASK_TERMS
    }


def _ranked_artifacts(
    artifacts: list[InputArtifact],
    keywords: set[str],
) -> list[InputArtifact]:
    return sorted(
        artifacts,
        key=lambda item: (
            -_artifact_relevance(item, keywords),
            item.size_bytes,
            item.relative_path.lower(),
        ),
    )


def _artifact_relevance(item: InputArtifact, keywords: set[str]) -> int:
    path = item.relative_path.replace("\\", "/").lower()
    parts = set(Path(path).parts)
    score = sum(12 for token in keywords if token in path)
    score += sum(3 for token in SECURITY_PATH_HINTS if token in path)
    score += 4 if parts & SOURCE_DIRECTORY_HINTS else 0
    score -= 8 * len(parts & LOW_PRIORITY_DIRECTORY_HINTS)
    if Path(path).suffix.lower() in TEXT_SUFFIXES or item.media_type.startswith("text/"):
        score += 2
    return score
