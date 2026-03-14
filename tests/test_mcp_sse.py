from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from d2c_graph.clients.d2c_mcp import D2CMcpClient
from d2c_graph.clients.figma_mcp import FigmaMcpClient
from d2c_graph.config import D2CMcpConfig, FigmaMcpConfig


PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9sot6RcAAAAASUVORK5CYII="
)


class FakeSseMcpServer(ThreadingHTTPServer):
    def __init__(self, server_address):
        super().__init__(server_address, FakeSseMcpHandler)
        self.stream_ready = threading.Event()
        self.stop_stream = threading.Event()
        self.stream_lock = threading.Lock()
        self.stream_writer = None
        self.tool_calls = 0

    def write_sse_message(self, payload: dict) -> None:
        if self.stream_writer is None:
            raise RuntimeError("SSE stream is not connected")
        body = f"event: message\ndata: {json.dumps(payload)}\n\n".encode("utf-8")
        with self.stream_lock:
            self.stream_writer.write(body)
            self.stream_writer.flush()


class FakeSseMcpHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/sse":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.server.stream_writer = self.wfile
        self.server.stream_ready.set()
        self.wfile.write(b"event: endpoint\ndata: /messages\n\n")
        self.wfile.flush()
        self.server.stop_stream.wait(timeout=5)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/messages":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        self.send_response(202)
        self.send_header("Content-Length", "0")
        self.end_headers()

        if payload.get("method") == "notifications/initialized":
            return
        if payload.get("method") == "initialize":
            self.server.write_sse_message(
                {"jsonrpc": "2.0", "id": payload["id"], "result": {"capabilities": {}}}
            )
            return
        if payload.get("method") != "tools/call":
            return

        self.server.tool_calls += 1
        tool_name = payload["params"]["name"]
        if tool_name == "generate_react_from_figma":
            result = {
                "files": {"src/App.tsx": "export default function App() { return <div>Hello</div>; }"},
                "entry_file": "src/App.tsx",
            }
            message = {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "structuredContent": result,
                    "content": [{"type": "text", "text": json.dumps(result)}],
                },
            }
        elif tool_name == "get_screenshot":
            result = {"url": PNG_DATA_URL}
            message = {
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "structuredContent": result,
                    "content": [{"type": "text", "text": json.dumps(result)}],
                },
            }
        else:
            message = {"jsonrpc": "2.0", "id": payload["id"], "error": {"message": "unknown tool"}}
        self.server.write_sse_message(message)

    def log_message(self, format: str, *args) -> None:
        return


def _start_fake_sse_server() -> tuple[FakeSseMcpServer, threading.Thread, str]:
    server = FakeSseMcpServer(("127.0.0.1", 0))
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://{host}:{port}/sse"


def test_d2c_mcp_client_supports_sse_transport(tmp_path: Path):
    server, thread, sse_url = _start_fake_sse_server()
    try:
        client = D2CMcpClient(
            D2CMcpConfig(
                transport="sse",
                url=sse_url,
                tool_name="generate_react_from_figma",
            )
        )
        result = client.generate_react_from_figma(
            "https://figma.example.com/file/123?node-id=1-2",
            cache_dir=tmp_path / "cache",
        )
        assert result.entry_file == "src/App.tsx"
        assert "src/App.tsx" in result.files
        assert server.tool_calls == 1
    finally:
        server.stop_stream.set()
        server.shutdown()
        thread.join(timeout=1)


def test_figma_mcp_client_supports_sse_transport(tmp_path: Path):
    server, thread, sse_url = _start_fake_sse_server()
    try:
        client = FigmaMcpClient(
            FigmaMcpConfig(
                transport="sse",
                url=sse_url,
            )
        )
        result = client.fetch_screenshot(
            "https://www.figma.com/design/abc123/Example?node-id=1-2",
            cache_dir=tmp_path / "cache",
        )
        assert Path(result.image_path).exists()
        assert result.cache_hit is False
        assert server.tool_calls == 1
    finally:
        server.stop_stream.set()
        server.shutdown()
        thread.join(timeout=1)
