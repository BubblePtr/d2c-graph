from __future__ import annotations

from operator import add
from typing import Annotated, Any
from typing_extensions import TypedDict


class NodeRun(TypedDict, total=False):
    node: str
    status: str
    started_at: str
    finished_at: str
    duration_ms: int
    node_dir: str
    error: str


class GraphState(TypedDict, total=False):
    figma_url: str
    screenshot_path: str
    workspace_root: str
    job_id: str
    thread_id: str
    run_root: str
    d2c_raw_files: dict[str, str]
    d2c_entry: str
    d2c_raw_response: dict[str, Any]
    visual_anchors_raw: str
    visual_anchors_reconciled: str
    react_generated_files: dict[str, str]
    react_artifacts: dict[str, str]
    react_build_result: dict[str, Any]
    kmp_generated_files: dict[str, str]
    kmp_artifacts: dict[str, str]
    kmp_build_result: dict[str, Any]
    manifest_path: str
    model_plan: dict[str, str]
    node_runs: Annotated[list[NodeRun], add]
    errors: Annotated[list[str], add]
