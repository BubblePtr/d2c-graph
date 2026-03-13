from __future__ import annotations

from pathlib import Path

from d2c_graph.config import AppConfig


def test_load_config(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
models:
  vision:
    provider: gemini
    model: gemini-test
    api_key_env: GEMINI_API_KEY
  text:
    provider: openai_compatible
    model: gpt-test
    api_key_env: OPENAI_API_KEY
    base_url: https://example.com/v1
d2c_mcp:
  command: fake
  tool_name: generate
build:
  react:
    command: echo react
  kmp:
    command: echo kmp
""",
        encoding="utf-8",
    )
    config = AppConfig.load(config_path)
    assert config.models.text.api_key() == "test-openai"
    assert config.models.vision.api_key() == "test-gemini"
    assert config.d2c_mcp.tool_name == "generate"
