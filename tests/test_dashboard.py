from __future__ import annotations

from pathlib import Path

from d2c_graph.dashboard import list_run_summaries, load_run_detail
from d2c_graph.runtime import write_json_file, write_text_file


def test_list_run_summaries_reads_manifest(tmp_path: Path) -> None:
    run_root = tmp_path / "runs" / "thread-123"
    node_root = run_root / "nodes" / "verify_react_build"
    node_root.mkdir(parents=True)
    write_json_file(
        run_root / "manifest.json",
        {
            "thread_id": "thread-123",
            "job_id": "job-123",
            "figma_url": "https://figma.example.com/file/123",
            "workspace_root": str(tmp_path),
            "node_runs": [
                {
                    "node": "verify_react_build",
                    "status": "completed",
                    "started_at": "2026-03-14T00:00:00+00:00",
                    "finished_at": "2026-03-14T00:00:05+00:00",
                    "duration_ms": 5000,
                    "node_dir": str(node_root),
                }
            ],
        },
    )

    summaries = list_run_summaries(tmp_path)

    assert len(summaries) == 1
    assert summaries[0]["thread_id"] == "thread-123"
    assert summaries[0]["status"] == "completed"
    assert summaries[0]["duration_ms"] == 5000
    assert summaries[0]["node_total"] == 1


def test_load_run_detail_reads_node_files_without_manifest(tmp_path: Path) -> None:
    node_root = tmp_path / "runs" / "thread-456" / "nodes" / "generate_react"
    node_root.mkdir(parents=True)
    write_text_file(node_root / "prompt.txt", "prompt body")
    write_text_file(node_root / "response.txt", "response body")
    write_json_file(node_root / "failure.json", {"error": "boom"})

    detail = load_run_detail(tmp_path, "thread-456")

    assert detail is not None
    assert detail["status"] == "failed"
    assert detail["nodes"][0]["name"] == "generate_react"
    assert detail["nodes"][0]["status"] == "failed"
    assert {file["name"] for file in detail["nodes"][0]["files"]} == {
        "failure.json",
        "prompt.txt",
        "response.txt",
    }
