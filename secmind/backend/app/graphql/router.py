from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from starlette.requests import HTTPConnection
from strawberry.fastapi import GraphQLRouter

from app.graphql.context import GraphQLContext
from app.graphql.ports import GraphQLBackend
from app.graphql.schema import graphql_schema

BackendProvider = Callable[
    [HTTPConnection],
    GraphQLBackend | Awaitable[GraphQLBackend],
]


def create_graphql_router(
    backend_provider: BackendProvider,
    *,
    graphql_ide: str | None = "graphiql",
) -> GraphQLRouter:
    """Build an unwired router; integration owns mounting and service composition."""

    async def context_getter(connection: HTTPConnection) -> GraphQLContext:
        backend = backend_provider(connection)
        if inspect.isawaitable(backend):
            backend = await backend
        return GraphQLContext.create(backend, connection=connection)

    return GraphQLRouter(
        graphql_schema,
        context_getter=context_getter,
        graphql_ide=graphql_ide,
    )
