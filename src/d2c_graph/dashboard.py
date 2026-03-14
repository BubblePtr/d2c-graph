from __future__ import annotations

import json
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from d2c_graph.runtime import ensure_directory

MAX_FILE_CONTENT_CHARS = 50_000


def list_run_summaries(out_dir: str | Path) -> list[dict[str, Any]]:
    run_roots = _list_run_roots(out_dir)
    if not run_roots:
        return []

    summaries: list[dict[str, Any]] = []
    for run_root in run_roots:
        manifest = _read_json_file(run_root / "manifest.json")
        node_records = _collect_node_records(run_root, manifest)
        cache_summary = _load_cache_summary(run_root)
        summaries.append(
            {
                "thread_id": str(manifest.get("thread_id") or run_root.name),
                "job_id": manifest.get("job_id"),
                "figma_url": manifest.get("figma_url"),
                "workspace_root": manifest.get("workspace_root"),
                "status": _derive_run_status(manifest, node_records),
                "started_at": _first_timestamp(node_records, "started_at"),
                "finished_at": _last_timestamp(node_records, "finished_at"),
                "duration_ms": sum(
                    int(record.get("duration_ms", 0))
                    for record in node_records
                    if isinstance(record.get("duration_ms"), int)
                ),
                "node_total": len(node_records),
                "node_failed": sum(1 for record in node_records if record.get("status") == "failed"),
                "run_root": str(run_root),
                "updated_at": _to_iso(_path_mtime(run_root)),
                "cache": cache_summary,
            }
        )
    return summaries


def load_run_detail(out_dir: str | Path, thread_id: str) -> dict[str, Any] | None:
    run_root = _resolve_run_root(out_dir, thread_id)
    if not run_root.exists() or not run_root.is_dir():
        return None

    manifest = _read_json_file(run_root / "manifest.json")
    node_records = _collect_node_records(run_root, manifest)
    cache_summary = _load_cache_summary(run_root)
    record_by_name = {str(record.get("node")): record for record in node_records if record.get("node")}
    nodes: list[dict[str, Any]] = []
    nodes_root = run_root / "nodes"
    if nodes_root.exists():
        for node_dir in sorted(nodes_root.iterdir(), key=lambda item: item.name):
            if not node_dir.is_dir():
                continue
            node_record = record_by_name.get(node_dir.name, {})
            files = []
            for file_path in sorted(node_dir.iterdir(), key=lambda item: item.name):
                if not file_path.is_file():
                    continue
                files.append(_read_node_file(file_path))
            nodes.append(
                {
                    "name": node_dir.name,
                    "path": str(node_dir),
                    "status": str(node_record.get("status") or _derive_node_status(node_dir)),
                    "started_at": node_record.get("started_at"),
                    "finished_at": node_record.get("finished_at"),
                    "duration_ms": node_record.get("duration_ms"),
                    "error": node_record.get("error"),
                    "files": files,
                }
            )

    return {
        "thread_id": thread_id,
        "run_root": str(run_root),
        "manifest": manifest,
        "status": _derive_run_status(manifest, node_records),
        "cache": cache_summary,
        "nodes": nodes,
    }


def serve_dashboard(out_dir: str | Path, host: str, port: int) -> None:
    dashboard_root = ensure_directory(out_dir)
    handler_class = _build_handler(dashboard_root)
    with ThreadingHTTPServer((host, port), handler_class) as server:
        print(f"d2c-graph dashboard: http://{host}:{port}")
        server.serve_forever()


