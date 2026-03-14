from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from d2c_graph.clients.figma_mcp import FigmaMcpClient
from d2c_graph.config import FigmaMcpConfig


PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9sot6RcAAAAASUVORK5CYII="
)


class FakeHttpMcpServer(ThreadingHTTPServer):
    def __init__(self, server_address):
        super().__init__(server_address, FakeHttpMcpHandler)
        self.tool_calls = 0
        self.session_ids: list[str | None] = []


class FakeHttpMcpHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/mcp":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.session_ids.append(self.headers.get("Mcp-Session-Id"))

        if payload.get("method") == "initialize":
            body = {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"capabilities": {}},
            }
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Mcp-Session-Id", "session-123")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return

        if payload.get("method") == "notifications/initialized":
            self.send_response(HTTPStatus.ACCEPTED)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        self.server.tool_calls += 1
        body = {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {
                "structuredContent": {"url": PNG_DATA_URL},
                "content": [{"type": "text", "text": json.dumps({"url": PNG_DATA_URL})}],
            },
        }
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args) -> None:
        return


def _start_fake_http_server() -> tuple[FakeHttpMcpServer, threading.Thread, str]:
    server = FakeHttpMcpServer(("127.0.0.1", 0))
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://{host}:{port}/mcp"


def test_figma_mcp_client_supports_http_transport(tmp_path: Path):
    server, thread, http_url = _start_fake_http_server()
    try:
        client = FigmaMcpClient(FigmaMcpConfig(type="http", url=http_url))
        result = client.fetch_screenshot(
            "https://www.figma.com/design/abc123/Example?node-id=1-2",
            cache_dir=tmp_path / "cache",
        )
        assert Path(result.image_path).exists()
        assert result.cache_hit is False
        assert server.tool_calls == 1
        assert server.session_ids == [None, "session-123", "session-123"]
    finally:
        server.shutdown()
        thread.join(timeout=1)
