from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from app.schemas.agents import AgentRole
from app.schemas.prompts import PromptMessageRole


@dataclass(frozen=True, slots=True)
class PromptDefinition:
    key: str
    content: str
    category: str
    message_role: PromptMessageRole
    name: str
    source_path: str | None = None
    variables: list[str] = field(default_factory=list)
    agent_role: AgentRole | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    checksum: str = ""

    @property
    def resolved_checksum(self) -> str:
        return self.checksum or hashlib.sha256(self.content.encode("utf-8")).hexdigest()


class NativePromptCatalog:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).resolve().parent / "native" / "zh-CN"

    def load(self) -> list[PromptDefinition]:
        manifest_path = self.root / "manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        definitions: list[PromptDefinition] = []
        for item in payload["prompts"]:
            template_path = self.root / item["path"]
            content = template_path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if checksum != item["checksum"]:
                raise ValueError(f"Prompt checksum mismatch: {item['key']}")
            try:
                agent_role = AgentRole(item["key"])
            except ValueError:
                agent_role = None
            definitions.append(
                PromptDefinition(
                    key=item["key"],
                    content=content,
                    category=item["category"],
                    message_role=PromptMessageRole(item["messageRole"]),
                    name=item["module"],
                    source_path=item.get("sourcePath") or None,
                    variables=list(item.get("variables") or []),
                    agent_role=agent_role,
                    metadata={
                        "locale": payload.get("locale", "zh-CN"),
                        "purpose": item.get("purpose", ""),
                        "stage": item.get("stage", ""),
                        "workbook_status": item.get("status", ""),
                        "workbook_notes": item.get("notes", ""),
                        "target_path": item.get("targetPath", ""),
                    },
                    checksum=checksum,
                )
            )
        return definitions
