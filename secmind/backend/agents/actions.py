from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.schemas.agents import AgentRole


class AgentActionType(StrEnum):
    COMPLETE = "complete"
    DELEGATE = "delegate"
    TOOL = "tool"


class AgentAction(BaseModel):
    """Internal structured command returned by an Agent model."""

    model_config = ConfigDict(extra="forbid")

    action: AgentActionType
    summary: str = ""
    role: AgentRole | None = None
    objective: str | None = None
    tool_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)
    context_refs: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_action_fields(self) -> AgentAction:
        if self.action == AgentActionType.DELEGATE:
            if self.role is None or not (self.objective or "").strip():
                raise ValueError("delegate action requires role and objective")
        if self.action == AgentActionType.TOOL and not self.tool_id:
            raise ValueError("tool action requires tool_id")
        if self.action == AgentActionType.COMPLETE and not self.summary.strip():
            raise ValueError("complete action requires summary")
        return self


class AgentActionError(ValueError):
    pass


def parse_agent_action(content: str) -> AgentAction:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline >= 0:
            cleaned = cleaned[first_newline + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    try:
        return AgentAction.model_validate(json.loads(cleaned))
    except (json.JSONDecodeError, ValidationError, TypeError) as error:
        raise AgentActionError("Agent response is not a valid action envelope") from error


ACTION_PROTOCOL = """
Return exactly one JSON object and no prose. Choose one action:
1. {"action":"delegate","role":"<agent_role>","objective":"<task>"}
2. {"action":"tool","tool_id":"<tool_id>","arguments":{}}
3. {"action":"complete","summary":"<public result>","data":{},
   "artifact_refs":[],"evidence_ids":[],"finding_ids":[]}
Use delegate when another specialist should perform the work. Continue after delegated or tool
results are supplied. Never include hidden reasoning in the JSON.
""".strip()

