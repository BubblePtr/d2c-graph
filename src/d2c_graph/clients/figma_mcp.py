from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from d2c_graph.clients.mcp_process import create_mcp_client
from d2c_graph.config import FigmaMcpConfig


@dataclass(slots=True)
class FigmaNodeRef:
    file_key: str
    node_id: str


@dataclass(slots=True)
class FigmaScreenshotResult:
    image_path: str
    raw_response: dict[str, Any]
    source_url: str
    cache_hit: bool = False


class FigmaMcpClient:
    def __init__(self, config: FigmaMcpConfig):
        self.config = config
        self._mcp_client = create_mcp_client(config)

    def fetch_screenshot(self, figma_url: str, *, cache_dir: str | Path) -> FigmaScreenshotResult:
        node_ref = parse_figma_node_url(figma_url)
        cached = self._load_cached_result(cache_dir, node_ref)
        if cached is not None:
            return cached

        response = self._mcp_client.call_tool(
            self.config.tool_name,
            {
                self.config.file_key_arg_name: node_ref.file_key,
                self.config.node_id_arg_name: node_ref.node_id,
            },
        )
        source_url = self._extract_image_source(response)
        image_bytes, extension = self._read_image_bytes(source_url)
        result = self._write_cached_result(cache_dir, node_ref, figma_url, response, source_url, image_bytes, extension)
        return result

    def _cache_key(self, node_ref: FigmaNodeRef) -> str:
        return hashlib.sha256(f"{node_ref.file_key}:{node_ref.node_id}".encode("utf-8")).hexdigest()

    def _load_cached_result(self, cache_dir: str | Path, node_ref: FigmaNodeRef) -> FigmaScreenshotResult | None:
        metadata_path = Path(cache_dir) / f"{self._cache_key(node_ref)}.json"
        if not metadata_path.exists():
            return None

        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            image_path = Path(payload["image_path"])
            source_url = payload["source_url"]
            raw_response = payload["raw_response"]
            if not image_path.exists():
                raise FileNotFoundError(image_path)
            if not isinstance(source_url, str) or not source_url:
                raise ValueError("Cached screenshot source_url is invalid")
            if not isinstance(raw_response, dict):
                raise ValueError("Cached screenshot raw_response is invalid")
            return FigmaScreenshotResult(
                image_path=str(image_path),
                raw_response=raw_response,
                source_url=source_url,
                cache_hit=True,
            )
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            metadata_path.unlink(missing_ok=True)
            return None

    def _write_cached_result(
        self,
        cache_dir: str | Path,
        node_ref: FigmaNodeRef,
        figma_url: str,
        raw_response: dict[str, Any],
        source_url: str,
        image_bytes: bytes,
        extension: str,
    ) -> FigmaScreenshotResult:
        cache_root = Path(cache_dir)
        cache_root.mkdir(parents=True, exist_ok=True)
        cache_key = self._cache_key(node_ref)
        image_path = cache_root / f"{cache_key}{extension}"
        temp_image = image_path.with_suffix(image_path.suffix + ".tmp")
        temp_image.write_bytes(image_bytes)
        temp_image.replace(image_path)

        metadata = {
            "figma_url": figma_url,
            "file_key": node_ref.file_key,
            "node_id": node_ref.node_id,
            "image_path": str(image_path),
            "source_url": source_url,
            "raw_response": raw_response,
        }
        metadata_path = cache_root / f"{cache_key}.json"
        temp_metadata = metadata_path.with_suffix(".tmp")
        temp_metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        temp_metadata.replace(metadata_path)

        return FigmaScreenshotResult(
            image_path=str(image_path),
            raw_response=raw_response,
            source_url=source_url,
        )

    def _extract_image_source(self, result: dict[str, Any]) -> str:
        payload = result.get("structuredContent")
        source = self._extract_image_source_value(payload)
        if source:
            return source

        for block in result.get("content", []):
            if not isinstance(block, dict):
                continue
            source = self._extract_image_source_value(block)
            if source:
                return source
            text = block.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            stripped = text.strip()
            if stripped.startswith("data:image/") or stripped.startswith("http://") or stripped.startswith("https://"):
                return stripped
            try:
                source = self._extract_image_source_value(json.loads(stripped))
            except json.JSONDecodeError:
                continue
            if source:
                return source

        raise ValueError("Figma MCP screenshot result did not contain an image source")

    def _extract_image_source_value(self, payload: Any) -> str | None:
        if isinstance(payload, str):
            if payload.startswith("data:image/") or payload.startswith("http://") or payload.startswith("https://"):
                return payload
            return None
        if isinstance(payload, list):
            for item in payload:
                source = self._extract_image_source_value(item)
                if source:
                    return source
            return None
        if not isinstance(payload, dict):
            return None

        for key in ("source", "url", "image_url", "imageUrl", "screenshot_url", "screenshotUrl"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, dict):
                nested = self._extract_image_source_value(value)
                if nested:
                    return nested
        images = payload.get("images")
        if isinstance(images, list):
            return self._extract_image_source_value(images)
        return None

    def _read_image_bytes(self, source_url: str) -> tuple[bytes, str]:
        if source_url.startswith("data:image/"):
            header, _, encoded = source_url.partition(",")
            mime_type = header[len("data:") :].split(";", 1)[0]
            extension = mimetypes.guess_extension(mime_type) or ".png"
            return base64.b64decode(encoded), extension

        with urlopen(source_url, timeout=self.config.request_timeout_seconds) as response:
            image_bytes = response.read()
            mime_type = response.headers.get_content_type()
        extension = mimetypes.guess_extension(mime_type) or Path(urlparse(source_url).path).suffix or ".png"
        if extension == ".jpe":
            extension = ".jpg"
        return image_bytes, extension


def parse_figma_node_url(figma_url: str) -> FigmaNodeRef:
    parsed = urlparse(figma_url)
    path_parts = [part for part in parsed.path.split("/") if part]
    try:
        marker_index = next(index for index, part in enumerate(path_parts) if part in {"file", "design"})
    except StopIteration as exc:
        raise ValueError(f"Unsupported Figma URL path: {figma_url}") from exc

    file_key_index = marker_index + 1
    if file_key_index >= len(path_parts):
        raise ValueError(f"Figma URL does not contain a file key: {figma_url}")

    query = parse_qs(parsed.query)
    node_id = query.get("node-id", [None])[0]
    if not node_id:
        raise ValueError(f"Figma URL does not contain node-id: {figma_url}")

    return FigmaNodeRef(file_key=path_parts[file_key_index], node_id=node_id)
