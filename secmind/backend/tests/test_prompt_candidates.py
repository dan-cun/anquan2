from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path

import pytest

from agents.native import StaticPromptResolver

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "prompts" / "candidates" / "zh-CN" / "manifest.json"


def _tokens(text: str) -> list[str]:
    return sorted(re.findall(r"\{\{[\s\S]*?\}\}", text))


def _balanced_go_blocks(text: str) -> bool:
    depth = 0
    for token in re.findall(r"\{\{([\s\S]*?)\}\}", text):
        directive = token.strip().split(maxsplit=1)[0] if token.strip() else ""
        if directive in {"if", "range", "with", "define", "block"}:
            depth += 1
        elif directive == "end":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def test_candidate_manifest_is_explicitly_non_active() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["locale"] == "zh-CN"
    assert manifest["activation"] == "candidate-only"
    assert {item["key"] for item in manifest["prompts"]} == {
        "primary_agent",
        "generator",
        "reporter",
        "language_chooser",
        "graphiti.agent_response",
    }


@pytest.mark.parametrize("entry_index", range(5))
def test_candidate_is_utf8_structurally_stable_and_readable(entry_index: int) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entry = manifest["prompts"][entry_index]
    relative = Path(entry["path"]).relative_to("secmind/backend/")
    candidate_path = ROOT / relative
    raw = candidate_path.read_bytes()
    text = raw.decode("utf-8")

    assert not raw.startswith(b"\xef\xbb\xbf")
    assert sha256(raw).hexdigest() == entry["candidateSha256"]
    assert "\ufffd" not in text
    assert any("\u3400" <= char <= "\u9fff" for char in text)
    assert _tokens(text) == entry["candidateGoTemplateTokens"]
    assert _balanced_go_blocks(text)
    assert entry["sourceGoTemplateTokens"] == entry["candidateGoTemplateTokens"]


@pytest.mark.asyncio
async def test_selected_agent_candidates_can_be_loaded_without_activation() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    prompts = {}
    for entry in manifest["prompts"]:
        if entry["key"] in {"primary_agent", "generator", "reporter"}:
            relative = Path(entry["path"]).relative_to("secmind/backend/")
            prompts[entry["key"]] = (ROOT / relative).read_text(encoding="utf-8")

    resolver = StaticPromptResolver(prompts)
    for key, expected in prompts.items():
        rendered, version_id = await resolver.render(key, {})
        assert rendered == expected
        assert version_id is None
