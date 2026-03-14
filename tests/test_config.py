from __future__ import annotations

from pathlib import Path

import pytest

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
figma_mcp:
  command: fake
scaffold:
  react:
    command: npm create vite@latest {target} -- --template react-ts
  kmp:
    git_url: https://example.com/kmp-shell.git
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


def test_load_config_supports_figma_http_and_d2c_sse(tmp_path: Path):
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
figma_mcp:
  type: http
  url: https://mcp.figma.com/mcp
d2c_mcp:
  transport: sse
  url: https://example.com/d2c/sse
  tool_name: generate
scaffold:
  react:
    command: npm create vite@latest {target} -- --template react-ts
  kmp:
    git_url: https://example.com/kmp-shell.git
build:
  react:
    command: echo react
  kmp:
    command: echo kmp
""",
        encoding="utf-8",
    )

    config = AppConfig.load(config_path)

    assert config.figma_mcp.transport == "http"
    assert config.d2c_mcp.transport == "sse"
    assert config.d2c_mcp.url == "https://example.com/d2c/sse"


def test_load_config_rejects_d2c_http_transport(tmp_path: Path):
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
figma_mcp:
  type: http
  url: https://mcp.figma.com/mcp
d2c_mcp:
  type: http
  url: https://example.com/d2c/mcp
  tool_name: generate
scaffold:
  react:
    command: npm create vite@latest {target} -- --template react-ts
  kmp:
    git_url: https://example.com/kmp-shell.git
build:
  react:
    command: echo react
  kmp:
    command: echo kmp
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="d2c_mcp transport must be stdio or sse"):
        AppConfig.load(config_path)


def test_load_config_rejects_react_scaffold_without_target(tmp_path: Path):
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
figma_mcp:
  command: fake
d2c_mcp:
  command: fake
  tool_name: generate
scaffold:
  react:
    command: npm create vite@latest react-app -- --template react-ts
  kmp:
    git_url: https://example.com/kmp-shell.git
build:
  react:
    command: echo react
  kmp:
    command: echo kmp
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"scaffold.react.command must include \{target\}"):
        AppConfig.load(config_path)


def test_load_config_allows_optional_kmp_branch(tmp_path: Path):
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
figma_mcp:
  command: fake
d2c_mcp:
  command: fake
  tool_name: generate
scaffold:
  react:
    command: npm create vite@latest {target} -- --template react-ts
  kmp:
    git_url: https://example.com/kmp-shell.git
build:
  react:
    command: echo react
  kmp:
    command: echo kmp
""",
        encoding="utf-8",
    )

    config = AppConfig.load(config_path)

    assert config.scaffold.kmp.branch is None
