from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

_TOKEN_RE = re.compile(r"({{[\s\S]*?}})")


@dataclass(frozen=True, slots=True)
class _Text:
    value: str


@dataclass(frozen=True, slots=True)
class _Expression:
    value: str


@dataclass(frozen=True, slots=True)
class _Block:
    kind: str
    expression: str
    body: list[object]
    otherwise: list[object]


class GoTemplateRenderer:
    """Render the subset of Go Template syntax used by the 41 native Prompts."""

    def render(self, template: str, variables: dict[str, Any]) -> str:
        tokens = _TOKEN_RE.split(template)
        nodes, index, stop = self._parse(tokens, 0)
        if stop is not None or index != len(tokens):
            raise ValueError("Unexpected Go Template block terminator")
        return self._render(nodes, variables, variables, {}).strip()

    def _parse(
        self,
        tokens: list[str],
        index: int,
        stops: set[str] | None = None,
    ) -> tuple[list[object], int, str | None]:
        nodes: list[object] = []
        stops = stops or set()
        while index < len(tokens):
            token = tokens[index]
            index += 1
            if not token.startswith("{{"):
                if token:
                    nodes.append(_Text(token))
                continue
            body = token[2:-2].strip().strip("-").strip()
            head, _, expression = body.partition(" ")
            if head in stops:
                return nodes, index, head
            if head in {"if", "range", "with"}:
                branch, index, terminator = self._parse(tokens, index, {"else", "end"})
                otherwise: list[object] = []
                if terminator == "else":
                    otherwise, index, terminator = self._parse(tokens, index, {"end"})
                if terminator != "end":
                    raise ValueError(f"Unclosed Go Template block: {head}")
                nodes.append(_Block(head, expression.strip(), branch, otherwise))
            elif head in {"else", "end"}:
                raise ValueError(f"Unexpected Go Template directive: {head}")
            else:
                nodes.append(_Expression(body))
        return nodes, index, None

    def _render(
        self,
        nodes: list[object],
        root: Any,
        current: Any,
        locals_: dict[str, Any],
    ) -> str:
        output: list[str] = []
        for node in nodes:
            if isinstance(node, _Text):
                output.append(node.value)
            elif isinstance(node, _Expression):
                output.append(self._stringify(self._resolve(node.value, root, current, locals_)))
            elif isinstance(node, _Block):
                value = self._resolve(node.expression, root, current, locals_)
                if node.kind == "range":
                    output.append(self._render_range(node, value, root, locals_))
                elif value:
                    branch_current = value if node.kind == "with" else current
                    output.append(self._render(node.body, root, branch_current, locals_))
                else:
                    output.append(self._render(node.otherwise, root, current, locals_))
        return "".join(output)

    def _render_range(
        self,
        node: _Block,
        value: Any,
        root: Any,
        locals_: dict[str, Any],
    ) -> str:
        expression = node.expression
        assignment = re.match(r"(\$\w+)\s*,\s*(\$\w+)\s*:=\s*(.+)", expression)
        if assignment:
            value = self._resolve(assignment.group(3), root, root, locals_)
            index_name, item_name = assignment.group(1), assignment.group(2)
        else:
            index_name = item_name = None
        if not value:
            return self._render(node.otherwise, root, root, locals_)
        items = list(value.values()) if isinstance(value, dict) else list(value)
        rendered: list[str] = []
        for index, item in enumerate(items):
            child_locals = dict(locals_)
            if index_name is not None and item_name is not None:
                child_locals[index_name] = index
                child_locals[item_name] = item
            rendered.append(self._render(node.body, root, item, child_locals))
        return "".join(rendered)

    def _resolve(
        self,
        expression: str,
        root: Any,
        current: Any,
        locals_: dict[str, Any],
    ) -> Any:
        expression = expression.split("|", 1)[0].strip()
        if expression in {"", "."}:
            return current
        if expression in {"true", "false"}:
            return expression == "true"
        if expression.startswith("$"):
            name, *parts = expression.split(".")
            value = locals_.get(name)
            return self._walk(value, parts)
        if expression.startswith("."):
            parts = expression[1:].split(".")
            value = self._walk(current, parts)
            if value is None and current is not root:
                value = self._walk(root, parts)
            return value
        return expression.strip('"')

    @staticmethod
    def _walk(value: Any, parts: list[str]) -> Any:
        for part in parts:
            if value is None:
                return None
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = getattr(value, part, None)
        return value

    @staticmethod
    def _stringify(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(value, ensure_ascii=False, default=str)
        return str(value)
