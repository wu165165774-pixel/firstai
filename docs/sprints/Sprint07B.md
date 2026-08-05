# Sprint 07B：Agent API 与专业 Agent

## 1. Sprint 信息

* 项目：NovelForge
* Sprint：07B
* 模块：Agent API 与专业 Agent
* 状态：Completed
* 完成日期：2026-08-05
* 开发分支：master
* 发布版本：v0.14.0-alpha.1
* 前置 Sprint：Sprint 07A

## 2. Sprint 目标

将 Sprint 07A 完成的 NovelAgent Core Framework 接入 FastAPI，并实现第一批专业小说 Agent。

本 Sprint 建立统一的 Agent 注册、管理和 HTTP 执行入口，使前端或其他服务可以根据具体任务选择不同 Agent。

## 3. 已实现专业 Agent

### 3.1 NovelAgent

Agent 名称：

```text
novel
```

职责：

* 通用小说任务
* 长期记忆召回
* 小说设定分析
* 文本创作
* 内容修改
* LLM 请求构造

### 3.2 CharacterAgent

Agent 名称：

```text
character
```

职责：

* 人物档案创建
* 人物性格分析
* 人物关系分析
* 人物成长轨迹设计
* 人物行为一致性检查
* 人物语言和行为风格设计

执行时优先使用人物长期记忆，不得擅自改变已经确认的人物设定。

### 3.3 WorldAgent

Agent 名称：

```text
world
```

职责：

* 世界观构建
* 地点和势力设计
* 历史、制度和文化设计
* 力量体系维护
* 世界规则一致性检查
* 新设定影响分析

执行时不得为了推动剧情临时创造违反已有世界规则的能力或制度。

### 3.4 PlotAgent

Agent 名称：

```text
plot
```

职责：

* 主线和支线规划
* 剧情因果分析
* 冲突与转折设计
* 伏笔安排和回收
* 时间线检查
* 剧情漏洞检查
* 人物和世界设定一致性检查

新剧情建议不会被描述成已经发生的剧情事实。

## 4. Agent Bootstrap

建立统一的全局 Agent 初始化流程：

```text
ProviderRegistry
    ↓
LLMManager
    ↓
AgentRegistry
    ↓
AgentManager
    ├── NovelAgent
    ├── CharacterAgent
    ├── WorldAgent
    └── PlotAgent
```

当前全局实例：

```python
provider_registry
llm_manager
agent_registry
agent_manager
```

同时保留原有 `registry` 名称，兼容现有 Chat API 和 Provider API。

## 5. Agent API

### 5.1 获取 Agent 列表

```http
GET /api/v1/agents
```

返回当前已经注册的 Agent 名称和功能说明。

当前返回：

```text
character
novel
plot
world
```

### 5.2 执行指定 Agent

```http
POST /api/v1/agents/{agent_name}/execute
```

请求字段：

* `user_id`
* `novel_id`
* `instruction`
* `provider`
* `model`
* `messages`
* `use_memory`
* `temperature`
* `max_tokens`
* `metadata`

返回统一 `AgentResult`：

* `agent`
* `success`
* `content`
* `provider`
* `model`
* `finish_reason`
* `usage`
* `latency_ms`
* `metadata`

### 5.3 不存在的 Agent

请求不存在的 Agent 时返回：

```text
HTTP 404
```

## 6. 长期记忆集成

所有专业 Agent 继承 NovelAgent 的执行流程，因此默认支持长期记忆。

调用链：

```text
Agent API
    ↓
AgentManager
    ↓
专业 Agent
    ↓
MemoryContextBuilder
    ↓
HybridMemoryRetriever
    ├── Qwen Embedding
    ├── FAISS 语义召回
    └── SQLite 记忆读取
    ↓
LLMManager
    ↓
Qwen Local
```

可以通过以下字段关闭记忆召回：

```json
{
  "use_memory": false
}
```

## 7. OpenAPI 路由

Sprint 07B 新增：

```text
GET  /api/v1/agents
POST /api/v1/agents/{agent_name}/execute
```

FastAPI OpenAPI 版本更新为：

```text
0.14.0-alpha.1
```

## 8. 自动化测试

Agent 测试总数：

```text
16
```

覆盖：

* Agent Core
* Agent Registry
* Agent Manager
* NovelAgent
* CharacterAgent
* WorldAgent
* PlotAgent
* 专业 Agent 注册
* Agent 列表 API
* Agent 执行 API
* 不存在 Agent 的 404 处理
* 长期记忆注入
* 禁用长期记忆
* 中文提示词完整性

Memory/RAG 回归测试：

```text
8
```

全量测试结果：

```text
Ran 24 tests
OK
```

## 9. 端到端验证

已验证：

* Backend 启动成功
* Memory Index 一致性检查成功
* Agent 列表 API 正常
* CharacterAgent 调用本地 Qwen 成功
* WorldAgent 调用本地 Qwen 成功
* PlotAgent 调用本地 Qwen 成功
* 长期记忆可被专业 Agent 使用
* 不存在 Agent 返回 HTTP 404
* 原有 Chat API 和 Memory API 未被破坏

## 10. 当前系统能力

```text
NovelForge Backend
├── Local Qwen Chat
├── Provider Registry
├── LLM Manager
├── SQLite Long-Term Memory
├── FAISS Vector Index
├── Hybrid Memory Retrieval
├── Memory Consistency Repair
├── NovelAgent
├── CharacterAgent
├── WorldAgent
├── PlotAgent
└── Agent HTTP API
```

## 11. 本 Sprint 未包含

* ChapterAgent
* RewriteAgent
* ReviewAgent
* Agent 流式输出
* Agent 执行历史
* Agent 超时与重试
* Agent Tool Calling
* 多 Agent 工作流
* LangGraph 编排
* 自动保存 Agent 输出到长期记忆
* 前端 Agent 选择界面

## 12. 下一阶段

下一阶段建议进入 Sprint 07C：

* ChapterAgent
* RewriteAgent
* ReviewAgent
* Agent 统一错误处理
* Agent 执行记录
* Agent 超时控制
* Agent API 集成测试
* 可选的 Agent 输出记忆提取

或者进入工作流阶段：

* LangGraph State
* Planner
* Character / World / Plot 多 Agent 协作
* 章节生成工作流
* 一致性审查工作流
