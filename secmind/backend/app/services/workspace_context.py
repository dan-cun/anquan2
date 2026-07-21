from __future__ import annotations

import re
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


def relevant_workspace_chunks(
    state: AgentState,
    *,
    max_files: int = 12,
    max_chars_per_file: int = 12_000,
    max_total_chars: int = 60_000,
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    workspace = Path(state.workspace).resolve()
    keywords = {
        token
        for token in re.findall(r"[a-zA-Z0-9_]{3,}", state.task.objective.lower())
        if token not in {"this", "that", "with", "from", "task", "security"}
    }

    def score(item: InputArtifact) -> tuple[int, int, str]:
        path = item.relative_path.lower()
        return (-sum(token in path for token in keywords), item.size_bytes, path)

    chunks: list[dict[str, object]] = []
    failures: list[dict[str, str]] = []
    remaining = max_total_chars
    for artifact in sorted(state.input_artifacts, key=score):
        if len(chunks) >= max_files or remaining <= 0:
            break
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
            }
        )
        remaining -= len(content)
    return chunks, failures
