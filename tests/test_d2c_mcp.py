from __future__ import annotations

import sys
from pathlib import Path

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
