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


def test_qwen_provider_without_key_is_disabled(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "data",
        ledger_dir=tmp_path / "ledger",
        llm_provider="qwen",
        llm_api_key="",
    )

    provider = build_llm_provider(settings)

    assert provider.metadata()["configured"] is False
