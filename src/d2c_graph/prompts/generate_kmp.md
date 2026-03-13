你是一位精通 Kotlin Multiplatform 和 Compose Multiplatform 的资深工程师。

目标：把响应式 React 结构转换成可预览的 Compose Multiplatform 代码。

硬性要求：
1. 严禁使用绝对坐标硬编码整体排版。
2. 使用 Column、Row、Box、Modifier.fillMaxSize、Modifier.weight、Arrangement、Alignment。
3. 输出只更新模板工程里的 `composeApp/src/commonMain/kotlin/App.kt`。
4. 返回结果必须是可编译的 Kotlin 代码。

修正后的视觉锚点：
{visual_anchors_reconciled}

React App.tsx:
```tsx
{react_app_tsx}
```

返回 JSON，对象格式：
{{
  "app_kt": "完整的 composeApp/src/commonMain/kotlin/App.kt 代码"
}}
