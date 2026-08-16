# Sprint 09B.3 - OpenAI / Claude / DashScope Provider 适配

## 状态

```text
实现与验收已完成，待 commit/tag
目标版本：v0.15.0-alpha.34
基线版本：v0.15.0-alpha.33
```

## 目标与边界

本 Sprint 在 09B.1 Provider Catalog 与 09B.2 Prompt provenance 之上增加三种可选云 Provider：

```text
业务 Agent / Planner / Workflow
  -> LLMManager + ChatRequest
  -> Provider Registry
     ├── openai    -> OpenAI Chat Completions
     ├── claude    -> Anthropic Messages API
     └── dashscope -> Model Studio OpenAI-compatible API
```

不修改 Agent、Planner、Workflow 或 Prompt Catalog 合约，不持久化 key，不在 API、验收文件或日志记录 endpoint/key。没有配置 key 时 Provider 仍保持已注册，但明确报告 `configured=false`，并且探测不会实例化 SDK client。

## 适配行为

### OpenAI

- 使用异步 OpenAI SDK Chat Completions，与现有 message-based 业务合约兼容。
- `max_tokens` 映射为现代模型使用的 `max_completion_tokens`。
- `low/medium/high` 映射为 OpenAI `reasoning_effort`；启用 reasoning 时不发送可能与 reasoning model 冲突的 temperature。
- 普通及流式响应统一为 NovelForge `ChatResponse`/文本 chunk，并归一化 token usage。

### Claude

- 使用官方 `AsyncAnthropic` Messages SDK。
- system/developer message 合并到 Anthropic `system`；user/assistant message 保持顺序，相邻同 role 内容确定性合并。
- 当前业务 `ChatMessage` 没有完整 Anthropic tool-use content block，因此拒绝把普通文本 `tool` message 伪装为工具结果。
- 当前不启用 extended thinking；Catalog 只声明 `none`，响应 metadata 明确记录 requested/applied reasoning，不虚报能力。

### DashScope

- 使用阿里云百炼官方支持的 OpenAI-compatible endpoint，复用 OpenAI SDK，无需引入第二套 DashScope SDK。
- `max_tokens` 保持兼容字段；reasoning 非 `none` 时映射为 `extra_body.enable_thinking=true`。
- Catalog 只声明 `none/medium`，用 `medium` 表示布尔 thinking 模式，不把布尔开关虚报为精细推理档位。

## 配置与健康探测

`backend/.env.example` 新增空 key 示例：

- `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`
- `CLAUDE_API_KEY` / `CLAUDE_BASE_URL` / `CLAUDE_MODEL` / `CLAUDE_MAX_TOKENS`
- `DASHSCOPE_API_KEY` / `DASHSCOPE_BASE_URL` / `DASHSCOPE_MODEL`

健康检查只调用各厂商 Models API，不产生文本生成费用；仍由 09B.1 的并行 timeout 和稳定错误码统一收敛。运行环境未配置这三种新增云 key，因此本次验收只证明适配合约、配置门禁与 Catalog 状态，不宣称三家付费 API 在线生成通过。

## 官方接口依据

- OpenAI 当前模型同时支持 Chat Completions、Responses 与 streaming；本 Sprint 为复用现有 message contract 选择 Chat Completions。
- Anthropic 官方 Python SDK支持异步 Messages、SSE streaming 与 Models API。
- Alibaba Cloud Model Studio 官方文档明确支持 OpenAI Python SDK、OpenAI-compatible Chat Completions 与 SSE streaming。

## 验证

```text
14/14 Provider focused tests passed
4/4 Qwen reasoning tests passed
7/7 Agent tests passed
35/35 Planner tests passed
18/18 frontend tests passed
460/460 backend full regression passed in 111.535s
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
Backend image with anthropic SDK built successfully
```

运行时 Catalog：

```text
claude: configured=false, available=false, not_configured
dashscope: configured=false, available=false, not_configured
openai: configured=false, available=false, not_configured
deepseek: configured=true, available=false, health_check_failed
qwen_local: configured=true, available=true
```

DeepSeek 仍只证明已配置与当前不可达状态可以区分；新增三家没有 key，因此没有发起生成调用。已有业务/验收数据未删除。

## 后续

Sprint 09C：多 SQLite/FAISS/Temporal Graph 一致快照、恢复演练、schema migration 与小说导出。
