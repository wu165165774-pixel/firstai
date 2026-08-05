# Sprint 07C.1：请求级 Qwen Thinking 控制

## 1. Sprint 信息

* 项目：NovelForge
* Sprint：07C.1
* 状态：Completed
* 完成日期：2026-08-05
* 发布版本：v0.14.0-alpha.3
* 前置版本：v0.14.0-alpha.2

## 2. 背景

在 Sprint 07B.1 中，为解决 Qwen3 Thinking 模式消耗全部输出 Token、导致最终正文为空的问题，Qwen Local Provider 曾全局写死：

```python
extra_body={
    "reasoning_effort": "none",
}
```

该配置适合快速创作，但会导致所有任务都无法启用 Thinking，包括未来的复杂剧情推演、章节审查和多 Agent 规划。

本 Sprint 将 Thinking 控制从 Provider 全局配置改为请求级参数。

## 3. Sprint 目标

* 请求可以独立选择 Thinking 强度
* 默认行为保持 `none`
* 兼容现有 Chat API
* 兼容现有 Agent API
* 普通调用与流式调用行为一致
* Agent 可以把 Thinking 设置传递给 LLM
* 返回结果记录实际 Thinking 配置
* 非法配置由 Pydantic 自动拒绝
* 修复 Qwen Provider 中已有参数问题

## 4. ReasoningEffort

新增统一类型：

```python
ReasoningEffort = Literal[
    "none",
    "low",
    "medium",
    "high",
]
```

支持级别：

### none

关闭 Thinking。

适合：

* 快速聊天
* 普通续写
* 文本改写
* 简单创作
* 实时交互

### low

启用少量推理。

适合：

* 简单剧情分析
* 小范围人物关系推演
* 简单章节规划

### medium

启用中等强度推理。

适合：

* 章节大纲规划
* 多人物关系分析
* 一致性审查
* 伏笔与因果分析

### high

启用高强度推理。

适合：

* 复杂时间线分析
* 多章节一致性检查
* 长篇剧情结构推演
* 多 Agent Planner

## 5. ChatRequest

`ChatRequest` 新增：

```python
reasoning_effort: ReasoningEffort = "none"
```

旧请求不提供该字段时，默认关闭 Thinking，因此现有调用保持兼容。

Chat API 可以直接接收：

```json
{
  "reasoning_effort": "medium"
}
```

## 6. AgentContext

`AgentContext` 新增：

```python
reasoning_effort: ReasoningEffort = "none"
```

Agent API 可以直接接收：

```json
{
  "task_mode": "creative",
  "reasoning_effort": "medium"
}
```

Grounded 模式不会调用 LLM，因此该字段在 Grounded 模式下不会产生额外推理开销。

## 7. NovelAgent 参数传递

NovelAgent 构造 `ChatRequest` 时会传递：

```python
reasoning_effort=context.reasoning_effort
```

调用链：

```text
Agent API
    ↓
AgentContext.reasoning_effort
    ↓
NovelAgent
    ↓
ChatRequest.reasoning_effort
    ↓
LLMManager
    ↓
QwenLocalProvider
    ↓
Ollama OpenAI-Compatible API
```

## 8. Qwen Local Provider

Qwen Local Provider 不再写死：

```python
"reasoning_effort": "none"
```

改为：

```python
extra_body={
    "reasoning_effort": request.reasoning_effort,
}
```

普通请求和流式请求均支持动态 Reasoning。

## 9. Provider 参数修复

### 9.1 Temperature 0.0

原实现：

```python
temperature=request.temperature or 0.7
```

当调用方传入：

```text
0.0
```

时，会被错误替换为：

```text
0.7
```

现已改为显式判断 `None`，因此 `0.0` 可以正确传递。

### 9.2 Stream 参数

流式接口现已统一支持：

* `reasoning_effort`
* `temperature`
* `max_tokens`
* `model`

### 9.3 空正文保护

Provider 对模型返回的：

```python
message.content is None
```

进行保护，统一转换为空字符串，避免返回模型校验异常。

### 9.4 Prompt 日志

移除了向终端直接打印完整 Prompt 的调试代码，防止：

* 日志污染
* 小说内容泄露
* 长 Prompt 占用大量日志空间
* 中文终端乱码

## 10. 返回 Metadata

Qwen Provider 返回以下 Metadata：

```json
{
  "reasoning_effort": "medium",
  "thinking_enabled": true
}
```

当配置为 `none` 时：

```json
{
  "reasoning_effort": "none",
  "thinking_enabled": false
}
```

专业 Agent 的 Creative 模式会同时包含：

```json
{
  "task_mode": "creative",
  "llm_called": true,
  "grounding_enforced": false,
  "reasoning_effort": "medium",
  "thinking_enabled": true
}
```

## 11. OpenAPI

`ChatRequest` 和 `AgentContext` 均公开以下枚举：

```text
none
low
medium
high
```

默认值：

```text
none
```

非法值，例如：

```json
{
  "reasoning_effort": "extreme"
}
```

返回：

```text
HTTP 422
```

## 12. 自动化测试

新增测试：

* 默认 Reasoning 为 `none`
* `high` 可以正确传递
* `temperature=0.0` 可以正确传递
* `max_tokens` 可以正确传递
* 流式调用传递 Reasoning 参数
* NovelAgent 传递 Reasoning 参数

测试结果：

```text
新增测试：4
原有测试：30
总计：34
```

全量结果：

```text
Ran 34 tests
OK
```

## 13. 端到端验证

已验证：

* `reasoning_effort=none`
* `reasoning_effort=medium`
* 相同任务可以动态切换 Thinking
* Metadata 返回实际配置
* Thinking Enabled 状态正确
* 非法值返回 HTTP 422
* Grounded 模式行为未改变
* Creative 模式正常生成正文

## 14. 当前推荐策略

| 任务类型              | 推荐配置          |
| ----------------- | ------------- |
| Grounded 事实回答     | 不调用 LLM       |
| 快速聊天              | none          |
| 普通小说续写            | none          |
| RewriteAgent      | none          |
| ChapterAgent 普通写作 | none 或 low    |
| ChapterAgent 大纲规划 | medium        |
| ReviewAgent       | medium        |
| 复杂剧情推演            | high          |
| 多 Agent Planner   | medium 或 high |

## 15. 验收结论

Sprint 07C.1 已完成：

* 请求级 Qwen Thinking
* ChatRequest 参数支持
* AgentContext 参数支持
* NovelAgent 参数传递
* 普通与流式 Provider 支持
* Temperature 0.0 修复
* Provider Metadata
* OpenAPI 枚举
* 非法值校验
* 34 条自动化测试通过

Sprint 状态：

```text
Completed
```
