from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from d2c_graph.config import D2CMcpConfig
from d2c_graph.clients.mcp_process import create_mcp_client


@dataclass(slots=True)
class D2CResult:
    files: dict[str, str]
    entry_file: str
    raw_response: dict[str, Any]
    cache_hit: bool = False


class D2CMcpClient:
    def __init__(self, config: D2CMcpConfig):
        self.config = config
        self._mcp_client = create_mcp_client(config)

    def generate_react_from_figma(self, figma_url: str, *, cache_dir: str | Path | None = None) -> D2CResult:
        if cache_dir is not None:
            cached = self._load_cached_result(cache_dir, figma_url)
            if cached is not None:
                return cached

        arguments = dict(self.config.extra_tool_args)
        arguments[self.config.figma_arg_name] = figma_url
        response = self._mcp_client.call_tool(self.config.tool_name, arguments)
        parsed = self._normalize_tool_result(response)
        result = D2CResult(
            files=parsed["files"],
            entry_file=parsed["entry_file"],
            raw_response=response,
        )
        if cache_dir is not None:
            self._write_cached_result(cache_dir, figma_url, result)
        return result

    def _cache_file_path(self, cache_dir: str | Path, figma_url: str) -> Path:
        digest = hashlib.sha256(figma_url.encode("utf-8")).hexdigest()
        return Path(cache_dir) / f"{digest}.json"

    def _load_cached_result(self, cache_dir: str | Path, figma_url: str) -> D2CResult | None:
        cache_path = self._cache_file_path(cache_dir, figma_url)
        if not cache_path.exists():
            return None

        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            parsed = self._normalize_payload(payload)
            raw_response = payload.get("raw_response")
            if raw_response is not None and not isinstance(raw_response, dict):
                raise ValueError("Cached raw_response must be a JSON object")
            return D2CResult(
                files=parsed["files"],
                entry_file=parsed["entry_file"],
                raw_response=raw_response or {},
                cache_hit=True,
            )
        except (OSError, json.JSONDecodeError, ValueError):
            cache_path.unlink(missing_ok=True)
            return None

    def _write_cached_result(self, cache_dir: str | Path, figma_url: str, result: D2CResult) -> None:
        cache_path = self._cache_file_path(cache_dir, figma_url)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "figma_url": figma_url,
            "entry_file": result.entry_file,
            "files": result.files,
            "raw_response": result.raw_response,
        }
        temp_path = cache_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(cache_path)

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
