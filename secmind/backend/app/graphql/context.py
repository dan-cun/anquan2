from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from strawberry.dataloader import DataLoader
from strawberry.fastapi import BaseContext

from app.graphql.ports import GraphQLBackend
from app.graphql.types import Subtask, Task


@dataclass(frozen=True, slots=True)
class GraphQLLoaders:
    tasks_by_flow: DataLoader[str, list[Task]]
    subtasks_by_task: DataLoader[str, list[Subtask]]

    @classmethod
    def create(cls, backend: GraphQLBackend) -> GraphQLLoaders:
        async def load_tasks(flow_ids: list[str]) -> list[list[Task]]:
            batch = getattr(backend.flows, "list_tasks_batch", None)
            if callable(batch):
                grouped = await batch(flow_ids)
                return [list(grouped.get(flow_id, ())) for flow_id in flow_ids]
            return [list(await backend.flows.list_tasks(flow_id)) for flow_id in flow_ids]

        async def load_subtasks(task_ids: list[str]) -> list[list[Subtask]]:
            batch = getattr(backend.flows, "list_subtasks_batch", None)
            if callable(batch):
                grouped = await batch(task_ids)
                return [list(grouped.get(task_id, ())) for task_id in task_ids]
            return [list(await backend.flows.list_subtasks(task_id)) for task_id in task_ids]

        return cls(
            tasks_by_flow=DataLoader(load_fn=load_tasks),
            subtasks_by_task=DataLoader(load_fn=load_subtasks),
        )


@dataclass
class GraphQLContext(BaseContext):
    backend: GraphQLBackend
    loaders: GraphQLLoaders
    connection: Any | None = None

    @classmethod
    def create(
        cls,
        backend: GraphQLBackend,
        *,
        connection: Any | None = None,
    ) -> GraphQLContext:
        return cls(
            backend=backend,
            loaders=GraphQLLoaders.create(backend),
            connection=connection,
        )


def get_backend(info: Any) -> GraphQLBackend:
    context = info.context
    if not isinstance(context, GraphQLContext):
        raise RuntimeError("GraphQLContext is required")
    return context.backend
