from __future__ import annotations

import sys
from pathlib import Path

import pytest

from d2c_graph.clients.d2c_mcp import D2CMcpClient
from d2c_graph.config import D2CMcpConfig


def test_d2c_mcp_client_reads_structured_content():
    fixture = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"
    client = D2CMcpClient(
        D2CMcpConfig(
            command=sys.executable,
            args=[str(fixture)],
            tool_name="generate_react_from_figma",
            figma_arg_name="figma_url",
        )
    )
    result = client.generate_react_from_figma("https://figma.example.com/file/123")
    assert result.entry_file == "src/App.tsx"
    assert "src/App.tsx" in result.files
    assert result.cache_hit is False


def test_d2c_mcp_client_uses_local_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fixture = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"
    counter_file = tmp_path / "counter.txt"
    monkeypatch.setenv("FAKE_MCP_COUNTER_FILE", str(counter_file))
    client = D2CMcpClient(
        D2CMcpConfig(
            command=sys.executable,
            args=[str(fixture)],
            tool_name="generate_react_from_figma",
            figma_arg_name="figma_url",
        )
    )

    cache_dir = tmp_path / "cache"
    figma_url = "https://figma.example.com/file/123"
    first = client.generate_react_from_figma(figma_url, cache_dir=cache_dir)
    second = client.generate_react_from_figma(figma_url, cache_dir=cache_dir)

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert first.files == second.files
    assert counter_file.read_text(encoding="utf-8") == "1"
    assert len(list(cache_dir.glob("*.json"))) == 1


def test_d2c_mcp_client_only_caches_valid_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fixture = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_server.py"
    monkeypatch.setenv("FAKE_MCP_MODE", "invalid")
    client = D2CMcpClient(
        D2CMcpConfig(
            command=sys.executable,
            args=[str(fixture)],
            tool_name="generate_react_from_figma",
            figma_arg_name="figma_url",
        )
    )

    cache_dir = tmp_path / "cache"
    with pytest.raises(ValueError):
        client.generate_react_from_figma("https://figma.example.com/file/123", cache_dir=cache_dir)

    assert not cache_dir.exists() or not any(cache_dir.iterdir())
