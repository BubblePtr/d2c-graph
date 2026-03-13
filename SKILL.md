---
name: "Figma2KMP"
description: "将 Figma 设计稿转换为 KMP (Kotlin Multiplatform) 代码。Invoke when user wants to convert Figma design to KMP code."
---

# Figma2KMP

将 Figma 设计稿转换为 KMP (Kotlin Multiplatform) 代码的技能。

## 输入

1. **Figma 链接** - 用户提供的 Figma 设计稿链接
2. **Figma 截图** - 用户提供的设计稿截图

## 输出目录规范

在当前工作区创建以下目录结构：

```
当前工作区/
├── react/        # 转码后的 React 代码（可预览）
├── kmp/          # 转码后的 KMP 代码（可预览）
└── d2c/          # MCP 接收到的原始 React 代码
```

## 流程

### A. 前置准备工作

**并行执行**（使用 subagent）：

1. **获取 React 代码**：调用 `d2c-mcp-server` MCP 服务获取 Figma 链接生成的 React 代码
2. **生成视觉锚点**：使用多模态大模型识别 Figma 截图，生成视觉锚点信息

#### 生成视觉锚点的 Prompt

```
你的任务是根据提供的界面截图，生成一份**自然语言视觉锚点描述**，用于辅助后续根据 Figma 节点数据生成更合理的响应式代码。

目标不是复述界面细节，而是提炼**视觉布局关系、分组方式、阅读顺序和显著性信息**。

请严格遵守以下规则：
1. 只描述**视觉上重要的布局关系和结构意图**
2. 不要复述具体颜色、字号、像素尺寸、坐标值
3. 不要猜测业务逻辑、交互逻辑或组件实现方式
4. 优先描述相对关系，不要描述绝对位置
5. 如果某个关系不确定，就用更保守的表达，不要强行判断
6. 视觉锚点只是辅助信息，不是对 Figma 原始结构的替代
```

等待两个任务完成后，继续下一步。

### B. 生成可预览的 React 代码

1. **保存原始代码**：将 MCP 返回的 React 代码保存到 `d2c/` 目录
2. **对比与修正**：以 MCP 返回的 React 代码为可信事实，修正视觉锚点信息
3. **复制 React 模板**：将 React 模板复制到 `react/` 目录
4. **响应式优化**：将绝对布局的代码转换为适合移动端的响应式布局
5. **代码替换**：将优化后的代码替换到 `react/` 目录中
6. **编译验证**：确保 React 工程编译通过

#### 生成 React 代码的 Prompt

```
你是一位精通移动端开发的资深前端工程师，擅长使用 React + Tailwind CSS 还原高保真 UI 设计。
你需要将 Figma MCP 给出的包含绝对布局的代码，优化成适合移动端的响应式布局的代码。得到的结果应该不包含任何绝对坐标和绝对布局。

请严格遵守以下规定：
1. 布局策略 (Critical):
   严禁使用绝对布局 (`position: absolute`) 进行整体排版。
   必须使用 Flexbox (`flex`, `flex-col`, `justify-between`) 或 Grid 布局，利用 `flex: 1` 填充剩余空间，确保适配不同尺寸的移动端设备。
   容器高度应设为 `100vh` 或 `h-screen`，防止滚动溢出（除非是内容区域）。
2. 技术栈:
   React (Functional Components + Hooks)
   Tailwind CSS (用于快速响应式布局)
3. 数据处理逻辑:
   视觉锚点只作为视觉辅助信息，Figma MCP 给出的代码是真是可信的设计稿来源。
```

#### React 模板工程

使用 skill 自带的 React 模板（位于 `.trae/skills/Figma2KMP/templates/react/`），复制到 `react/` 目录后进行代码替换。

### C. 转换为 KMP 代码

1. **复制 KMP 模板**：将 KMP 模板复制到 `kmp/` 目录
2. **代码转换**：结合 React 代码和视觉锚点信息，将 React 代码转换为 KMP 代码
3. **编译验证**：确保 KMP 工程编译通过

#### 生成 KMP 代码的 Prompt

```
你是一位精通移动端开发的资深前端工程师，擅长使用 KMP 跨平台架构实现 React 代码设计。
你需要将 React 工程转换为可预览的 KMP 代码。优化成适合移动端的响应式布局的代码。得到的结果应该不包含任何绝对坐标和绝对布局。

请严格遵守以下规定：
1. 布局策略 (Critical):
   严禁使用绝对坐标硬编码 (Hardcoded Coordinates) 进行整体排版。
   必须使用 Compose 标准布局容器 ( Column , Row , Box )。
   使用 Modifier.weight(1f) 来分配剩余空间 (对应 Flexbox 的 flex: 1 )，确保 UI 在不同屏幕尺寸下的自适应性。
   使用 Arrangement (如 Arrangement.SpaceBetween , Arrangement.spacedBy() ) 和 Alignment 控制子元素的位置与间距。
   根容器应使用 Modifier.fillMaxSize() 撑满屏幕，避免非预期的留白或滚动。
2. 技术栈:
   KMP (Kotlin Multiplatform)
   Compose Multiplatform (UI Framework)
3. 数据处理逻辑:
   视觉锚点只作为视觉辅助信息，Figma MCP 给出的代码是真是可信的设计稿来源。
```

#### KMP 模板工程

使用 skill 自带的 KMP 模板（位于 `.trae/skills/Figma2KMP/templates/kmp/`），复制到 `kmp/` 目录后进行代码替换。

## 注意事项

- 视觉锚点仅作为辅助信息，MCP 返回的代码是可信事实
- 所有代码必须保证响应式布局，不能包含绝对坐标
- React 和 KMP 工程都需要编译通过
