from __future__ import annotations

import strawberry
from strawberry.schema.config import StrawberryConfig

from app.graphql.mutation import Mutation
from app.graphql.query import Query
from app.graphql.subscription import Subscription

graphql_schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    subscription=Subscription,
    config=StrawberryConfig(auto_camel_case=True),
)


def schema_sdl() -> str:
    return graphql_schema.as_str()
