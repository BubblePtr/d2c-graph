from __future__ import annotations

import shlex
import sys
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from d2c_graph.clients.d2c_mcp import D2CResult
from d2c_graph.clients.figma_mcp import FigmaScreenshotResult
from d2c_graph.config import AppConfig
from d2c_graph.graph.workflow import PipelineDependencies, PipelineWorkflow, default_initial_state


class FakeFigmaClient:
    def __init__(self, screenshot_path: Path):
        self.screenshot_path = screenshot_path

    def fetch_screenshot(self, figma_url: str, *, cache_dir=None) -> FigmaScreenshotResult:
        if cache_dir is not None:
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
        return FigmaScreenshotResult(
            image_path=str(self.screenshot_path),
            raw_response={"figma_url": figma_url},
            source_url="file://fake",
        )


class FakeD2CClient:
    def generate_react_from_figma(self, figma_url: str, *, cache_dir=None) -> D2CResult:
        if cache_dir is not None:
            Path(cache_dir).mkdir(parents=True, exist_ok=True)
        return D2CResult(
            files={
                "src/App.tsx": "export default function App() { return <div>Original</div>; }",
            },
            entry_file="src/App.tsx",
            raw_response={"figma_url": figma_url},
        )


class FakeRunner:
    def run_json(self, node_name: str, prompt: str, node_dir: Path, *, image_path: str | None = None):
        if node_name == "analyze_screenshot":
            return {"anchors": ["顶部有标题", "下方是垂直内容区"]}
        if node_name == "reconcile_facts":
            return {"visual_anchors_reconciled": "页面由标题区和内容区组成，内容纵向排列。"}
        if node_name == "generate_responsive_react":
            return {
                "app_tsx": (
                    "export default function App() {\n"
                    "  return <main style={{display: 'flex', minHeight: '100vh'}}><section>OK</section></main>;\n"
                    "}\n"
                )
            }
        if node_name == "generate_kmp":
            return {
                "app_kt": (
                    "import androidx.compose.foundation.layout.Column\n"
                    "import androidx.compose.foundation.layout.fillMaxSize\n"
                    "import androidx.compose.runtime.Composable\n"
                    "import androidx.compose.ui.Modifier\n\n"
                    "@Composable\n"
                    "fun App() {\n"
                    "    Column(modifier = Modifier.fillMaxSize()) {}\n"
                    "}\n"
                )
            }
        raise AssertionError(f"Unexpected node {node_name}")


class FakeCommandRunner:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def __call__(self, command: str, cwd: str | Path):
        cwd_path = Path(cwd)
        self.calls.append((command, str(cwd_path)))
        if command.startswith("python scaffold_react "):
            target = Path(shlex.split(command)[2])
            (target / "src").mkdir(parents=True, exist_ok=True)
            (target / "package.json").write_text("{}", encoding="utf-8")
            return {
                "command": command,
                "cwd": str(cwd_path),
                "returncode": 0,
                "stdout": "react scaffolded\n",
                "stderr": "",
            }
        if command.startswith("git clone "):
            target = Path(shlex.split(command)[-1])
            (target / "composeApp" / "src" / "commonMain" / "kotlin").mkdir(parents=True, exist_ok=True)
            (target / "settings.gradle.kts").write_text("// shell\n", encoding="utf-8")
            return {
                "command": command,
                "cwd": str(cwd_path),
                "returncode": 0,
                "stdout": "kmp scaffolded\n",
                "stderr": "",
            }
        return {
            "command": command,
            "cwd": str(cwd_path),
            "returncode": 0,
            "stdout": "build ok\n",
            "stderr": "",
        }


def build_test_config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "models": {
                "vision": {
                    "provider": "gemini",
                    "model": "gemini-test",
                    "api_key_env": "GEMINI_API_KEY",
                },
                "text": {
                    "provider": "openai_compatible",
                    "model": "gpt-test",
                    "api_key_env": "OPENAI_API_KEY",
                    "base_url": "https://example.com/v1",
                },
            },
            "figma_mcp": {
                "command": "fake",
            },
            "d2c_mcp": {
                "command": "fake",
                "tool_name": "generate",
            },
            "scaffold": {
                "react": {
                    "command": "python scaffold_react {target}",
                },
                "kmp": {
                    "git_url": "https://example.com/kmp-shell.git",
                    "branch": "main",
                },
            },
            "build": {
                "react": {"command": f"{sys.executable} -c \"print('react ok')\""},
                "kmp": {"command": f"{sys.executable} -c \"print('kmp ok')\""},
            },
        }
    )


def test_graph_runs_end_to_end(tmp_path: Path):
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"fake")
    command_runner = FakeCommandRunner()

    workflow = PipelineWorkflow(
        build_test_config(),
        PipelineDependencies(
            figma_client=FakeFigmaClient(screenshot),
            d2c_client=FakeD2CClient(),
            text_runner=FakeRunner(),
            vision_runner=FakeRunner(),
            command_runner=command_runner,
        ),
    )
    graph = workflow.compile(InMemorySaver())
    state = default_initial_state("https://figma.example.com/file/123?node-id=1-2", str(tmp_path))
    result = graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})
    run_root = tmp_path / state["thread_id"]

    assert (run_root / "d2c" / "src" / "App.tsx").exists()
    assert (run_root / "react" / "src" / "App.tsx").exists()
    assert (run_root / "kmp" / "composeApp" / "src" / "commonMain" / "kotlin" / "App.kt").exists()
    assert (run_root / ".cache" / "figma_screenshots").exists()
    assert (run_root / ".cache" / "d2c_mcp").exists()
    assert Path(result["manifest_path"]) == run_root / "manifest.json"
    assert result["react_build_result"]["returncode"] == 0
    assert result["kmp_build_result"]["returncode"] == 0
    assert not (tmp_path / "runs").exists()
    assert not (tmp_path / "react").exists()
    assert not (tmp_path / "kmp").exists()
    assert not (tmp_path / "d2c").exists()
    assert command_runner.calls[0][0] == f"python scaffold_react {shlex.quote(str(run_root / 'react'))}"
    assert command_runner.calls[0][1] == str(tmp_path)
    assert command_runner.calls[2][0] == (
        f"git clone --branch main https://example.com/kmp-shell.git {shlex.quote(str(run_root / 'kmp'))}"
    )
    assert command_runner.calls[2][1] == str(tmp_path)
