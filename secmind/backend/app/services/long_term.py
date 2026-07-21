from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from app.database.repositories import LongTermRepository, ResultRepository
from app.schemas.long_term import (
    ContextSnapshot,
    NoteKind,
    NoteRecord,
    SkillDefinition,
    SkillLoad,
    StructuredContext,
    TodoItem,
    TodoPriority,
    TodoStatus,
)
from app.schemas.runtime import EventContext, RuntimeEventType
from app.schemas.tools import (
    ToolExecutionStatus,
    ToolOrigin,
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    UnifiedToolResult,
)
from app.services.runtime import RuntimeEventHub
from ledger.runtime_store import RuntimeLedgerStore
from tools.mcp.gateway import UnifiedToolGateway


class LongTermTaskService:
    def __init__(
        self,
        repository: LongTermRepository,
        results: ResultRepository,
        ledger: RuntimeLedgerStore,
        event_hub: RuntimeEventHub,
    ) -> None:
        self.repository = repository
        self.results = results
        self.ledger = ledger
        self.event_hub = event_hub

    async def register_skill(
        self,
        *,
        skill_id: str,
        name: str,
        content: str,
        description: str = "",
        version: str = "1.0",
        tags: list[str] | None = None,
        compatible_roles: list[str] | None = None,
        source: str = "operator",
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> SkillDefinition:
        previous = self.repository.get_skill(skill_id)
        now = datetime.now(UTC)
        skill = SkillDefinition(
            skill_id=skill_id,
            name=name,
            content=content,
            description=description,
            version=version,
            checksum=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            tags=tags or [],
            compatible_roles=compatible_roles or [],
            source=source,
            enabled=enabled,
            metadata=metadata or {},
            created_at=previous.created_at if previous else now,
            updated_at=now,
        )
        saved = self.repository.upsert_skill(skill)
        event_type = (
            RuntimeEventType.SKILL_UPDATED if previous else RuntimeEventType.SKILL_REGISTERED
        )
        await self._publish(
            "system-skills",
            event_type,
            {"skill": saved.model_dump(mode="json", exclude={"content"})},
            actor="operator",
        )
        return saved

    def list_skills(self, *, enabled: bool | None = None) -> list[SkillDefinition]:
        return self.repository.list_skills(enabled=enabled)

    async def load_skill(
        self,
        *,
        skill_id: str,
        run_id: str,
        flow_id: str,
        agent_instance_id: str | None = None,
        reason: str = "",
        actor: str = "operator",
    ) -> SkillLoad:
        skill = self.repository.get_skill(skill_id)
        if skill is None:
            raise KeyError(skill_id)
        if not skill.enabled:
            raise ValueError(f"Skill is disabled: {skill_id}")
        load = self.repository.add_skill_load(
            SkillLoad(
                skill_id=skill_id,
                run_id=run_id,
                flow_id=flow_id,
                agent_instance_id=agent_instance_id,
                reason=reason,
            )
        )
        await self._publish(
            run_id,
            RuntimeEventType.SKILL_LOADED,
            {
                "load": load.model_dump(mode="json"),
                "skill": skill.model_dump(mode="json", exclude={"content"}),
            },
            actor=actor,
            agent_instance_id=agent_instance_id,
            flow_id=flow_id,
        )
        return load

    async def unload_skill(self, load_id: str, *, actor: str = "operator") -> SkillLoad:
        load = self.repository.unload_skill(load_id)
        await self._publish(
            load.run_id,
            RuntimeEventType.SKILL_UNLOADED,
            {"load": load.model_dump(mode="json")},
            actor=actor,
            agent_instance_id=load.agent_instance_id,
            flow_id=load.flow_id,
        )
        return load

    async def create_todo(
        self,
        *,
        run_id: str,
        flow_id: str,
        title: str,
        description: str = "",
        priority: TodoPriority = TodoPriority.NORMAL,
        position: int = 0,
        task_id: str | None = None,
        agent_instance_id: str | None = None,
        depends_on: list[str] | None = None,
        actor: str = "operator",
    ) -> TodoItem:
        todo = self.repository.create_todo(
            TodoItem(
                run_id=run_id,
                flow_id=flow_id,
                title=title,
                description=description,
                priority=priority,
                position=position,
                task_id=task_id,
                agent_instance_id=agent_instance_id,
                depends_on=depends_on or [],
            )
        )
        await self._publish_item(RuntimeEventType.TODO_CREATED, todo, actor)
        return todo

    async def update_todo(
        self,
        todo_id: str,
        *,
        status: TodoStatus | None = None,
        title: str | None = None,
        description: str | None = None,
        evidence_ids: list[str] | None = None,
        actor: str = "operator",
    ) -> TodoItem:
        current = self.repository.get_todo(todo_id)
        if current is None:
            raise KeyError(todo_id)
        now = datetime.now(UTC)
        updates: dict[str, Any] = {"updated_at": now}
        if status is not None:
            updates["status"] = status
            updates["completed_at"] = now if status == TodoStatus.COMPLETED else None
        if title is not None:
            updates["title"] = title
        if description is not None:
            updates["description"] = description
        if evidence_ids is not None:
            updates["evidence_ids"] = evidence_ids
        todo = self.repository.update_todo(current.model_copy(update=updates))
        event_type = (
            RuntimeEventType.TODO_COMPLETED
            if todo.status == TodoStatus.COMPLETED
            else RuntimeEventType.TODO_UPDATED
        )
        await self._publish_item(event_type, todo, actor)
        return todo

    def list_todos(self, run_id: str) -> list[TodoItem]:
        return self.repository.list_todos(run_id)

    async def record_note(
        self,
        *,
        run_id: str,
        flow_id: str,
        kind: NoteKind,
        content: str,
        agent_instance_id: str | None = None,
        evidence_ids: list[str] | None = None,
        tags: list[str] | None = None,
        actor: str = "operator",
    ) -> NoteRecord:
        note = self.repository.record_note(
            NoteRecord(
                run_id=run_id,
                flow_id=flow_id,
                kind=kind,
                content=content,
                agent_instance_id=agent_instance_id,
                evidence_ids=evidence_ids or [],
                tags=tags or [],
            )
        )
        await self._publish(
            run_id,
            RuntimeEventType.NOTE_RECORDED,
            {"note": note.model_dump(mode="json")},
            actor=actor,
            agent_instance_id=agent_instance_id,
            flow_id=flow_id,
        )
        return note

    async def archive_note(self, note_id: str, *, actor: str = "operator") -> NoteRecord:
        note = self.repository.archive_note(note_id)
        await self._publish(
            note.run_id,
            RuntimeEventType.NOTE_ARCHIVED,
            {"note": note.model_dump(mode="json")},
            actor=actor,
            agent_instance_id=note.agent_instance_id,
            flow_id=note.flow_id,
        )
        return note

    def list_notes(self, run_id: str, *, active_only: bool = True) -> list[NoteRecord]:
        return self.repository.list_notes(run_id, active_only=active_only)

    async def compress_context(
        self,
        *,
        run_id: str,
        flow_id: str,
        agent_instance_id: str | None = None,
        actor: str = "summarizer",
    ) -> ContextSnapshot:
        previous = self.repository.list_snapshots(run_id)
        from_sequence = previous[-1].source_to_sequence if previous else 0
        raw_events = self.ledger.events(run_id, after_sequence=from_sequence, limit=100_000)
        events = [
            item
            for item in raw_events
            if item.event_type != RuntimeEventType.CONTEXT_COMPRESSED.value
        ]
        tools = [self._event_item(item) for item in events if item.event_type.startswith("tool.")]
        errors = [
            self._event_item(item)
            for item in events
            if item.event_type.endswith((".failed", ".error", ".timed_out", ".denied"))
        ]
        endpoints = self._endpoints(events)
        findings = [
            {
                "finding_id": row.finding_id,
                "title": row.title,
                "severity": row.severity,
                "evidence_ids": row.evidence_ids_json,
            }
            for row in self.results.list_findings(run_id)
        ]
        todos = [item.model_dump(mode="json") for item in self.list_todos(run_id)]
        notes = [item.model_dump(mode="json") for item in self.list_notes(run_id)]
        loads = self.repository.list_skill_loads(
            run_id, agent_instance_id=agent_instance_id, active_only=True
        )
        skills = [
            {
                "skill_id": item.skill_id,
                "version": item.version,
                "checksum": item.checksum,
            }
            for load in loads
            if (item := self.repository.get_skill(load.skill_id)) is not None
        ]
        structured = StructuredContext(
            tools=tools,
            endpoints=endpoints,
            findings=findings,
            errors=errors,
            todos=todos,
            notes=notes,
            skills=skills,
        )
        raw = json.dumps([item.model_dump(mode="json") for item in events], ensure_ascii=False)
        compact = structured.model_dump_json()
        summary = (
            f"结构化上下文快照：工具事件 {len(tools)} 条，端点 {len(endpoints)} 个，"
            f"发现 {len(findings)} 条，错误 {len(errors)} 条，待办 {len(todos)} 条，"
            f"笔记 {len(notes)} 条，已加载 Skill {len(skills)} 个。"
        )
        snapshot = self.repository.save_snapshot(
            ContextSnapshot(
                run_id=run_id,
                flow_id=flow_id,
                agent_instance_id=agent_instance_id,
                source_from_sequence=from_sequence,
                source_to_sequence=raw_events[-1].sequence if raw_events else from_sequence,
                estimated_tokens_before=self._estimate_tokens(raw),
                estimated_tokens_after=self._estimate_tokens(compact + summary),
                narrative_summary=summary,
                structured=structured,
            )
        )
        await self._publish(
            run_id,
            RuntimeEventType.CONTEXT_COMPRESSED,
            {"snapshot": snapshot.model_dump(mode="json")},
            actor=actor,
            agent_instance_id=agent_instance_id,
            flow_id=flow_id,
        )
        return snapshot

    def agent_context(self, run_id: str, agent_instance_id: str | None = None) -> dict[str, Any]:
        loads = self.repository.list_skill_loads(run_id, agent_instance_id=agent_instance_id)
        loaded_by_id = {
            item.skill_id: self.repository.get_skill(item.skill_id)
            for item in loads
        }
        snapshots = self.repository.list_snapshots(run_id)
        return {
            "available_skills": [
                item.model_dump(mode="json", exclude={"content"})
                for item in self.repository.list_skills(enabled=True)
            ],
            "loaded_skills": [
                item.model_dump(mode="json") for item in loaded_by_id.values() if item
            ],
            "todos": [item.model_dump(mode="json") for item in self.list_todos(run_id)],
            "notes": [item.model_dump(mode="json") for item in self.list_notes(run_id)],
            "context_snapshot": snapshots[-1].model_dump(mode="json") if snapshots else None,
        }

    async def _publish_item(self, event_type: RuntimeEventType, todo: TodoItem, actor: str) -> None:
        await self._publish(
            todo.run_id,
            event_type,
            {"todo": todo.model_dump(mode="json")},
            actor=actor,
            agent_instance_id=todo.agent_instance_id,
            flow_id=todo.flow_id,
        )

    async def _publish(
        self,
        run_id: str,
        event_type: RuntimeEventType,
        payload: dict[str, Any],
        *,
        actor: str,
        flow_id: str | None = None,
        agent_instance_id: str | None = None,
    ) -> None:
        event = self.ledger.append(
            run_id,
            event_type.value,
            payload,
            actor=actor,
            context=EventContext(flow_id=flow_id, agent_instance_id=agent_instance_id),
        )
        await self.event_hub.publish(event.model_dump(mode="json"))

    @staticmethod
    def _event_item(event: Any) -> dict[str, Any]:
        payload = event.payload
        invocation = (
            payload.get("invocation")
            if isinstance(payload.get("invocation"), dict)
            else {}
        )
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        return {
            "sequence": event.sequence,
            "event_type": event.event_type,
            "actor": event.actor,
            "tool_id": invocation.get("tool_id") or payload.get("tool_id"),
            "invocation_id": invocation.get("invocation_id") or payload.get("invocation_id"),
            "status": result.get("status") or payload.get("status"),
            "summary": result.get("text") or payload.get("summary"),
            "error_code": result.get("error_code") or payload.get("error_code"),
            "error_message": result.get("error_message") or payload.get("error_message"),
            "evidence_ids": result.get("evidence_ids") or payload.get("evidence_ids") or [],
            "artifact_refs": result.get("artifact_refs") or payload.get("artifact_refs") or [],
        }

    @staticmethod
    def _endpoints(events: list[Any]) -> list[dict[str, Any]]:
        found: dict[tuple[str, str], dict[str, Any]] = {}
        keys = {"endpoint", "url", "target", "host", "hostname"}

        def visit(value: Any, sequence: int) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key.lower() in keys and isinstance(item, (str, int, float)):
                        found[(key.lower(), str(item))] = {
                            "kind": key.lower(),
                            "value": str(item),
                            "last_sequence": sequence,
                        }
                    else:
                        visit(item, sequence)
            elif isinstance(value, list):
                for item in value:
                    visit(item, sequence)

        for event in events:
            visit(event.payload, event.sequence)
        return list(found.values())

    @staticmethod
    def _estimate_tokens(value: str) -> int:
        return 0 if not value else max(1, (len(value) + 3) // 4)


def register_long_term_tools(gateway: UnifiedToolGateway, service: LongTermTaskService) -> None:
    definitions = (
        ("native:skill.list", "列出可用和已加载的 Skill", {"type": "object"}),
        (
            "native:skill.load",
            "为当前 Agent 按需加载 Skill",
            {
                "type": "object",
                "required": ["skill_id"],
                "properties": {
                    "skill_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        ),
        ("native:todo.list", "列出当前运行的 Todo", {"type": "object"}),
        (
            "native:todo.create",
            "创建长期任务 Todo",
            {
                "type": "object",
                "required": ["title"],
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "priority": {"type": "integer"},
                },
            },
        ),
        (
            "native:todo.update",
            "更新 Todo 状态和证据",
            {
                "type": "object",
                "required": ["todo_id"],
                "properties": {
                    "todo_id": {"type": "string"},
                    "status": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        ),
        ("native:notes.list", "列出当前运行的 Notes", {"type": "object"}),
        (
            "native:notes.record",
            "记录事实、假设、约束、观察或错误 Note",
            {
                "type": "object",
                "required": ["kind", "content"],
                "properties": {
                    "kind": {"type": "string"},
                    "content": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        ),
        ("native:context.compress", "生成结构化上下文快照", {"type": "object"}),
    )

    async def invoke(invocation: UnifiedToolInvocation) -> UnifiedToolResult:
        try:
            args = invocation.arguments
            if invocation.tool_id == "native:skill.list":
                data = service.agent_context(invocation.run_id, invocation.agent_instance_id)
            elif invocation.tool_id == "native:skill.load":
                value = await service.load_skill(
                    skill_id=str(args["skill_id"]),
                    run_id=invocation.run_id,
                    flow_id=invocation.flow_id,
                    agent_instance_id=invocation.agent_instance_id,
                    reason=str(args.get("reason") or "Agent requested Skill"),
                    actor="agent",
                )
                data = value.model_dump(mode="json")
            elif invocation.tool_id == "native:todo.list":
                data = {
                    "todos": [
                        item.model_dump(mode="json")
                        for item in service.list_todos(invocation.run_id)
                    ]
                }
            elif invocation.tool_id == "native:todo.create":
                value = await service.create_todo(
                    run_id=invocation.run_id,
                    flow_id=invocation.flow_id,
                    title=str(args["title"]),
                    description=str(args.get("description") or ""),
                    priority=TodoPriority(int(args.get("priority", TodoPriority.NORMAL))),
                    task_id=invocation.task_id,
                    agent_instance_id=invocation.agent_instance_id,
                    actor="agent",
                )
                data = value.model_dump(mode="json")
            elif invocation.tool_id == "native:todo.update":
                status = args.get("status")
                value = await service.update_todo(
                    str(args["todo_id"]),
                    status=TodoStatus(str(status)) if status else None,
                    evidence_ids=list(args["evidence_ids"]) if "evidence_ids" in args else None,
                    actor="agent",
                )
                data = value.model_dump(mode="json")
            elif invocation.tool_id == "native:notes.list":
                data = {
                    "notes": [
                        item.model_dump(mode="json")
                        for item in service.list_notes(invocation.run_id)
                    ]
                }
            elif invocation.tool_id == "native:notes.record":
                value = await service.record_note(
                    run_id=invocation.run_id,
                    flow_id=invocation.flow_id,
                    kind=NoteKind(str(args["kind"])),
                    content=str(args["content"]),
                    agent_instance_id=invocation.agent_instance_id,
                    evidence_ids=list(args.get("evidence_ids") or []),
                    actor="agent",
                )
                data = value.model_dump(mode="json")
            else:
                value = await service.compress_context(
                    run_id=invocation.run_id,
                    flow_id=invocation.flow_id,
                    agent_instance_id=invocation.agent_instance_id,
                    actor="agent",
                )
                data = value.model_dump(mode="json")
            return UnifiedToolResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.tool_id,
                status=ToolExecutionStatus.COMPLETED,
                text="长期任务状态操作已完成。",
                data=data,
            )
        except Exception as error:
            return UnifiedToolResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.tool_id,
                status=ToolExecutionStatus.FAILED,
                text="长期任务状态操作失败。",
                error_code=type(error).__name__,
                error_message=str(error),
            )

    for tool_id, description, input_schema in definitions:
        gateway.register_native(
            UnifiedToolDefinition(
                tool_id=tool_id,
                name=tool_id.removeprefix("native:"),
                description=description,
                origin=ToolOrigin.NATIVE,
                input_schema=input_schema,
                output_schema={"type": "object"},
                annotations={"category": "long_term_state", "risk_level": 0},
            ),
            invoke,
        )
