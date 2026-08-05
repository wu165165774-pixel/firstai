# Sprint 07A：NovelAgent Core Framework

## 1. Sprint 信息

* 项目：NovelForge
* Sprint：07A
* 模块：NovelAgent Core Framework
* 状态：Completed
* 完成日期：2026-08-05
* 开发分支：master
* 基线版本：v0.13.0

## 2. Sprint 目标

建立 NovelForge 可扩展 Agent 基础架构，为后续人物、世界观、剧情规划、章节生成、内容重写和一致性审查 Agent 提供统一的数据模型、注册机制与执行入口。

本阶段只实现 Agent Core，不新增 HTTP API，不引入 LangGraph，也不实现多 Agent 协作。

## 3. 已实现目录

```text
backend/app/agents/
├── __init__.py
├── base.py
├── bootstrap.py
├── errors.py
├── manager.py
├── novel_agent.py
├── registry.py
└── schemas.py
```

## 4. 已实现功能

### 4.1 BaseAgent

定义所有 NovelForge Agent 必须遵守的统一接口：

* `name`
* `description`
* `run(context)`

所有具体 Agent 均应继承 `BaseAgent`。

### 4.2 AgentContext

定义 Agent 单次运行所需的上下文：

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

`AgentContext` 使用 Pydantic 校验，不允许传入未定义字段。

### 4.3 AgentResult

统一封装 Agent 执行结果：

* Agent 名称
* 成功状态
* 输出内容
* Provider
* Model
* Finish Reason
* Token Usage
* Latency
* Metadata

### 4.4 AgentRegistry

实现 Agent 注册和查询：

* 注册 Agent
* 根据名称获取 Agent
* Agent 名称标准化
* 重复注册保护
* 不存在 Agent 异常
* 已注册 Agent 列表

Agent 名称查询不区分大小写。

### 4.5 AgentManager

提供统一 Agent 执行入口：

```text
AgentManager.execute()
    ↓
AgentRegistry.get()
    ↓
BaseAgent.run()
    ↓
AgentResult
```

`AgentManager` 支持直接接收 `AgentContext`，也支持接收普通字典并自动执行 Pydantic 校验。

### 4.6 NovelAgent

实现第一个通用小说 Agent。

当前职责：

* 接收小说任务
* 构造统一系统提示词
* 按需召回长期记忆
* 注入已有聊天消息
* 调用 LLMManager
* 透传 Provider 和 Model
* 返回标准 AgentResult

长期记忆调用链：

```text
NovelAgent
    ↓
MemoryContextBuilder
    ↓
HybridMemoryRetriever
    ├── Qwen Embedding
    ├── FAISS 语义召回
    └── SQLite 完整记忆与数据隔离
```

LLM 调用链：

```text
NovelAgent
    ↓
ChatRequest
    ↓
LLMManager
    ↓
Provider Registry
    ↓
Qwen Local / 其他 Provider
```

### 4.7 Agent Bootstrap

提供 AgentManager 工厂函数：

```python
create_agent_manager(llm_manager)
```

使用依赖注入创建：

* AgentRegistry
* NovelAgent
* AgentManager

当前不直接创建全局 AgentManager，避免 Agent Bootstrap 与 LLM Bootstrap 产生循环依赖。

## 5. 当前 Agent 列表

```text
novel
```

`novel` 是当前通用小说任务 Agent。

后续将增加：

```text
character
world
plot
chapter
rewrite
review
```

## 6. 自动化测试

新增测试文件：

```text
backend/tests/test_agents.py
```

覆盖：

* Agent 注册
* Agent 名称查询
* Agent 名称大小写标准化
* 重复注册保护
* 不存在 Agent 错误
* AgentManager 执行
* 字典到 AgentContext 自动转换
* NovelAgent 长期记忆注入
* NovelAgent LLM 请求构造
* Provider 和 Model 传递
* Agent Metadata 注入
* 禁用长期记忆

测试结果：

```text
Agent tests: 6 passed
```

结合现有 Memory/RAG 测试：

```text
Memory/RAG tests: 8 passed
Agent tests: 6 passed
Total: 14 passed
```

## 7. 本 Sprint 未包含

以下功能不属于 Sprint 07A：

* Agent HTTP API
* Agent 全局 Bootstrap
* CharacterAgent
* WorldAgent
* PlotAgent
* ChapterAgent
* RewriteAgent
* ReviewAgent
* LangGraph 工作流
* Agent Tool Calling
* 多 Agent 协作
* Agent 运行记录持久化
* Agent 权限控制
* Agent 超时和重试
* Agent 流式输出

## 8. 验收结论

Sprint 07A 已完成以下验收：

* 所有 Agent 文件通过 Python 语法检查
* Agent 模块可在 Backend 容器内完整导入
* BaseAgent 抽象接口可用
* AgentRegistry 注册与异常保护正常
* AgentManager 调度正常
* NovelAgent 可注入长期记忆
* NovelAgent 可禁用长期记忆
* LLM 请求参数透传正常
* 自动化测试通过
* 未破坏现有 Memory/RAG 功能

Sprint 07A 状态：

```text
Completed
```

## 9. 下一阶段

Sprint 07B 计划：

* Agent Bootstrap 接入 Backend
* Agent 列表 API
* Agent 执行 API
* CharacterAgent
* WorldAgent
* PlotAgent
* Agent API Schema
* Agent API 自动化测试
* Agent 端到端 Qwen 测试

Sprint 07B 完成后，评估发布：

```text
v0.14.0-alpha.1
```
