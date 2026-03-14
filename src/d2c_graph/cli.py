from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from d2c_graph.clients.d2c_mcp import D2CMcpClient
from d2c_graph.config import AppConfig
from d2c_graph.dashboard import serve_dashboard
from d2c_graph.graph.workflow import PipelineDependencies, PipelineWorkflow, default_initial_state
from d2c_graph.llm.factory import create_text_model, create_vision_model
from d2c_graph.llm.runner import JsonPromptRunner
from d2c_graph.runtime import ensure_directory


def main() -> None:
    parser = argparse.ArgumentParser(prog="d2c-graph")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--figma-url", required=True)
    run_parser.add_argument("--screenshot", required=True)
    run_parser.add_argument("--out", required=True)
    run_parser.add_argument("--config", default="config.yaml")

    resume_parser = subparsers.add_parser("resume")
    resume_parser.add_argument("--thread-id", required=True)
    resume_parser.add_argument("--checkpoint-id")
    resume_parser.add_argument("--out", default=".")
    resume_parser.add_argument("--config")

    dashboard_parser = subparsers.add_parser("dashboard")
    dashboard_parser.add_argument("--out", default=".")
    dashboard_parser.add_argument("--host", default="127.0.0.1")
    dashboard_parser.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()
    if args.command == "run":
        run_command(args)
        return
    if args.command == "dashboard":
        dashboard_command(args)
        return
    resume_command(args)


def run_command(args: argparse.Namespace) -> None:
    config = AppConfig.load(args.config)
    out_dir = ensure_directory(args.out)
    initial_state = default_initial_state(args.figma_url, args.screenshot, str(out_dir))
    run_root = ensure_directory(out_dir / "runs" / initial_state["thread_id"])
    shutil.copyfile(args.config, run_root / "resolved_config.yaml")

    with SqliteSaver.from_conn_string(str(out_dir / "runs" / "checkpoints.sqlite")) as checkpointer:
        graph = build_graph(config, checkpointer)
        graph.invoke(
            initial_state,
            config={"configurable": {"thread_id": initial_state["thread_id"]}},
        )


def resume_command(args: argparse.Namespace) -> None:
    out_dir = ensure_directory(args.out)
    config_path = args.config or out_dir / "runs" / args.thread_id / "resolved_config.yaml"
    config = AppConfig.load(config_path)
    configurable = {"thread_id": args.thread_id}
    if args.checkpoint_id:
        configurable["checkpoint_id"] = args.checkpoint_id

    with SqliteSaver.from_conn_string(str(out_dir / "runs" / "checkpoints.sqlite")) as checkpointer:
        graph = build_graph(config, checkpointer)
        graph.invoke({}, config={"configurable": configurable})


def dashboard_command(args: argparse.Namespace) -> None:
    out_dir = ensure_directory(args.out)
    serve_dashboard(out_dir, args.host, args.port)


def build_graph(config: AppConfig, checkpointer):
    d2c_client = D2CMcpClient(config.d2c_mcp)
    dependencies = PipelineDependencies(
        d2c_client=d2c_client,
        text_runner=JsonPromptRunner(create_text_model(config)),
        vision_runner=JsonPromptRunner(create_vision_model(config)),
    )
    workflow = PipelineWorkflow(config, dependencies)
    return workflow.compile(checkpointer)


if __name__ == "__main__":
    main()
