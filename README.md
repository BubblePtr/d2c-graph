# d2c-graph

`d2c-graph` 是一个基于 LangGraph 的严格阻塞式流水线，用于把：

- `Figma 链接`

转换为：

- `workspace/<thread_id>/d2c/` 原始 React 代码
- `workspace/<thread_id>/react/` 响应式 React 工程
- `workspace/<thread_id>/kmp/` Compose Multiplatform 工程

## 特点

- 显式图编排，不允许静默跳步
- 并行执行 `d2c` 获取与 Figma 截图拉取
- 自动缓存 Figma 截图与 d2c MCP 返回结果
- `figma_mcp` 支持官方推荐的 `HTTP /mcp` 格式
- `d2c_mcp` 支持本地 `stdio` 和远程 `SSE URL`
- 每个节点记录产物、日志、stderr/stdout 与失败快照
- 使用 LangGraph checkpoint 支持恢复
- 仅支持 `OpenAI 兼容` 和 `Gemini`

## 快速开始

```bash
uv sync
cp config.example.yaml config.yaml
d2c-graph run \
  --figma-url "https://www.figma.com/design/...?...node-id=1-2" \
  --out ./workspace \
  --config ./config.yaml
```

`figma-url` 需要包含具体节点的 `node-id`，用于截图拉取与缓存键计算。
`--out` 是固定的 workspace 根目录，每次运行会在其下创建一个新的 `<thread_id>/` 子目录，并将该次运行的缓存、日志、d2c、React、KMP 产物都写入该目录。

MCP 配置同时支持两种方式：

```yaml
# 官方 Figma MCP
figma_mcp:
  type: http
  url: https://mcp.figma.com/mcp
  tool_name: get_screenshot

# 自部署 d2c MCP: stdio
d2c_mcp:
  command: d2c-mcp-server
  args: []
  tool_name: generate_react_from_figma

# 自部署 d2c MCP: sse
d2c_mcp:
  transport: sse
  url: https://example.com/d2c/sse
  tool_name: generate_react_from_figma

scaffold:
  react:
    command: npm create vite@latest {target} -- --template react-ts
  kmp:
    git_url: https://example.com/kmp-shell.git
    # branch: main
```

恢复执行：

```bash
d2c-graph resume --thread-id <thread-id> --out ./workspace
```

查看运行日志与节点状态：

```bash
d2c-graph dashboard --out ./workspace --host 127.0.0.1 --port 8000
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000) 后可以看到：

- 运行列表与整体状态
- 每个节点的耗时、状态与错误
- LLM 节点的 `prompt.txt` / `response.txt` / `response.json`
- 构建节点的 `build.json`，包含 `stdout` / `stderr`
- 每次 run 的完整目录，如 `workspace/<thread_id>/react`
