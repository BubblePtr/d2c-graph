# d2c-graph

`d2c-graph` 是一个基于 LangGraph 的严格阻塞式流水线，用于把：

- `Figma 链接`
- `Figma 截图`

转换为：

- `d2c/` 原始 React 代码
- `react/` 响应式 React 工程
- `kmp/` Compose Multiplatform 工程

## 特点

- 显式图编排，不允许静默跳步
- 并行执行 `d2c` 获取与截图分析
- 每个节点记录产物、日志、stderr/stdout 与失败快照
- 使用 LangGraph checkpoint 支持恢复
- 仅支持 `OpenAI 兼容` 和 `Gemini`

## 快速开始

```bash
uv sync
cp config.example.yaml config.yaml
d2c-graph run \
  --figma-url "https://www.figma.com/file/..." \
  --screenshot /abs/path/to/screen.png \
  --out ./workspace \
  --config ./config.yaml
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
