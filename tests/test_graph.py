from __future__ import annotations

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
        return FigmaScreenshotResult(
            image_path=str(self.screenshot_path),
            raw_response={"figma_url": figma_url},
            source_url="file://fake",
        )


class FakeD2CClient:
    def generate_react_from_figma(self, figma_url: str, *, cache_dir=None) -> D2CResult:
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
            "build": {
                "react": {"command": f"{sys.executable} -c \"print('react ok')\""},
                "kmp": {"command": f"{sys.executable} -c \"print('kmp ok')\""},
            },
        }
    )


def test_graph_runs_end_to_end(tmp_path: Path):
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"fake")

    workflow = PipelineWorkflow(
        build_test_config(),
        PipelineDependencies(
            figma_client=FakeFigmaClient(screenshot),
            d2c_client=FakeD2CClient(),
            text_runner=FakeRunner(),
            vision_runner=FakeRunner(),
        ),
    )
    graph = workflow.compile(InMemorySaver())
    state = default_initial_state("https://figma.example.com/file/123?node-id=1-2", str(tmp_path))
    result = graph.invoke(state, config={"configurable": {"thread_id": state["thread_id"]}})

    assert (tmp_path / "d2c" / "src" / "App.tsx").exists()
    assert (tmp_path / "react" / "src" / "App.tsx").exists()
    assert (tmp_path / "kmp" / "composeApp" / "src" / "commonMain" / "kotlin" / "App.kt").exists()
    assert Path(result["manifest_path"]).exists()
    assert result["react_build_result"]["returncode"] == 0
    assert result["kmp_build_result"]["returncode"] == 0
