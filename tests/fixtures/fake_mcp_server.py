from __future__ import annotations

import json
import sys


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


while True:
    message = read_message()
    method = message.get("method")
    if method == "initialize":
        write_message({"jsonrpc": "2.0", "id": message["id"], "result": {"capabilities": {}}})
    elif method == "tools/call":
        result = {
            "files": {
                "src/App.tsx": "export default function App() { return <div>Hello</div>; }",
            },
            "entry_file": "src/App.tsx",
        }
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
