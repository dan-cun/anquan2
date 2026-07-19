from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.database.repositories import PromptRepository
from app.schemas.prompts import (
    PromptTemplateRecord,
    PromptVersionRecord,
    PromptVersionStatus,
)
from prompts.catalog import NativePromptCatalog, PromptDefinition
from prompts.importer import PromptWorkbookImporter
from prompts.renderer import GoTemplateRenderer

_DEFAULT_VARIABLES: dict[str, Any] = {
    "Lang": "zh-CN",
    "Cwd": ".",
    "DockerImage": "SecMind controlled runtime",
    "ContainerPorts": [],
    "ExecutionContext": "",
    "SummarizedContentPrefix": "[上下文摘要]",
    "UseAgents": True,
    "FlowManagerEnabled": True,
    "GraphitiEnabled": False,
    "AskUserEnabled": True,
    "IsDefaultDockerImage": True,
    "UserFiles": [],
    "AdviceToolName": "DELEGATE:ADVISER",
    "CoderToolName": "DELEGATE:CODER",
    "EnricherToolName": "DELEGATE:ENRICHER",
    "MaintenanceToolName": "DELEGATE:INSTALLER",
    "MemoristToolName": "DELEGATE:MEMORIST",
    "PentesterToolName": "DELEGATE:PENTESTER",
    "SearchToolName": "DELEGATE:SEARCHER",
    "SummarizationToolName": "DELEGATE:SUMMARIZER",
    "TerminalToolName": "native:bandit_python_audit",
}


class NativePromptRegistry:
    def __init__(
        self,
        repository: PromptRepository,
        *,
        catalog: NativePromptCatalog | None = None,
        importer: PromptWorkbookImporter | None = None,
        renderer: GoTemplateRenderer | None = None,
    ) -> None:
        self.repository = repository
        self.catalog = catalog or NativePromptCatalog()
        self.importer = importer or PromptWorkbookImporter()
        self.renderer = renderer or GoTemplateRenderer()

    def seed_catalog(self) -> list[PromptTemplateRecord]:
        return self._store(self.catalog.load(), source="bundled:zh-CN", activate=True)

    def import_workbook(self, workbook_path: Path) -> list[PromptTemplateRecord]:
        path = workbook_path.expanduser().resolve()
        return self._store(
            self.importer.load(path),
            source=f"workbook:{path.name}",
            activate=True,
        )

    def _store(
        self,
        definitions: list[PromptDefinition],
        *,
        source: str,
        activate: bool,
    ) -> list[PromptTemplateRecord]:
        stored: list[PromptTemplateRecord] = []
        for definition in definitions:
            template = self.repository.upsert_template(
                PromptTemplateRecord(
                    prompt_key=definition.key,
                    name=definition.name,
                    category=definition.category,
                    message_role=definition.message_role,
                    agent_role=definition.agent_role,
                    source_path=definition.source_path,
                    variables=definition.variables,
                    metadata=definition.metadata,
                )
            )
            versions = self.repository.list_versions(definition.key)
            matching = next(
                (item for item in versions if item.checksum == definition.resolved_checksum),
                None,
            )
            if matching is None:
                matching = self.repository.create_version(
                    PromptVersionRecord(
                        prompt_key=definition.key,
                        version=len(versions) + 1,
                        content=definition.content,
                        variables=definition.variables,
                        checksum=definition.resolved_checksum,
                        status=(
                            PromptVersionStatus.ACTIVE if activate else PromptVersionStatus.DRAFT
                        ),
                        source=source,
                        activated_at=datetime.now(UTC) if activate else None,
                    )
                )
            elif activate and matching.status != PromptVersionStatus.ACTIVE:
                matching = self.repository.activate_version(definition.key, matching.version_id)
            if activate and template.active_version_id != matching.version_id:
                template = self.repository.get_template(definition.key) or template
            stored.append(template)
        return stored

    async def render(
        self,
        prompt_key: str,
        variables: dict[str, Any],
    ) -> tuple[str, str | None]:
        version = self.repository.get_active_version(prompt_key)
        if version is None:
            raise KeyError(f"No active Prompt version: {prompt_key}")
        context = dict(_DEFAULT_VARIABLES)
        context["CurrentTime"] = datetime.now(UTC).isoformat()
        context.update(variables)
        context.setdefault("Input", context.get("Objective", ""))
        context.setdefault("Question", context.get("Objective", ""))
        context.setdefault("Description", context.get("Objective", ""))
        context.setdefault("TaskQuestion", context.get("Objective", ""))
        context.setdefault("ExecutionContext", context.get("Objective", ""))
        return self.renderer.render(version.content, context), version.version_id
