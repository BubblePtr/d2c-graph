from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol

from langchain_core.messages import HumanMessage, SystemMessage

from d2c_graph.runtime import encode_image_as_data_url, write_json_file, write_text_file


class PromptRunner(Protocol):
    def run_json(
        self,
        node_name: str,
        prompt: str,
        node_dir: Path,
        *,
        image_path: str | None = None,
    ) -> dict[str, Any]: ...


class JsonPromptRunner:
    def __init__(self, model: Any):
        self.model = model

    def run_json(
        self,
        node_name: str,
        prompt: str,
        node_dir: Path,
        *,
        image_path: str | None = None,
    ) -> dict[str, Any]:
        write_text_file(node_dir / "prompt.txt", prompt)
        messages: list[Any] = [SystemMessage(content="Return only valid JSON.")]
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if image_path:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": encode_image_as_data_url(image_path)},
                }
            )
        messages.append(HumanMessage(content=content))
        response = self.model.invoke(messages)
        raw_text = _coerce_message_content(response.content)
        write_text_file(node_dir / "response.txt", raw_text)
        payload = _extract_json(raw_text)
        write_json_file(node_dir / "response.json", payload)
        return payload


def _coerce_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                texts.append(str(block["text"]))
            else:
                texts.append(str(block))
        return "\n".join(texts)
    return str(content)


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    try:
        payload = json.loads(stripped)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    code_block = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if code_block:
        payload = json.loads(code_block.group(1))
        if isinstance(payload, dict):
            return payload

    brace_match = re.search(r"(\{.*\})", text, re.DOTALL)
    if brace_match:
        payload = json.loads(brace_match.group(1))
        if isinstance(payload, dict):
            return payload

    raise ValueError("Model response does not contain a JSON object")
