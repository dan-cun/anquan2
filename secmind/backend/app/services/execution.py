from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.database.repositories import NativeRepositories
from app.schemas.runtime import AgentState, ExecutionIdentity, TaskRequest
from app.services.runtime import RuntimeRunService


@dataclass(slots=True)
class UnifiedExecutionService:
    """Creates one durable identity and submits work to the single runtime kernel."""

    runtime: RuntimeRunService
    repositories: NativeRepositories

    def prepare_identity(
        self,
        task: TaskRequest,
        *,
        flow_id: str | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
    ) -> ExecutionIdentity:
        identity = ExecutionIdentity(
            flow_id=flow_id or str(uuid4()),
            run_id=run_id or str(uuid4()),
            task_id=task_id or str(uuid4()),
        )
        self.repositories.flows.ensure_flow(
            identity.flow_id,
            title=task.objective[:200],
        )
        if self.repositories.tasks.get_task(identity.task_id) is None:
            self.repositories.tasks.create_task(
                flow_id=identity.flow_id,
                task_id=identity.task_id,
                title=task.objective[:200],
                objective=task.objective,
                status="created",
            )
        return identity

    def submit(
        self,
        task: TaskRequest,
        *,
        flow_id: str | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
    ) -> ExecutionIdentity:
        identity = self.prepare_identity(
            task,
            flow_id=flow_id,
            run_id=run_id,
            task_id=task_id,
        )
        self.repositories.tasks.update_task(identity.task_id, status="running")
        self.runtime.submit(
            task,
            flow_id=identity.flow_id,
            run_id=identity.run_id,
            task_id=identity.task_id,
        )
        return identity

    async def run_inline(
        self,
        task: TaskRequest,
        *,
        flow_id: str | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
    ) -> tuple[ExecutionIdentity, AgentState]:
        identity = self.prepare_identity(
            task,
            flow_id=flow_id,
            run_id=run_id,
            task_id=task_id,
        )
        self.repositories.tasks.update_task(identity.task_id, status="running")
        state = await self.runtime.run_inline(
            task,
            identity.run_id,
            flow_id=identity.flow_id,
            task_id=identity.task_id,
        )
        return identity, state
