from __future__ import annotations

from pathlib import Path

from graphql import (
    GraphQLEnumType,
    GraphQLInputObjectType,
    GraphQLInterfaceType,
    GraphQLObjectType,
    build_schema,
)

from app.graphql.schema import schema_sdl


def _field_signature(field) -> tuple[str, dict[str, tuple[str, object]]]:
    return str(field.type), {
        name: (str(argument.type), argument.default_value) for name, argument in field.args.items()
    }


def _input_field_signature(field) -> tuple[str, object]:
    return str(field.type), field.default_value


def test_generated_schema_matches_frozen_contract() -> None:
    frozen_path = Path(__file__).parents[1] / "app" / "graphql" / "schema.graphql"
    frozen = build_schema(frozen_path.read_text(encoding="utf-8"))
    generated = build_schema(schema_sdl())

    for root_name in ("Query", "Mutation", "Subscription"):
        expected = frozen.get_type(root_name)
        actual = generated.get_type(root_name)
        assert isinstance(expected, GraphQLObjectType)
        assert isinstance(actual, GraphQLObjectType)
        assert set(actual.fields) == set(expected.fields)

    for name, expected in frozen.type_map.items():
        if name.startswith("__") or name in {"String", "Boolean", "Int", "Float", "ID"}:
            continue
        actual = generated.get_type(name)
        assert actual is not None, f"generated schema is missing {name}"
        assert type(actual) is type(expected), f"GraphQL kind mismatch for {name}"
        if isinstance(expected, GraphQLEnumType):
            assert set(actual.values) == set(expected.values)
        elif isinstance(
            expected,
            (GraphQLObjectType, GraphQLInputObjectType, GraphQLInterfaceType),
        ):
            assert set(actual.fields) == set(expected.fields), f"field mismatch for {name}"
            for field_name, expected_field in expected.fields.items():
                actual_field = actual.fields[field_name]
                location = f"{name}.{field_name}"
                if isinstance(expected, GraphQLInputObjectType):
                    assert _input_field_signature(actual_field) == _input_field_signature(
                        expected_field
                    ), f"input field signature mismatch for {location}"
                else:
                    assert _field_signature(actual_field) == _field_signature(expected_field), (
                        f"field signature mismatch for {location}"
                    )
