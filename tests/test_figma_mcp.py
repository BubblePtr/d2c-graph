from __future__ import annotations

import sys
from pathlib import Path

from d2c_graph.clients.figma_mcp import FigmaMcpClient, parse_figma_node_url
from d2c_graph.config import FigmaMcpConfig


def test_parse_figma_node_url():
    result = parse_figma_node_url("https://www.figma.com/design/abc123/Example?node-id=1-2")
    assert result.file_key == "abc123"
    assert result.node_id == "1-2"


def test_figma_mcp_client_fetches_and_caches_screenshot(tmp_path: Path, monkeypatch):
    fixture = Path(__file__).resolve().parent / "fixtures" / "fake_figma_mcp_server.py"
    counter_file = tmp_path / "counter.txt"
    monkeypatch.setenv("FAKE_FIGMA_COUNTER_FILE", str(counter_file))
    client = FigmaMcpClient(
        FigmaMcpConfig(
            command=sys.executable,
            args=[str(fixture)],
        )
    )

    cache_dir = tmp_path / "cache"
    figma_url = "https://www.figma.com/design/abc123/Example?node-id=1-2"
    first = client.fetch_screenshot(figma_url, cache_dir=cache_dir)
    second = client.fetch_screenshot(figma_url, cache_dir=cache_dir)

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert Path(first.image_path).exists()
    assert Path(first.image_path).read_bytes() == Path(second.image_path).read_bytes()
    assert counter_file.read_text(encoding="utf-8") == "1"
