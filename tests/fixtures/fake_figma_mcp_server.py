from __future__ import annotations

import json
import os
import sys
from pathlib import Path


PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9sot6RcAAAAASUVORK5CYII="
)


def read_message() -> dict:
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            raise SystemExit(0)
        if line == b"\r\n":
            break
        key, _, value = line.decode("utf-8").partition(":")
        headers[key.strip().lower()] = value.strip()
    length = int(headers["content-length"])
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def write_message(payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
    sys.stdout.buffer.write(header + body)
    sys.stdout.buffer.flush()


def record_call() -> None:
    counter_path = os.getenv("FAKE_FIGMA_COUNTER_FILE")
    if not counter_path:
        return
    path = Path(counter_path).resolve()
    current = int(path.read_text(encoding="utf-8") or "0") if path.exists() else 0
    path.write_text(str(current + 1), encoding="utf-8")


while True:
    message = read_message()
    method = message.get("method")
    if method == "initialize":
        write_message({"jsonrpc": "2.0", "id": message["id"], "result": {"capabilities": {}}})
    elif method == "tools/call":
        record_call()
        result = {"url": PNG_DATA_URL}
        write_message(
            {
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {
                    "structuredContent": result,
                    "content": [{"type": "text", "text": json.dumps(result)}],
                },
            }
        )
    else:
        if "id" in message:
            write_message({"jsonrpc": "2.0", "id": message["id"], "result": {}})
