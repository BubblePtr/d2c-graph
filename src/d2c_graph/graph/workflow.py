from __future__ import annotations

import json
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from d2c_graph.clients.d2c_mcp import D2CMcpClient
from d2c_graph.config import AppConfig
from d2c_graph.graph.checks import (
    assert_no_absolute_kmp_layout,
    assert_no_absolute_react_layout,
)
from d2c_graph.graph.state import GraphState, NodeRun
from d2c_graph.llm.runner import PromptRunner
from d2c_graph.runtime import (
    copy_tree,
    ensure_directory,
    reset_directory,
    run_shell_command,
    summarize_state,
    write_json_file,
    write_text_file,
)


@dataclass(slots=True)
class PipelineDependencies:
    d2c_client: D2CMcpClient
    text_runner: PromptRunner
    vision_runner: PromptRunner
    command_runner: Any = run_shell_command


class PipelineWorkflow:
    def __init__(self, config: AppConfig, dependencies: PipelineDependencies):
        self.config = config
        self.dependencies = dependencies
        self.package_root = Path(__file__).resolve().parents[1]
        self.prompts_dir = self.package_root / "prompts"
        self.templates_dir = self.package_root / "templates"

    def compile(self, checkpointer: Any):
        react_graph = self._build_react_subgraph().compile(name="react_subgraph")
        kmp_graph = self._build_kmp_subgraph().compile(name="kmp_subgraph")

        graph = StateGraph(GraphState)
        graph.add_node("validate_inputs", self._tracked("validate_inputs", self._validate_inputs))
        graph.add_node("fetch_d2c_react", self._tracked("fetch_d2c_react", self._fetch_d2c_react))
        graph.add_node("analyze_screenshot", self._tracked("analyze_screenshot", self._analyze_screenshot))
        graph.add_node("reconcile_facts", self._tracked("reconcile_facts", self._reconcile_facts))
        graph.add_node("react_subgraph", react_graph)
        graph.add_node("kmp_subgraph", kmp_graph)
        graph.add_node("finalize", self._tracked("finalize", self._finalize))

        graph.add_edge(START, "validate_inputs")
        graph.add_edge("validate_inputs", "fetch_d2c_react")
        graph.add_edge("validate_inputs", "analyze_screenshot")
        graph.add_edge("fetch_d2c_react", "reconcile_facts")
        graph.add_edge("analyze_screenshot", "reconcile_facts")
        graph.add_edge("reconcile_facts", "react_subgraph")
        graph.add_edge("react_subgraph", "kmp_subgraph")
        graph.add_edge("kmp_subgraph", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(checkpointer=checkpointer, name="d2c_graph")

    def _build_react_subgraph(self) -> StateGraph:
        graph = StateGraph(GraphState)
        graph.add_node("save_d2c", self._tracked("save_d2c", self._save_d2c))
        graph.add_node("scaffold_react", self._tracked("scaffold_react", self._scaffold_react))
        graph.add_node(
            "generate_responsive_react",
            self._tracked("generate_responsive_react", self._generate_responsive_react),
        )
        graph.add_node("write_react_files", self._tracked("write_react_files", self._write_react_files))
        graph.add_node("verify_react_build", self._tracked("verify_react_build", self._verify_react_build))
        graph.add_edge(START, "save_d2c")
        graph.add_edge("save_d2c", "scaffold_react")
        graph.add_edge("scaffold_react", "generate_responsive_react")
        graph.add_edge("generate_responsive_react", "write_react_files")
        graph.add_edge("write_react_files", "verify_react_build")
        graph.add_edge("verify_react_build", END)
        return graph

    def _build_kmp_subgraph(self) -> StateGraph:
        graph = StateGraph(GraphState)
        graph.add_node("scaffold_kmp", self._tracked("scaffold_kmp", self._scaffold_kmp))
        graph.add_node("generate_kmp", self._tracked("generate_kmp", self._generate_kmp))
        graph.add_node("write_kmp_files", self._tracked("write_kmp_files", self._write_kmp_files))
        graph.add_node("verify_kmp_build", self._tracked("verify_kmp_build", self._verify_kmp_build))
        graph.add_edge(START, "scaffold_kmp")
        graph.add_edge("scaffold_kmp", "generate_kmp")
        graph.add_edge("generate_kmp", "write_kmp_files")
        graph.add_edge("write_kmp_files", "verify_kmp_build")
        graph.add_edge("verify_kmp_build", END)
        return graph

    def _tracked(self, node_name: str, handler):
        def wrapper(state: GraphState) -> GraphState:
            node_dir = self._node_dir(state, node_name)
            ensure_directory(node_dir)
            started_at = self._now_iso()
            write_json_file(node_dir / "state_input.json", summarize_state(dict(state)))
            try:
                updates = handler(state, node_dir)
                finished_at = self._now_iso()
                record: NodeRun = {
                    "node": node_name,
                    "status": "completed",
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "duration_ms": self._duration_ms(started_at, finished_at),
                    "node_dir": str(node_dir),
                }
                write_json_file(node_dir / "state_output.json", summarize_state(updates))
                return {**updates, "node_runs": [record]}
            except Exception as exc:
                finished_at = self._now_iso()
                write_text_file(node_dir / "error.txt", traceback.format_exc())
                record = {
                    "node": node_name,
                    "status": "failed",
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "duration_ms": self._duration_ms(started_at, finished_at),
                    "node_dir": str(node_dir),
                    "error": str(exc),
                }
                write_json_file(node_dir / "failure.json", {"error": str(exc)})
                exc.node_record = record  # type: ignore[attr-defined]
                raise

        return wrapper

    def _validate_inputs(self, state: GraphState, node_dir: Path) -> GraphState:
        figma_url = state.get("figma_url")
        screenshot_path = state.get("screenshot_path")
        workspace_root = state.get("workspace_root")
        if not figma_url:
            raise ValueError("figma_url is required")
        if not screenshot_path:
            raise ValueError("screenshot_path is required")
        if not workspace_root:
            raise ValueError("workspace_root is required")

        image = Path(screenshot_path)
        if not image.exists():
            raise FileNotFoundError(f"screenshot not found: {image}")

        root = ensure_directory(workspace_root)
        ensure_directory(root / "d2c")
        ensure_directory(root / "react")
        ensure_directory(root / "kmp")
        job_id = state.get("job_id") or uuid.uuid4().hex[:12]
        thread_id = state.get("thread_id") or job_id
        run_root = ensure_directory(root / "runs" / thread_id)
        write_json_file(node_dir / "validated.json", {"figma_url": figma_url, "screenshot_path": str(image)})
        return {
            "job_id": job_id,
            "thread_id": thread_id,
            "run_root": str(run_root),
            "model_plan": {
                "vision": f"{self.config.models.vision.provider}:{self.config.models.vision.model}",
                "text": f"{self.config.models.text.provider}:{self.config.models.text.model}",
            },
        }

    def _fetch_d2c_react(self, state: GraphState, node_dir: Path) -> GraphState:
        result = self.dependencies.d2c_client.generate_react_from_figma(state["figma_url"])
        write_json_file(node_dir / "d2c_summary.json", {"entry_file": result.entry_file, "files": list(result.files)})
        write_json_file(node_dir / "d2c_raw_response.json", result.raw_response)
        return {
            "d2c_raw_files": result.files,
            "d2c_entry": result.entry_file,
            "d2c_raw_response": result.raw_response,
        }

    def _analyze_screenshot(self, state: GraphState, node_dir: Path) -> GraphState:
        prompt = self._render_prompt("visual_anchors.md")
        payload = self.dependencies.vision_runner.run_json(
            "analyze_screenshot",
            prompt,
            node_dir,
            image_path=state["screenshot_path"],
        )
        anchors = payload.get("visual_anchors") or payload.get("anchors") or payload.get("summary") or payload
        if isinstance(anchors, list):
            normalized = "\n".join(f"- {item}" for item in anchors)
        else:
            normalized = str(anchors)
        return {"visual_anchors_raw": normalized}

    def _reconcile_facts(self, state: GraphState, node_dir: Path) -> GraphState:
        self._require_fields(state, "d2c_raw_files", "d2c_entry", "visual_anchors_raw")
        entry_code = state["d2c_raw_files"][state["d2c_entry"]]
        prompt = self._render_prompt(
            "reconcile_facts.md",
            visual_anchors_raw=state["visual_anchors_raw"],
            d2c_entry=state["d2c_entry"],
            d2c_files="\n".join(sorted(state["d2c_raw_files"].keys())),
            d2c_entry_code=entry_code,
        )
        payload = self.dependencies.text_runner.run_json("reconcile_facts", prompt, node_dir)
        reconciled = payload.get("visual_anchors_reconciled") or payload.get("summary") or payload
        return {"visual_anchors_reconciled": str(reconciled)}

    def _save_d2c(self, state: GraphState, node_dir: Path) -> GraphState:
        self._require_fields(state, "workspace_root", "d2c_raw_files")
        d2c_root = reset_directory(Path(state["workspace_root"]) / "d2c")
        artifacts: dict[str, str] = {}
        for relative_path, content in state["d2c_raw_files"].items():
            output = d2c_root / relative_path
            write_text_file(output, content)
            artifacts[relative_path] = str(output)
        write_json_file(node_dir / "artifacts.json", artifacts)
        return {"react_artifacts": artifacts}

    def _scaffold_react(self, state: GraphState, node_dir: Path) -> GraphState:
        target = Path(state["workspace_root"]) / "react"
        copy_tree(self.templates_dir / "react", target)
        write_json_file(node_dir / "scaffold.json", {"target": str(target)})
        return {}

    def _generate_responsive_react(self, state: GraphState, node_dir: Path) -> GraphState:
        self._require_fields(state, "d2c_raw_files", "d2c_entry", "visual_anchors_reconciled")
        prompt = self._render_prompt(
            "generate_react.md",
            visual_anchors_reconciled=state["visual_anchors_reconciled"],
            d2c_entry=state["d2c_entry"],
            d2c_entry_code=state["d2c_raw_files"][state["d2c_entry"]],
        )
        payload = self.dependencies.text_runner.run_json("generate_responsive_react", prompt, node_dir)
        files = payload.get("files")
        if not isinstance(files, dict):
            app_tsx = payload.get("app_tsx")
            if not isinstance(app_tsx, str):
                raise ValueError("generate_react prompt must return files or app_tsx")
            files = {"src/App.tsx": app_tsx}
        return {"react_generated_files": files}

    def _write_react_files(self, state: GraphState, node_dir: Path) -> GraphState:
        self._require_fields(state, "workspace_root", "react_generated_files")
        react_root = Path(state["workspace_root"]) / "react"
        artifacts: dict[str, str] = {}
        for relative_path, content in state["react_generated_files"].items():
            assert_no_absolute_react_layout(content)
            output = react_root / relative_path
            write_text_file(output, content)
            artifacts[relative_path] = str(output)
        write_json_file(node_dir / "artifacts.json", artifacts)
        return {"react_artifacts": artifacts}

    def _verify_react_build(self, state: GraphState, node_dir: Path) -> GraphState:
        react_root = Path(state["workspace_root"]) / "react"
        result = self.dependencies.command_runner(self.config.build.react.command, react_root)
        write_json_file(node_dir / "build.json", result)
        if result["returncode"] != 0:
            raise RuntimeError("React build failed")
        return {"react_build_result": result}

    def _scaffold_kmp(self, state: GraphState, node_dir: Path) -> GraphState:
        target = Path(state["workspace_root"]) / "kmp"
        copy_tree(self.templates_dir / "kmp", target)
        write_json_file(node_dir / "scaffold.json", {"target": str(target)})
        return {}

    def _generate_kmp(self, state: GraphState, node_dir: Path) -> GraphState:
        self._require_fields(state, "react_generated_files", "visual_anchors_reconciled")
        react_app = state["react_generated_files"].get("src/App.tsx")
        if not react_app:
            raise ValueError("React output does not contain src/App.tsx")
        prompt = self._render_prompt(
            "generate_kmp.md",
            visual_anchors_reconciled=state["visual_anchors_reconciled"],
            react_app_tsx=react_app,
        )
        payload = self.dependencies.text_runner.run_json("generate_kmp", prompt, node_dir)
        files = payload.get("files")
        if not isinstance(files, dict):
            app_kt = payload.get("app_kt")
            if not isinstance(app_kt, str):
                raise ValueError("generate_kmp prompt must return files or app_kt")
            files = {"composeApp/src/commonMain/kotlin/App.kt": app_kt}
        return {"kmp_generated_files": files}

    def _write_kmp_files(self, state: GraphState, node_dir: Path) -> GraphState:
        self._require_fields(state, "workspace_root", "kmp_generated_files")
        kmp_root = Path(state["workspace_root"]) / "kmp"
        artifacts: dict[str, str] = {}
        for relative_path, content in state["kmp_generated_files"].items():
            assert_no_absolute_kmp_layout(content)
            output = kmp_root / relative_path
            write_text_file(output, content)
            artifacts[relative_path] = str(output)
        write_json_file(node_dir / "artifacts.json", artifacts)
        return {"kmp_artifacts": artifacts}

    def _verify_kmp_build(self, state: GraphState, node_dir: Path) -> GraphState:
        kmp_root = Path(state["workspace_root"]) / "kmp"
        result = self.dependencies.command_runner(self.config.build.kmp.command, kmp_root)
        write_json_file(node_dir / "build.json", result)
        if result["returncode"] != 0:
            raise RuntimeError("KMP build failed")
        return {"kmp_build_result": result}

    def _finalize(self, state: GraphState, node_dir: Path) -> GraphState:
        run_root = Path(state["run_root"])
        manifest = {
            "job_id": state["job_id"],
            "thread_id": state["thread_id"],
            "figma_url": state["figma_url"],
            "screenshot_path": state["screenshot_path"],
            "workspace_root": state["workspace_root"],
            "model_plan": state.get("model_plan", {}),
            "d2c_entry": state.get("d2c_entry"),
            "node_runs": state.get("node_runs", []),
            "react_artifacts": state.get("react_artifacts", {}),
            "react_build_result": state.get("react_build_result"),
            "kmp_artifacts": state.get("kmp_artifacts", {}),
            "kmp_build_result": state.get("kmp_build_result"),
        }
        manifest_path = run_root / "manifest.json"
        write_json_file(manifest_path, manifest)
        write_json_file(node_dir / "manifest_pointer.json", {"manifest_path": str(manifest_path)})
        return {"manifest_path": str(manifest_path)}

    def _render_prompt(self, name: str, **variables: str) -> str:
        template = (self.prompts_dir / name).read_text(encoding="utf-8")
        return template.format(**variables)

    def _require_fields(self, state: GraphState, *fields: str) -> None:
        missing = [field for field in fields if not state.get(field)]
        if missing:
            raise ValueError(f"Missing required state fields: {', '.join(missing)}")

    def _node_dir(self, state: GraphState, node_name: str) -> Path:
        run_root = Path(state.get("run_root") or Path(state["workspace_root"]) / "runs" / state.get("thread_id", "unknown"))
        return run_root / "nodes" / node_name

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _duration_ms(self, started_at: str, finished_at: str) -> int:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(finished_at)
        return int((end - start).total_seconds() * 1000)


def default_initial_state(figma_url: str, screenshot_path: str, workspace_root: str) -> GraphState:
    thread_id = uuid.uuid4().hex[:12]
    return {
        "figma_url": figma_url,
        "screenshot_path": screenshot_path,
        "workspace_root": workspace_root,
        "thread_id": thread_id,
        "job_id": thread_id,
        "node_runs": [],
        "errors": [],
    }
