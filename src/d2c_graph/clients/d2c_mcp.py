from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from d2c_graph.config import D2CMcpConfig


@dataclass(slots=True)
class D2CResult:
    files: dict[str, str]
    entry_file: str
    raw_response: dict[str, Any]


class D2CMcpClient:
    def __init__(self, config: D2CMcpConfig):
        self.config = config
        self._message_id = 0

    def generate_react_from_figma(self, figma_url: str) -> D2CResult:
        arguments = dict(self.config.extra_tool_args)
        arguments[self.config.figma_arg_name] = figma_url
        with subprocess.Popen(
            [self.config.command, *self.config.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        ) as process:
            self._initialize(process)
            response = self._request(
                process,
                "tools/call",
                {"name": self.config.tool_name, "arguments": arguments},
            )
            if process.stdin:
                process.stdin.close()
            parsed = self._normalize_tool_result(response)
            return D2CResult(
                files=parsed["files"],
                entry_file=parsed["entry_file"],
                raw_response=response,
            )

    def _initialize(self, process: subprocess.Popen[bytes]) -> None:
        self._request(
            process,
            "initialize",
            {
                "protocolVersion": self.config.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "d2c-graph", "version": "0.1.0"},
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

    def _normalize_tool_result(self, result: dict[str, Any]) -> dict[str, Any]:
        if "structuredContent" in result:
            payload = result["structuredContent"]
            return self._normalize_payload(payload)

        content = result.get("content", [])
        text_blocks: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text_blocks.append(block.get("text", ""))
            elif isinstance(block, dict) and "text" in block:
                text_blocks.append(str(block["text"]))

        combined = "\n".join(text_blocks).strip()
        if not combined:
            raise ValueError("MCP tool result did not contain structuredContent or text content")
        try:
            payload = json.loads(combined)
        except json.JSONDecodeError as exc:
            raise ValueError("MCP text response is not valid JSON") from exc
        return self._normalize_payload(payload)

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        files = payload.get("files")
        if isinstance(files, list):
            normalized_files = {}
            for item in files:
                if not isinstance(item, dict) or "path" not in item or "content" not in item:
                    raise ValueError("Unsupported MCP files list format")
                normalized_files[item["path"]] = item["content"]
            files = normalized_files
        if not isinstance(files, dict) or not files:
            raise ValueError("MCP payload did not include a non-empty files map")

        entry_file = (
            payload.get("entry_file")
            or payload.get("entryFile")
            or payload.get("entry")
            or next(iter(files.keys()))
        )
        if entry_file not in files:
            raise ValueError(f"Entry file {entry_file} is not present in MCP files")
        return {"files": files, "entry_file": entry_file}
