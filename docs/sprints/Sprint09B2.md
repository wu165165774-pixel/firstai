# Sprint 09B.2 - Prompt revision 与可审计选择

## 状态

```text
实现与验收已完成，待 commit/tag
目标版本：v0.15.0-alpha.33
基线版本：v0.15.0-alpha.32
```

## 目标与边界

本 Sprint 让内部 Prompt 选择可识别、可复核、可跨 Workflow/Memory 持久化：

```text
stable prompt_id + immutable revision
  -> server-resolved current selection
  -> rendered system/request SHA-256
  -> Agent/Planner/Workflow/Consistency/Memory metadata
  -> read-only workbench revision display
```

不增加 Prompt 数据库表，不提供在线编辑或运行中热替换，不允许客户端直接覆盖 provenance。云 Provider 新适配留给 09B.3。

## Prompt Catalog

`GET /api/v1/prompts` 返回 20 个按 `prompt_id` 排序的 descriptor：

- 8 个 Agent 各自的 system 与 fully assembled request identity。
- Consistency fact extraction 的 system/request identity。
- Memory extraction 的 system/request identity。

Registry 支持同一 ID 注册多个 revision、确定性 current revision 与显式历史 revision 解析。Catalog 不返回 Prompt content 或渲染摘要。

## Provenance 合约

每条 `prompt_provenance` 包含：

```text
prompt_id
revision
rendered_sha256
rendered_chars
```

Agent request 摘要只覆盖实际发送给 Provider 的 message role/content canonical JSON，不把内部 message metadata 当成 Prompt。结果仅保存摘要和长度，不复制 Canon、Memory、正文或用户指令。Agent 会覆盖调用方或 Provider 返回的同名字段，防止伪造审计身份。

传播路径：

- Agent request metadata -> Agent result metadata。
- Planner Agent result -> Planner candidate metadata。
- Chapter/Review/Rewrite result -> Workflow step metadata -> 既有 Workflow 持久化。
- Consistency direct request -> Analyze result metadata。
- Memory extraction direct request -> 每条新增 Memory metadata。

## 工作台

Planner candidate 显示本次 system/request 的 `prompt_id@revision`。Workflow Inspector 从所有持久 step metadata 聚合、排序并去重显示版本。界面不显示 Prompt 正文或摘要，也不能提交 revision override。

## 验证

```text
6/6 Prompt Catalog focused tests passed
18/18 Consistency tests passed
15/15 Memory Lifecycle tests passed
35/35 Planner tests passed
25/25 Chapter Workflow tests passed
7/7 Agent tests passed
6/6 Authentication tests passed
18/18 frontend tests passed
453/453 backend full regression passed in 92.618s
Python compileall passed
git diff --check passed
Frontend production image built successfully
OpenAPI version = 0.15.0-alpha.33
Prompt Catalog route registered and protected
```

真实 Qwen candidate-only 验收：

```text
novel_id = 85c4dff6-7530-459f-a3f7-1eaf34fc5c76
provider/model = qwen_local/qwen3:8b
total_tokens = 3747
latency_ms = 33015.16
finish_reason = stop
persisted = false
plan_revision_before/after = 2/2
agent.planner.system@r1 = 64-char SHA-256, 1255 rendered chars
agent.planner.request@r1 = 64-char SHA-256, 6509 rendered chars
```

## 后续

Sprint 09B.3：OpenAI、Claude、DashScope Provider 适配，并继续复用 Provider/Prompt Catalog 合约。
