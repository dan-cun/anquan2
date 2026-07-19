from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from app.database import create_native_repositories
from app.database.models import Base
from prompts import (
    GoTemplateRenderer,
    NativePromptCatalog,
    NativePromptRegistry,
    PromptWorkbookError,
    PromptWorkbookImporter,
)


def test_completed_catalog_contains_and_renders_all_native_prompts() -> None:
    definitions = NativePromptCatalog().load()

    assert len(definitions) == 41
    assert len({item.key for item in definitions}) == 41
    assert all(any("\u3400" <= char <= "\u9fff" for char in item.content) for item in definitions)

    renderer = GoTemplateRenderer()
    for definition in definitions:
        rendered = renderer.render(definition.content, {})
        assert rendered
        assert "{{" not in rendered
        assert "}}" not in rendered


def test_go_template_renderer_supports_nested_if_else_and_range() -> None:
    renderer = GoTemplateRenderer()
    template = (
        "{{if .Enabled}}{{range $index, $item := .Items}}"
        "{{$index}}={{$item.Name}};{{end}}{{else}}off{{end}}"
    )

    variables = {"Enabled": True, "Items": [{"Name": "a"}, {"Name": "b"}]}
    assert renderer.render(template, variables) == "0=a;1=b;"
    assert renderer.render(template, {"Enabled": False, "Items": []}) == "off"


def _write_workbook(path: Path, *, broken: bool = False) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Prompt修改表"
    sheet.append(
        [
            "Prompt键",
            "分类",
            "消息角色",
            "Agent/模块",
            "源文件",
            "模板变量",
            "原始Prompt（参考）",
            "修改后Prompt（编辑）",
            "修改状态",
            "修改说明",
        ]
    )
    for index in range(41):
        key = "assistant" if index == 0 else f"template_{index}"
        original = "{{.Input}}"
        modified = "已修改 {{.Other}}" if broken and index == 0 else "已修改 {{.Input}}"
        sheet.append(
            [
                key,
                "native",
                "system" if index == 0 else "template",
                key,
                f"{key}.tmpl",
                ".Input",
                original,
                modified,
                "待复核",
                "",
            ]
        )
    workbook.save(path)


def test_workbook_importer_requires_variable_stability(tmp_path: Path) -> None:
    valid_path = tmp_path / "valid.xlsx"
    _write_workbook(valid_path)
    definitions = PromptWorkbookImporter().load(valid_path)
    assert len(definitions) == 41
    assert definitions[0].key == "assistant"

    broken_path = tmp_path / "broken.xlsx"
    _write_workbook(broken_path, broken=True)
    with pytest.raises(PromptWorkbookError, match="removed variables"):
        PromptWorkbookImporter().load(broken_path)


@pytest.mark.asyncio
async def test_registry_seeds_active_versions_and_returns_traceable_version(tmp_path: Path) -> None:
    repositories = create_native_repositories(f"sqlite:///{(tmp_path / 'runtime.db').as_posix()}")
    Base.metadata.create_all(repositories.engine)
    registry = NativePromptRegistry(repositories.prompts)

    seeded = registry.seed_catalog()
    prompt, version_id = await registry.render("assistant", {"Objective": "检查代码"})

    assert len(seeded) == 41
    assert version_id is not None
    assert "{{" not in prompt
    assert any("\u3400" <= char <= "\u9fff" for char in prompt)
    assert repositories.prompts.get_active_version("assistant").version_id == version_id