def _build_handler(out_dir: Path):
    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "d2c-graph-dashboard/0.1"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(INDEX_HTML)
                return
            if parsed.path == "/api/runs":
                self._send_json({"runs": list_run_summaries(out_dir)})
                return
            if parsed.path.startswith("/api/runs/"):
                thread_id = parsed.path.removeprefix("/api/runs/").strip("/")
                if not thread_id:
                    self._send_not_found()
                    return
                payload = load_run_detail(out_dir, thread_id)
                if payload is None:
                    self._send_not_found()
                    return
                self._send_json(payload)
                return
            self._send_not_found()

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_html(self, content: str) -> None:
            encoded = content.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_json(self, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_not_found(self) -> None:
            encoded = json.dumps({"error": "not found"}).encode("utf-8")
            self.send_response(HTTPStatus.NOT_FOUND)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return DashboardHandler


def _list_run_roots(out_dir: str | Path) -> list[Path]:
    workspace_root = Path(out_dir)
    if not workspace_root.exists():
        return []

    run_roots: dict[str, Path] = {}
    for child in workspace_root.iterdir():
        if child.name.startswith(".") or not child.is_dir() or child.name == "runs":
            continue
        if (child / "manifest.json").exists() or (child / "nodes").exists():
            run_roots[child.name] = child

    legacy_runs_root = workspace_root / "runs"
    if legacy_runs_root.exists():
        for child in legacy_runs_root.iterdir():
            if child.is_dir() and child.name not in run_roots:
                run_roots[child.name] = child

    return sorted(run_roots.values(), key=_path_mtime, reverse=True)


def _resolve_run_root(out_dir: str | Path, thread_id: str) -> Path:
    workspace_root = Path(out_dir)
    direct = workspace_root / thread_id
    if direct.exists():
        return direct
    return workspace_root / "runs" / thread_id


def _collect_node_records(run_root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    manifest_records = manifest.get("node_runs")
    if isinstance(manifest_records, list):
        return [record for record in manifest_records if isinstance(record, dict)]

    records: list[dict[str, Any]] = []
    nodes_root = run_root / "nodes"
    if not nodes_root.exists():
        return records
    for node_dir in sorted(nodes_root.iterdir(), key=lambda item: item.name):
        if not node_dir.is_dir():
            continue
        record: dict[str, Any] = {
            "node": node_dir.name,
            "status": _derive_node_status(node_dir),
        }
        output = _read_json_file(node_dir / "state_output.json")
        failure = _read_json_file(node_dir / "failure.json")
        if output:
            record["finished_at"] = _to_iso(_path_mtime(node_dir / "state_output.json"))
        if failure:
            record["error"] = failure.get("error")
            record["finished_at"] = _to_iso(_path_mtime(node_dir / "failure.json"))
        records.append(record)
    return records


def _derive_run_status(manifest: dict[str, Any], node_records: list[dict[str, Any]]) -> str:
    if any(record.get("status") == "failed" for record in node_records):
        return "failed"
    if manifest:
        return "completed"
    if node_records:
        return "running"
    return "pending"


def _derive_node_status(node_dir: Path) -> str:
    if (node_dir / "failure.json").exists() or (node_dir / "error.txt").exists():
        return "failed"
    if (node_dir / "state_output.json").exists():
        return "completed"
    return "running"


def _load_cache_summary(run_root: Path) -> dict[str, dict[str, Any]]:
    return {
        "figma_screenshot": _read_json_file(run_root / "nodes" / "fetch_figma_screenshot" / "screenshot_summary.json"),
        "d2c": _read_json_file(run_root / "nodes" / "fetch_d2c_react" / "d2c_summary.json"),
    }


def _read_node_file(file_path: Path) -> dict[str, Any]:
    suffix = file_path.suffix.lower()
    if suffix == ".json":
        return {
            "name": file_path.name,
            "kind": "json",
            "size": file_path.stat().st_size,
            "content": _read_json_file(file_path),
        }

    text = file_path.read_text(encoding="utf-8", errors="replace")
    truncated = False
    if len(text) > MAX_FILE_CONTENT_CHARS:
        text = text[:MAX_FILE_CONTENT_CHARS] + "\n...<truncated>"
        truncated = True
    return {
        "name": file_path.name,
        "kind": "text",
        "size": file_path.stat().st_size,
        "content": text,
        "truncated": truncated,
    }


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _first_timestamp(records: list[dict[str, Any]], key: str) -> str | None:
    timestamps = [record.get(key) for record in records if isinstance(record.get(key), str)]
    return min(timestamps) if timestamps else None


def _last_timestamp(records: list[dict[str, Any]], key: str) -> str | None:
    timestamps = [record.get(key) for record in records if isinstance(record.get(key), str)]
    return max(timestamps) if timestamps else None


def _path_mtime(path: Path) -> float:
    return path.stat().st_mtime


def _to_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>d2c-graph dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --muted: #5c6773;
      --text: #102033;
      --border: #d8e0e8;
      --accent: #0f766e;
      --failed: #b42318;
      --running: #7a5af8;
      --completed: #087443;
      --shadow: 0 10px 30px rgba(16, 32, 51, 0.08);
      --mono: "SFMono-Regular", "SF Mono", Menlo, Consolas, monospace;
      --sans: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Palatino, Georgia, serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: linear-gradient(180deg, #eef4f7 0%, var(--bg) 55%);
      color: var(--text);
      font-family: var(--sans);
    }
    .shell {
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
      min-height: 100vh;
    }
    .sidebar {
      border-right: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.9);
      backdrop-filter: blur(10px);
      padding: 20px;
      overflow: auto;
    }
    .content {
      padding: 24px;
      overflow: auto;
    }
    h1, h2, h3 {
      margin: 0;
      font-weight: 600;
    }
    h1 { font-size: 24px; }
    h2 { font-size: 22px; margin-bottom: 8px; }
    h3 { font-size: 16px; }
    .muted { color: var(--muted); }
    .stack { display: grid; gap: 16px; }
    .run-item, .card, details {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 16px;
      box-shadow: var(--shadow);
    }
    .run-item {
      padding: 14px;
      cursor: pointer;
      transition: transform 0.12s ease, border-color 0.12s ease;
    }
    .run-item:hover { transform: translateY(-1px); border-color: #adc2d6; }
    .run-item.active { border-color: var(--accent); }
    .card { padding: 18px; }
    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 10px 14px;
      margin-top: 10px;
      font-size: 14px;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 3px 10px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      border: 1px solid currentColor;
    }
    .badge.completed { color: var(--completed); }
    .badge.failed { color: var(--failed); }
    .badge.running, .badge.pending { color: var(--running); }
    .grid {
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    }
    details { padding: 14px 16px; }
    summary {
      cursor: pointer;
      font-weight: 600;
      list-style: none;
    }
    summary::-webkit-details-marker { display: none; }
    pre {
      margin: 12px 0 0;
      padding: 14px;
      border-radius: 12px;
      background: #0f172a;
      color: #d6e2ff;
      overflow: auto;
      font-family: var(--mono);
      font-size: 12px;
      line-height: 1.45;
    }
    code { font-family: var(--mono); }
    .empty {
      display: grid;
      place-items: center;
      min-height: 60vh;
      text-align: center;
    }
    .row {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
    }
    .node-header {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
      margin-bottom: 12px;
    }
    .node-files {
      display: grid;
      gap: 12px;
    }
    @media (max-width: 960px) {
      .shell { grid-template-columns: 1fr; }
      .sidebar { border-right: 0; border-bottom: 1px solid var(--border); }
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside class="sidebar">
      <div class="stack">
        <div>
          <h1>d2c-graph</h1>
          <div class="muted">runs observability dashboard</div>
        </div>
        <div id="run-list" class="stack"></div>
      </div>
    </aside>
    <main class="content">
      <div id="content" class="empty muted">No runs found under the selected output directory.</div>
    </main>
  </div>
  <script>
    const state = { runs: [], selectedThreadId: null };

    const fmt = (value) => value ? new Date(value).toLocaleString() : "n/a";
    const fmtDuration = (ms) => Number.isFinite(ms) ? `${ms} ms` : "n/a";

    function badge(status) {
      const value = status || "pending";
      return `<span class="badge ${value}">${value}</span>`;
    }

    function cacheBadge(label, summary) {
      if (!summary || Object.keys(summary).length === 0) {
        return `<span>${label}: n/a</span>`;
      }
      return `<span>${label}: ${summary.cache_hit ? "hit" : "miss"}</span>`;
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
    }

    async function fetchJson(path) {
      const response = await fetch(path, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
      }
      return response.json();
    }

    function renderRunList() {
      const host = document.getElementById("run-list");
      if (!state.runs.length) {
        host.innerHTML = '<div class="muted">No runs yet.</div>';
        return;
      }
      host.innerHTML = state.runs.map((run) => `
        <div class="run-item ${run.thread_id === state.selectedThreadId ? "active" : ""}" data-thread-id="${run.thread_id}">
          <div class="row">
            <strong>${escapeHtml(run.thread_id)}</strong>
            ${badge(run.status)}
          </div>
          <div class="meta">
            <span>${run.node_total} nodes</span>
            <span>${fmtDuration(run.duration_ms)}</span>
          </div>
          <div class="meta muted">
            ${cacheBadge("IMG cache", run.cache?.figma_screenshot)}
            ${cacheBadge("D2C cache", run.cache?.d2c)}
          </div>
          <div class="meta muted">
            <span>${fmt(run.updated_at)}</span>
          </div>
        </div>
      `).join("");

      host.querySelectorAll("[data-thread-id]").forEach((node) => {
        node.addEventListener("click", () => {
          const threadId = node.getAttribute("data-thread-id");
          if (!threadId) {
            return;
          }
          state.selectedThreadId = threadId;
          location.hash = threadId;
          renderRunList();
          loadDetail(threadId);
        });
      });
    }

    function renderDetail(payload) {
      const manifest = payload.manifest || {};
      const cache = payload.cache || {};
      const host = document.getElementById("content");
      host.className = "stack";
      host.innerHTML = `
        <section class="card">
          <div class="row">
            <div>
              <h2>${escapeHtml(payload.thread_id)}</h2>
              <div class="muted">${escapeHtml(manifest.figma_url || "No figma_url captured")}</div>
            </div>
            ${badge(payload.status)}
          </div>
          <div class="grid" style="margin-top: 18px;">
            <div class="card">
              <h3>Workspace</h3>
              <div class="muted"><code>${escapeHtml(manifest.workspace_root || payload.run_root)}</code></div>
            </div>
            <div class="card">
              <h3>Models</h3>
              <div class="muted"><code>${escapeHtml(JSON.stringify(manifest.model_plan || {}, null, 2))}</code></div>
            </div>
            <div class="card">
              <h3>Artifacts</h3>
              <div class="muted">${Object.keys(manifest.react_artifacts || {}).length} react, ${Object.keys(manifest.kmp_artifacts || {}).length} kmp</div>
            </div>
            <div class="card">
              <h3>Cache</h3>
              <div class="muted">${cacheBadge("IMG cache", cache.figma_screenshot)}</div>
              <div class="muted">${cacheBadge("D2C cache", cache.d2c)}</div>
            </div>
          </div>
        </section>
        <section class="grid">
          <div class="card">
            <h3>Figma Screenshot Cache</h3>
            <div class="muted"><code>${escapeHtml(cache.figma_screenshot?.screenshot_path || "n/a")}</code></div>
            <div class="meta muted">
              <span>${cacheBadge("Status", cache.figma_screenshot)}</span>
              <span><code>${escapeHtml(cache.figma_screenshot?.cache_dir || "n/a")}</code></span>
            </div>
          </div>
          <div class="card">
            <h3>D2C Cache</h3>
            <div class="muted"><code>${escapeHtml(cache.d2c?.cache_dir || "n/a")}</code></div>
            <div class="meta muted">
              <span>${cacheBadge("Status", cache.d2c)}</span>
              <span>${Array.isArray(cache.d2c?.files) ? cache.d2c.files.length : 0} files</span>
            </div>
          </div>
        </section>
        <section class="stack">
          ${payload.nodes.map((node) => `
            <article class="card">
              <div class="node-header">
                <div>
                  <h3>${escapeHtml(node.name)}</h3>
                  <div class="meta muted">
                    <span>${fmt(node.started_at)}</span>
                    <span>${fmtDuration(node.duration_ms)}</span>
                    <span><code>${escapeHtml(node.path)}</code></span>
                  </div>
                </div>
                ${badge(node.status)}
              </div>
              ${node.error ? `<div class="muted">error: ${escapeHtml(node.error)}</div>` : ""}
              <div class="node-files">
                ${node.files.map((file) => `
                  <details>
                    <summary>${escapeHtml(file.name)} <span class="muted">(${file.kind}, ${file.size} bytes${file.truncated ? ", truncated" : ""})</span></summary>
                    <pre>${escapeHtml(file.kind === "json" ? JSON.stringify(file.content, null, 2) : file.content)}</pre>
                  </details>
                `).join("")}
              </div>
            </article>
          `).join("") || '<div class="card muted">No node data found for this run.</div>'}
        </section>
      `;
    }

    async function loadRuns() {
      const payload = await fetchJson("/api/runs");
      state.runs = payload.runs || [];
      const preferred = location.hash.replace(/^#/, "");
      if (preferred && state.runs.some((run) => run.thread_id === preferred)) {
        state.selectedThreadId = preferred;
      } else if (!state.selectedThreadId && state.runs.length) {
        state.selectedThreadId = state.runs[0].thread_id;
      } else if (state.selectedThreadId && !state.runs.some((run) => run.thread_id === state.selectedThreadId)) {
        state.selectedThreadId = state.runs[0]?.thread_id || null;
      }
      renderRunList();
      if (state.selectedThreadId) {
        await loadDetail(state.selectedThreadId);
      }
    }

    async function loadDetail(threadId) {
      if (!threadId) {
        return;
      }
      const payload = await fetchJson(`/api/runs/${encodeURIComponent(threadId)}`);
      renderDetail(payload);
    }

    loadRuns().catch((error) => {
      const host = document.getElementById("content");
      host.className = "empty";
      host.innerHTML = `<div><h2>Dashboard failed to load</h2><div class="muted">${escapeHtml(error.message)}</div></div>`;
    });
    setInterval(() => {
      loadRuns().catch(() => {});
    }, 5000);
  </script>
</body>
</html>
"""
