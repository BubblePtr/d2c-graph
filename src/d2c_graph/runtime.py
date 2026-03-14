from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def ensure_directory(path: str | Path) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def reset_directory(path: str | Path) -> Path:
    directory = Path(path)
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def remove_path(path: str | Path) -> None:
    target = Path(path)
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()


def copy_tree(source: str | Path, destination: str | Path) -> None:
    src = Path(source)
    dst = Path(destination)
    reset_directory(dst)
    shutil.copytree(src, dst, dirs_exist_ok=True)


def write_text_file(path: str | Path, content: str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def write_json_file(path: str | Path, content: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return target


def encode_image_as_data_url(path: str | Path) -> str:
    image_path = Path(path)
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    suffix = image_path.suffix.lstrip(".") or "png"
    return f"data:image/{suffix};base64,{encoded}"


def run_shell_command(command: str, cwd: str | Path) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        shell=True,
        text=True,
        capture_output=True,
        env=os.environ.copy(),
    )
    return {
        "command": command,
        "cwd": str(cwd),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def summarize_state(value: Any, depth: int = 0) -> Any:
    if depth > 2:
        return "<truncated>"
    if isinstance(value, dict):
        if "files" in value and isinstance(value["files"], dict):
            return {"files": list(value["files"].keys())}
        return {key: summarize_state(item, depth + 1) for key, item in list(value.items())[:25]}
    if isinstance(value, list):
        return [summarize_state(item, depth + 1) for item in value[:10]]
    if isinstance(value, str) and len(value) > 600:
        return value[:600] + "...<truncated>"
    return value
