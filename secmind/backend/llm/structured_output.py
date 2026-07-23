from __future__ import annotations

import json
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from llm.base import EmptyContentReason, LLMResponse

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class StructuredOutputDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Literal["empty_content", "invalid_json", "invalid_root", "schema_validation"]
    content_length: int = Field(ge=0)
    source_format: Literal["empty", "json", "fenced_json", "unknown"]
    finish_reason: str | None = None
    empty_content_reason: EmptyContentReason | None = None
    validation_errors: list[dict[str, Any]] = Field(default_factory=list)
    retryable: bool = False
    suggested_overrides: dict[str, Any] = Field(default_factory=dict)


class StructuredOutputError(ValueError, Generic[StructuredModel]):
    def __init__(self, message: str, diagnostics: StructuredOutputDiagnostics) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


def parse_structured_output(
    response: LLMResponse | str,
    schema: type[StructuredModel],
) -> StructuredModel:
    content, finish_reason, empty_reason = _response_fields(response)
    cleaned, source_format = _clean_json_document(content)
    if not cleaned:
        retryable = empty_reason == EmptyContentReason.LENGTH_REASONING_ONLY
        raise StructuredOutputError(
            "Structured model response is empty",
            StructuredOutputDiagnostics(
                code="empty_content",
                content_length=len(content),
                source_format="empty",
                finish_reason=finish_reason,
                empty_content_reason=empty_reason,
                retryable=retryable,
                suggested_overrides={"thinking_enabled": False} if retryable else {},
            ),
        )
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise StructuredOutputError(
            "Structured model response is not one complete JSON document",
            StructuredOutputDiagnostics(
                code="invalid_json",
                content_length=len(content),
                source_format=source_format,
                finish_reason=finish_reason,
                empty_content_reason=empty_reason,
                validation_errors=[
                    {
                        "location": [error.lineno, error.colno],
                        "type": "json_decode",
                        "message": error.msg,
                    }
                ],
            ),
        ) from error
    if not isinstance(payload, dict):
        raise StructuredOutputError(
            "Structured model response must be one JSON object",
            StructuredOutputDiagnostics(
                code="invalid_root",
                content_length=len(content),
                source_format=source_format,
                finish_reason=finish_reason,
                empty_content_reason=empty_reason,
                validation_errors=[
                    {
                        "location": [],
                        "type": "object_type",
                        "message": "JSON root must be an object",
                    }
                ],
            ),
        )
    try:
        return schema.model_validate(payload)
    except ValidationError as error:
        validation_errors = [
            {
                "location": [str(part) for part in item["loc"]],
                "type": item["type"],
                "message": item["msg"],
            }
            for item in error.errors(include_input=False, include_url=False)
        ]
        raise StructuredOutputError(
            "Structured model response does not match the required schema",
            StructuredOutputDiagnostics(
                code="schema_validation",
                content_length=len(content),
                source_format=source_format,
                finish_reason=finish_reason,
                empty_content_reason=empty_reason,
                validation_errors=validation_errors,
            ),
        ) from error


def _response_fields(
    response: LLMResponse | str,
) -> tuple[str, str | None, EmptyContentReason | None]:
    if isinstance(response, LLMResponse):
        return response.content, response.finish_reason, response.empty_content_reason
    return str(response), None, None


def _clean_json_document(
    content: str,
) -> tuple[str, Literal["empty", "json", "fenced_json", "unknown"]]:
    cleaned = content.lstrip("\ufeff").strip()
    if not cleaned:
        return "", "empty"
    if not cleaned.startswith("```"):
        return cleaned, "json" if cleaned[:1] in {"{", "["} else "unknown"
    first_newline = cleaned.find("\n")
    if first_newline < 0 or not cleaned.endswith("```"):
        return cleaned, "unknown"
    language = cleaned[3:first_newline].strip().lower()
    if language not in {"", "json"}:
        return cleaned, "unknown"
    body = cleaned[first_newline + 1 : -3].strip()
    return body, "fenced_json"
