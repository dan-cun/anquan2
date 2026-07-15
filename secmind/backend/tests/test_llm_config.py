import pytest

from app.core.config import Settings
from llm.factory import build_llm_provider


def test_qwen_provider_configured(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        ledger_dir=tmp_path / "ledger",
        llm_provider="qwen",
        llm_api_key="test-key",
        llm_base_url="https://example.com/compatible-mode/v1/",
        llm_model="qwen-plus",
    )

    provider = build_llm_provider(settings)
    metadata = provider.metadata()

    assert metadata["name"] == "qwen"
    assert metadata["configured"] is True
    assert metadata["base_url"] == "https://example.com/compatible-mode/v1"
    assert metadata["model"] == "qwen-plus"


@pytest.mark.parametrize(
    ("configured_name", "metadata_name"),
    [
        ("deepseek", "deepseek"),
        ("openai", "openai"),
        ("moonshot", "moonshot"),
        ("zhipu", "zhipu"),
        ("siliconflow", "siliconflow"),
        ("openai-compatible", "openai-compatible"),
    ],
)
def test_named_openai_compatible_provider_preserves_vendor_name(
    tmp_path, configured_name, metadata_name
):
    settings = Settings(
        data_dir=tmp_path,
        ledger_dir=tmp_path / "ledger",
        llm_provider=configured_name,
        llm_api_key="secret",
        llm_base_url="https://example.com/v1",
        llm_model="test-model",
    )

    metadata = build_llm_provider(settings).metadata()

    assert metadata["configured"] is True
    assert metadata["name"] == metadata_name


def test_qwen_provider_without_key_is_disabled(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        ledger_dir=tmp_path / "ledger",
        llm_provider="qwen",
        llm_api_key="",
    )

    provider = build_llm_provider(settings)

    assert provider.metadata()["configured"] is False


@pytest.mark.parametrize(
    "base_url",
    ["http://example.com/v1", "https://127.0.0.1/v1", "https://10.0.0.1/v1"],
)
def test_qwen_provider_rejects_unsafe_base_url(tmp_path, base_url):
    settings = Settings(
        data_dir=tmp_path / "data",
        ledger_dir=tmp_path / "ledger",
        llm_provider="qwen",
        llm_api_key="test-key",
        llm_base_url=base_url,
    )

    with pytest.raises(ValueError, match="LLM base_url"):
        build_llm_provider(settings)
