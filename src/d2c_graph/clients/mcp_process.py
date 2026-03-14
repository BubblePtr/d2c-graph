from __future__ import annotations

import json
import socket
import subprocess
import threading
import time
from http.client import HTTPConnection, HTTPSConnection
from queue import Empty, Queue
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


class StdioMcpClient:
    def __init__(self, config: Any, *, client_name: str = "d2c-graph", client_version: str = "0.1.0"):
        self.config = config
        self.client_name = client_name
        self.client_version = client_version
        self._message_id = 0

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        command = self.config.command
        if not command:
            raise ValueError("stdio MCP transport requires command")
        with subprocess.Popen(
            [command, *self.config.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        ) as process:
            self._initialize(process)
            response = self._request(
                process,
                "tools/call",
                {"name": tool_name, "arguments": arguments},
            )
            if process.stdin:
                process.stdin.close()
            return response

    def _initialize(self, process: subprocess.Popen[bytes]) -> None:
        self._request(
            process,
            "initialize",
            {
                "protocolVersion": self.config.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": self.client_name, "version": self.client_version},
            },
        )
        self._notify(process, "notifications/initialized", {})

    def _request(
        self,
        process: subprocess.Popen[bytes],
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        self._message_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._message_id,
            "method": method,
            "params": params,
        }
        self._write_message(process, payload)
        deadline = time.monotonic() + self.config.request_timeout_seconds
        while time.monotonic() < deadline:
            message = self._read_message(process)
            if "id" not in message or message["id"] != self._message_id:
                continue
            if "error" in message:
                raise RuntimeError(f"MCP error for {method}: {message['error']}")
            return message.get("result", {})
        raise TimeoutError(f"MCP request timed out for method {method}")

    def _notify(
        self,
        process: subprocess.Popen[bytes],
        method: str,
        params: dict[str, Any],
    ) -> None:
        self._write_message(
            process,
            {"jsonrpc": "2.0", "method": method, "params": params},
        )

    def _write_message(self, process: subprocess.Popen[bytes], payload: dict[str, Any]) -> None:
        if process.stdin is None:
            raise RuntimeError("MCP process stdin is unavailable")
        body = json.dumps(payload).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        process.stdin.write(header + body)
        process.stdin.flush()

    def _read_message(self, process: subprocess.Popen[bytes]) -> dict[str, Any]:
        if process.stdout is None:
            raise RuntimeError("MCP process stdout is unavailable")
        headers: dict[str, str] = {}
        while True:
            line = process.stdout.readline()
            if not line:
                stderr = b""
                if process.stderr is not None:
                    stderr = process.stderr.read()
                raise RuntimeError(f"MCP server closed unexpectedly: {stderr.decode('utf-8', errors='ignore')}")
            if line == b"\r\n":
                break
            key, _, value = line.decode("utf-8").partition(":")
            headers[key.strip().lower()] = value.strip()
        content_length = int(headers["content-length"])
        body = process.stdout.read(content_length)
        return json.loads(body.decode("utf-8"))


class SseMcpClient:
    def __init__(self, config: Any, *, client_name: str = "d2c-graph", client_version: str = "0.1.0"):
        self.config = config
        self.client_name = client_name
        self.client_version = client_version
        self._message_id = 0
        self._pending: dict[int, Queue[dict[str, Any]]] = {}
        self._pending_lock = threading.Lock()
        self._endpoint_queue: Queue[str] = Queue()
        self._reader_error: Queue[BaseException] = Queue()
        self._stop_reader = threading.Event()
        self._response = None
        self._stream_connection: HTTPConnection | HTTPSConnection | None = None
        self._reader_thread: threading.Thread | None = None
        self._message_endpoint: str | None = None

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._start_session()
        try:
            self._initialize()
            return self._request(
                "tools/call",
                {"name": tool_name, "arguments": arguments},
            )
        finally:
            self._close_session()

    def _start_session(self) -> None:
        url = self.config.url
        if not url:
            raise ValueError("sse MCP transport requires url")
        timeout = max(self.config.startup_timeout_seconds, self.config.request_timeout_seconds)
        parsed = urlparse(url)
        connection_class = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
        self._stream_connection = connection_class(parsed.hostname, parsed.port, timeout=timeout)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        self._stream_connection.request(
            "GET",
            path,
            headers={
                "Accept": "text/event-stream",
                "Cache-Control": "no-cache",
            },
        )
        self._response = self._stream_connection.getresponse()
        if self._response.status >= 400:
            raise RuntimeError(f"MCP SSE stream request failed: HTTP {self._response.status}")
        self._stop_reader.clear()
        self._message_endpoint = None
        self._reader_thread = threading.Thread(target=self._read_sse_stream, daemon=True)
        self._reader_thread.start()
        try:
            endpoint = self._endpoint_queue.get(timeout=self.config.startup_timeout_seconds)
        except Empty as exc:
            raise TimeoutError("MCP SSE endpoint event was not received") from exc
        self._message_endpoint = urljoin(url, endpoint)

    def _close_session(self) -> None:
        self._stop_reader.set()
        response = self._response
        stream_connection = self._stream_connection
        reader_thread = self._reader_thread
        self._response = None
        self._stream_connection = None
        self._reader_thread = None
        self._message_endpoint = None
        with self._pending_lock:
            self._pending.clear()
        while not self._endpoint_queue.empty():
            self._endpoint_queue.get_nowait()
        while not self._reader_error.empty():
            self._reader_error.get_nowait()

        def finalize() -> None:
            if stream_connection is not None and stream_connection.sock is not None:
                try:
                    stream_connection.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            if response is not None:
                response.close()
            if stream_connection is not None:
                stream_connection.close()
            if reader_thread is not None:
                reader_thread.join(timeout=0.1)

        threading.Thread(target=finalize, daemon=True).start()

    def _initialize(self) -> None:
        self._request(
            "initialize",
            {
                "protocolVersion": self.config.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": self.client_name, "version": self.client_version},
            },
        )
        self._notify("notifications/initialized", {})

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._message_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._message_id,
            "method": method,
            "params": params,
        }
        queue: Queue[dict[str, Any]] = Queue()
        with self._pending_lock:
            self._pending[self._message_id] = queue
        try:
            immediate = self._post_message(payload)
            if immediate is not None:
                return self._extract_result(immediate, method)

            deadline = time.monotonic() + self.config.request_timeout_seconds
            while time.monotonic() < deadline:
                self._raise_reader_error()
                remaining = max(0.01, deadline - time.monotonic())
                try:
                    message = queue.get(timeout=min(0.25, remaining))
                except Empty:
                    continue
                return self._extract_result(message, method)
            raise TimeoutError(f"MCP request timed out for method {method}")
        finally:
            with self._pending_lock:
                self._pending.pop(self._message_id, None)

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._post_message(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
        )

    def _post_message(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        endpoint = self._message_endpoint
        if not endpoint:
            raise RuntimeError("MCP SSE message endpoint is unavailable")
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        with urlopen(request, timeout=self.config.request_timeout_seconds) as response:
            content_length = response.headers.get("Content-Length")
            if content_length is None:
                raw_body = response.read()
            else:
                raw_body = response.read(int(content_length))
            if not raw_body:
                return None
            return json.loads(raw_body.decode("utf-8"))

    def _extract_result(self, message: dict[str, Any], method: str) -> dict[str, Any]:
        if "error" in message:
            raise RuntimeError(f"MCP error for {method}: {message['error']}")
        return message.get("result", {})

    def _read_sse_stream(self) -> None:
        if self._response is None:
            return
        event_name = "message"
        data_lines: list[str] = []
        try:
            while not self._stop_reader.is_set():
                if self._response.fp is None:
                    break
                raw_line = self._response.fp.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8").rstrip("\r\n")
                if not line:
                    self._dispatch_sse_event(event_name, "\n".join(data_lines))
                    event_name = "message"
                    data_lines = []
                    continue
                if line.startswith(":"):
                    continue
                field, _, value = line.partition(":")
                if value.startswith(" "):
                    value = value[1:]
                if field == "event":
                    event_name = value or "message"
                elif field == "data":
                    data_lines.append(value)
        except BaseException as exc:  # noqa: BLE001
            if not self._stop_reader.is_set():
                self._reader_error.put(exc)

    def _dispatch_sse_event(self, event_name: str, data: str) -> None:
        if not data:
            return
        if event_name == "endpoint":
            self._endpoint_queue.put(data)
            return
        message = json.loads(data)
        message_id = message.get("id")
        if not isinstance(message_id, int):
            return
        with self._pending_lock:
            queue = self._pending.get(message_id)
        if queue is not None:
            queue.put(message)

    def _raise_reader_error(self) -> None:
        try:
            error = self._reader_error.get_nowait()
        except Empty:
            return
        raise RuntimeError(f"MCP SSE stream failed: {error}") from error


class StreamableHttpMcpClient:
    def __init__(self, config: Any, *, client_name: str = "d2c-graph", client_version: str = "0.1.0"):
        self.config = config
        self.client_name = client_name
        self.client_version = client_version
        self._message_id = 0
        self._session_id: str | None = None

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._initialize()
        self._notify("notifications/initialized", {})
        return self._request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )

    def _initialize(self) -> None:
        self._request(
            "initialize",
            {
                "protocolVersion": self.config.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": self.client_name, "version": self.client_version},
            },
        )

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._message_id += 1
        message = {
            "jsonrpc": "2.0",
            "id": self._message_id,
            "method": method,
            "params": params,
        }
        response = self._post_message(message)
        if "error" in response:
            raise RuntimeError(f"MCP error for {method}: {response['error']}")
        return response.get("result", {})

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._post_message(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
        )

    def _post_message(self, message: dict[str, Any]) -> dict[str, Any]:
        url = self.config.url
        if not url:
            raise ValueError("http MCP transport requires url")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": self.config.protocol_version,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        request = Request(
            url,
            data=json.dumps(message).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        with urlopen(request, timeout=self.config.request_timeout_seconds) as response:
            session_id = response.headers.get("Mcp-Session-Id")
            if session_id:
                self._session_id = session_id
            content_type = response.headers.get_content_type()
            if content_type == "text/event-stream":
                payload = self._read_streamable_http_sse(response)
            else:
                payload = self._read_json_response(response)
        return payload

    def _read_json_response(self, response) -> dict[str, Any]:
        content_length = response.headers.get("Content-Length")
        if content_length is None:
            raw_body = response.read()
        else:
            raw_body = response.read(int(content_length))
        if not raw_body:
            return {}
        return json.loads(raw_body.decode("utf-8"))

    def _read_streamable_http_sse(self, response) -> dict[str, Any]:
        event_name = "message"
        data_lines: list[str] = []
        while True:
            raw_line = response.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if not line:
                if data_lines:
                    payload = self._handle_stream_event(event_name, "\n".join(data_lines))
                    if payload is not None:
                        return payload
                event_name = "message"
                data_lines = []
                continue
            if line.startswith(":"):
                continue
            field, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field == "event":
                event_name = value or "message"
            elif field == "data":
                data_lines.append(value)
        raise RuntimeError("HTTP MCP response stream ended before returning a result")

    def _handle_stream_event(self, event_name: str, data: str) -> dict[str, Any] | None:
        if event_name not in {"message", "response"}:
            return None
        payload = json.loads(data)
        if "id" not in payload and "result" not in payload and "error" not in payload:
            return None
        return payload


def create_mcp_client(config: Any, *, client_name: str = "d2c-graph", client_version: str = "0.1.0"):
    if config.transport == "http":
        return StreamableHttpMcpClient(config, client_name=client_name, client_version=client_version)
    if config.transport == "sse":
        return SseMcpClient(config, client_name=client_name, client_version=client_version)
    return StdioMcpClient(config, client_name=client_name, client_version=client_version)
