# NovelForge 当前实现状态

## 1. 文档信息

* 项目名称：NovelForge
* 当前开发分支：master
* 当前代码版本：v0.13.0-alpha.1
* 文档状态：当前实现快照
* 快照日期：2026-08-05
* 当前阶段：长期记忆与 Vector RAG 基础能力已实现，混合检索整合进行中

本文档记录 NovelForge 当前已经实现并完成基础验证的功能。

本文档不是最终架构文档，也不表示原规划中的所有 Sprint 均已按顺序完成。后续开发过程中，将继续补充缺失模块、自动化测试、Sprint 文档和正式版本验收。

---

## 2. 当前整体架构

当前系统主要由以下组件组成：

```text
用户请求
    ↓
FastAPI Chat API
    ↓
LLM Manager
    ↓
Provider Registry
    ├── DeepSeek Provider
    └── Qwen Local Provider
            ↓
        Ollama
            ↓
        qwen3:8b
```

长期记忆处理链路：

```text
用户聊天输入
    ↓
Qwen 生成聊天回复
    ↓
FastAPI BackgroundTasks
    ↓
LLM Memory Extractor
    ↓
结构化记忆分类
    ├── character
    ├── world
    ├── plot
    └── short_term
    ↓
Memory Manager
    ↓
SQLite 持久化
    ↓
去重、hit_count、importance、score 更新
    ↓
Embedding
    ↓
FAISS 持久化索引
```

---

## 3. 已实现功能

### 3.1 Backend 基础框架

已实现：

* FastAPI 应用
* Uvicorn 服务
* Docker 部署
* Docker Compose 编排
* 健康检查接口
* Swagger/OpenAPI 文档
* 请求中间件
* 请求 ID
* 请求耗时日志
* 统一项目配置
* 统一响应结构
* 基础异常处理

当前端口：

```text
宿主机端口：18080
容器端口：8000
```

---

### 3.2 LLM Provider 框架

已实现：

* Base LLM Provider
* Provider Registry
* LLM Manager
* ChatRequest
* ChatMessage
* Provider 动态选择
* Model 动态选择
* 统一聊天调用入口

当前已注册 Provider：

```text
deepseek
qwen_local
```

DeepSeek Provider 框架已经存在，但尚未使用真实 DeepSeek API Key 完成正式验收。

---

### 3.3 本地 Qwen 部署

已实现：

* Ollama Docker 服务
* Backend 与 Ollama 容器通信
* qwen3:8b 本地模型
* OpenAI-compatible Chat API
* Qwen Local Provider
* GPU 推理
* 模型列表查询
* 聊天接口调用

硬件环境：

```text
GPU：NVIDIA GeForce RTX 4070 SUPER
显存：12 GB
CUDA：12.7
```

当前模型：

```text
qwen3:8b
qwen3-embedding:0.6b
```

---

### 3.4 长期记忆数据模型

已实现记忆字段：

```text
id
user_id
novel_id
memory_type
content
importance
hit_count
score
created_at
updated_at
last_accessed_at
metadata
```

记忆类型：

```text
character
world
plot
short_term
```

---

### 3.5 SQLite 记忆存储

已实现：

* SQLite 初始化
* memories 表自动创建
* 记忆新增
* 记忆查询
* 按用户和小说隔离
* metadata JSON 存储
* 时间字段维护
* 动态 score 计算
* 查询结果排序
* 容器重启后数据持久化

SQLite 数据文件：

```text
/app/data/memory.db
```

---

### 3.6 LLM 结构化记忆抽取

已实现：

* 后台异步记忆抽取
* 使用 Qwen 分析用户输入
* 只抽取用户明确提供的信息
* 返回结构化 JSON
* 自动判断 memory_type
* 自动计算 importance
* 一句话拆分为多条原子事实
* 无意义输入返回空数组
* JSON 清理与解析保护
* 非法 memory_type 过滤
* LLM 请求异常保护

验证示例：

输入：

```text
林凡性格谨慎，是青云宗的外门弟子。青云宗位于东荒大陆。
```

抽取结果：

```text
character：林凡性格谨慎。
character：林凡是青云宗的外门弟子。
world：青云宗位于东荒大陆。
```

输入：

```text
请继续。
```

抽取结果：

```json
[]
```

---

### 3.7 记忆去重与评分

已实现：

* 相同内容精确去重
* 重复记忆不产生新记录
* hit_count 自动增加
* updated_at 自动更新
* last_accessed_at 自动更新
* importance 合并
* score 动态计算
* 查询结果按 score 排序

已验证重复输入后：

```text
记录数量仍为 1
hit_count 从 1 增加到 2
score 重新计算
updated_at 更新
```

---

### 3.8 长期记忆上下文注入

已实现：

* 从用户请求提取 user_id
* 从用户请求提取 novel_id
* 提取最后一条用户消息
* 查询相关记忆
* 按 character、world、plot 和 other 分类
* 生成系统提示词
* 将长期记忆插入聊天 messages
* 要求模型禁止编造未记录设定

当前上下文注入仍主要依赖现有 Memory Retriever。

FAISS 语义检索尚未完全接入正式聊天链路。

---

### 3.9 Embedding

已实现：

* Ollama Embedding API
* qwen3-embedding:0.6b
* 批量文本 Embedding
* 1024 维向量
* float32 转换
* 向量归一化
* 空输入检查
* 维度检查
* NaN 和 Infinity 检查
* HTTP 异常处理

语义验证结果：

```text
林凡性格谨慎。
林凡做事小心，从不轻易冒险。
相似度：0.8963
```

与无关世界设定的相似度：

```text
青云宗位于东荒大陆。
相似度：0.2758
```

语义区分测试通过。

---

### 3.10 FAISS 向量存储

已实现：

* FAISS IndexFlatIP
* FAISS IndexIDMap2
* 余弦相似度搜索
* memory_id 到 vector_id 映射
* 稳定 vector_id 生成
* 向量新增
* 向量更新
* 向量删除基础能力
* 索引全量重建
* 索引搜索
* 索引统计
* 索引文件持久化
* JSON ID 映射持久化
* 容器重启后自动加载

持久化文件：

```text
/app/data/vector_db/memory.index
/app/data/vector_db/memory_ids.json
```

---

### 3.11 SQLite 与 FAISS 同步

已实现：

* 从 SQLite 全量重建 FAISS
* SQLite memory ID 与 FAISS vector ID 映射
* 新增记忆后自动生成 Embedding
* 新增记忆后自动写入 FAISS
* 去重更新后自动执行 FAISS upsert
* FAISS 失败不影响 SQLite 主存储
* 可通过 rebuild 恢复向量索引

当前已验证 SQLite 和 FAISS 记录数量一致。

---

### 3.12 FAISS 语义搜索

已实现独立语义搜索。

验证问题：

```text
谁做事很小心，不愿意轻易冒险？
```

第一名结果：

```text
林凡性格谨慎。
```

相似度：

```text
0.6419
```

说明语义搜索能够召回文本表述不同但含义相近的记忆。

---

## 4. 当前主要代码目录

```text
backend/app/
├── api/
│   └── v1/
├── config/
├── core/
├── llm/
│   ├── bootstrap.py
│   ├── base.py
│   ├── manager.py
│   ├── registry.py
│   ├── schemas.py
│   └── providers/
├── memory/
│   ├── context.py
│   ├── extractor.py
│   ├── manager.py
│   ├── retriever.py
│   ├── schemas.py
│   ├── score.py
│   └── storage/
└── rag/
    ├── embedding.py
    ├── faiss_store.py
    └── memory_indexer.py
```

---

## 5. 当前依赖

主要运行依赖：

```text
fastapi
uvicorn
pydantic
pydantic-settings
python-dotenv
loguru
httpx
openai
numpy
faiss-cpu
```

当前已验证：

```text
openai：2.53.0
httpx：0.28.1
numpy：2.5.1
faiss：1.15.0
```

依赖完整性检查：

```text
No broken requirements found.
```

---

## 6. 当前未完成功能

### 6.1 Vector RAG 正式检索链路

待实现：

* FAISS 搜索结果批量读取 SQLite
* user_id 隔离
* novel_id 隔离
* 无效 memory_id 清理
* similarity 过滤
* similarity 与 SQLite score 混合评分
* importance 权重
* hit_count 权重
* 时间衰减
* 最终 top-k 排序
* 接入 MemoryContextBuilder
* 接入正式 Chat API

---

### 6.2 索引一致性

待完善：

* 删除 SQLite 记忆时同步删除 FAISS
* 修改记忆内容时更新向量
* 应用启动时自动检查一致性
* SQLite 与 FAISS 数量不一致时自动重建
* 索引文件损坏恢复
* 模型或向量维度变化后的版本迁移

---

### 6.3 自动化测试

待补充：

* LLM Registry 测试
* Qwen Provider 测试
* SQLite Storage 测试
* Memory Manager 测试
* 记忆去重测试
* Memory Extractor 测试
* Embedding 测试
* FAISS Store 测试
* Memory Indexer 测试
* Chat API 集成测试
* 容器重启持久化测试

---

### 6.4 尚未完成的原规划模块

待后续继续实现：

* OpenAI Provider
* Claude Provider
* DashScope/Qwen API Provider
* DeepSeek API 正式验收
* Session Memory
* Working Memory
* Novel Agent
* LangGraph 工作流
* Prompt Manager
* Plot RAG
* External Knowledge RAG
* Temporal Graph RAG
* 世界观知识图谱
* 人物关系图谱
* Planner
* Consistency Engine
* Chapter Generator
* Rewrite Agent
* Review Agent
* Frontend
* 项目管理界面
* 插件机制
* 完整 v1.0 发布

---

## 7. 当前版本说明

当前版本：

```text
v0.13.0-alpha.1
```

该版本表示：

* 本地 Qwen 聊天能力已实现；
* 长期记忆核心链路已实现；
* LLM 结构化记忆提取已实现；
* SQLite 记忆持久化已实现；
* 精确去重和动态评分已实现；
* Ollama Embedding 已实现；
* FAISS 持久化向量索引已实现；
* SQLite 与 FAISS 自动同步已实现；
* 独立语义搜索已验证；
* 正式混合检索链路尚未完成。

该版本不是正式的 Sprint 13 完成版本，也不是生产版本。

---

## 8. 后续开发原则

从该快照之后继续开发时，应恢复以下工程要求：

1. 每个功能模块必须有明确范围。
2. 每个阶段必须有运行验证。
3. 每个阶段必须有自动化测试。
4. 每个正式 Sprint 必须有完整文档。
5. 每个稳定阶段必须提交 Git。
6. 每个正式里程碑必须打版本标签。
7. 不允许把数据库、日志、模型文件和向量索引提交到 Git。
8. 正式版本发布前必须确保工作区干净。
9. 任何架构调整必须同步更新文档。
10. 每个 Sprint 完成后必须提供验收清单。

---

## 9. 下一步

当前下一项开发任务：

```text
完成 FAISS 与 SQLite 混合检索
```

目标链路：

```text
用户问题
    ↓
Qwen Embedding
    ↓
FAISS 语义召回
    ↓
按 user_id 和 novel_id 过滤
    ↓
SQLite 获取完整记忆
    ↓
similarity + importance + hit_count + score 综合排序
    ↓
MemoryContextBuilder
    ↓
注入 Qwen Chat 上下文
```

完成该功能并补齐自动化测试后，再评估是否发布：

```text
v0.13.0
```
# NovelForge 当前实现状态

## 1. 文档信息

* 项目名称：NovelForge
* 当前开发分支：master
* 当前代码版本：v0.13.0-alpha.1
* 文档状态：当前实现快照
* 快照日期：2026-08-05
* 当前阶段：长期记忆与 Vector RAG 基础能力已实现，混合检索整合进行中

本文档记录 NovelForge 当前已经实现并完成基础验证的功能。

本文档不是最终架构文档，也不表示原规划中的所有 Sprint 均已按顺序完成。后续开发过程中，将继续补充缺失模块、自动化测试、Sprint 文档和正式版本验收。

---

## 2. 当前整体架构

当前系统主要由以下组件组成：

```text
用户请求
    ↓
FastAPI Chat API
    ↓
LLM Manager
    ↓
Provider Registry
    ├── DeepSeek Provider
    └── Qwen Local Provider
            ↓
        Ollama
            ↓
        qwen3:8b
```

长期记忆处理链路：

```text
用户聊天输入
    ↓
Qwen 生成聊天回复
    ↓
FastAPI BackgroundTasks
    ↓
LLM Memory Extractor
    ↓
结构化记忆分类
    ├── character
    ├── world
    ├── plot
    └── short_term
    ↓
Memory Manager
    ↓
SQLite 持久化
    ↓
去重、hit_count、importance、score 更新
    ↓
Embedding
    ↓
FAISS 持久化索引
```

---

## 3. 已实现功能

### 3.1 Backend 基础框架

已实现：

* FastAPI 应用
* Uvicorn 服务
* Docker 部署
* Docker Compose 编排
* 健康检查接口
* Swagger/OpenAPI 文档
* 请求中间件
* 请求 ID
* 请求耗时日志
* 统一项目配置
* 统一响应结构
* 基础异常处理

当前端口：

```text
宿主机端口：18080
容器端口：8000
```

---

### 3.2 LLM Provider 框架

已实现：

* Base LLM Provider
* Provider Registry
* LLM Manager
* ChatRequest
* ChatMessage
* Provider 动态选择
* Model 动态选择
* 统一聊天调用入口

当前已注册 Provider：

```text
deepseek
qwen_local
```

DeepSeek Provider 框架已经存在，但尚未使用真实 DeepSeek API Key 完成正式验收。

---

### 3.3 本地 Qwen 部署

已实现：

* Ollama Docker 服务
* Backend 与 Ollama 容器通信
* qwen3:8b 本地模型
* OpenAI-compatible Chat API
* Qwen Local Provider
* GPU 推理
* 模型列表查询
* 聊天接口调用

硬件环境：

```text
GPU：NVIDIA GeForce RTX 4070 SUPER
显存：12 GB
CUDA：12.7
```

当前模型：

```text
qwen3:8b
qwen3-embedding:0.6b
```

---

### 3.4 长期记忆数据模型

已实现记忆字段：

```text
id
user_id
novel_id
memory_type
content
importance
hit_count
score
created_at
updated_at
last_accessed_at
metadata
```

记忆类型：

```text
character
world
plot
short_term
```

---

### 3.5 SQLite 记忆存储

已实现：

* SQLite 初始化
* memories 表自动创建
* 记忆新增
* 记忆查询
* 按用户和小说隔离
* metadata JSON 存储
* 时间字段维护
* 动态 score 计算
* 查询结果排序
* 容器重启后数据持久化

SQLite 数据文件：

```text
/app/data/memory.db
```

---

### 3.6 LLM 结构化记忆抽取

已实现：

* 后台异步记忆抽取
* 使用 Qwen 分析用户输入
* 只抽取用户明确提供的信息
* 返回结构化 JSON
* 自动判断 memory_type
* 自动计算 importance
* 一句话拆分为多条原子事实
* 无意义输入返回空数组
* JSON 清理与解析保护
* 非法 memory_type 过滤
* LLM 请求异常保护

验证示例：

输入：

```text
林凡性格谨慎，是青云宗的外门弟子。青云宗位于东荒大陆。
```

抽取结果：

```text
character：林凡性格谨慎。
character：林凡是青云宗的外门弟子。
world：青云宗位于东荒大陆。
```

输入：

```text
请继续。
```

抽取结果：

```json
[]
```

---

### 3.7 记忆去重与评分

已实现：

* 相同内容精确去重
* 重复记忆不产生新记录
* hit_count 自动增加
* updated_at 自动更新
* last_accessed_at 自动更新
* importance 合并
* score 动态计算
* 查询结果按 score 排序

已验证重复输入后：

```text
记录数量仍为 1
hit_count 从 1 增加到 2
score 重新计算
updated_at 更新
```

---

### 3.8 长期记忆上下文注入

已实现：

* 从用户请求提取 user_id
* 从用户请求提取 novel_id
* 提取最后一条用户消息
* 查询相关记忆
* 按 character、world、plot 和 other 分类
* 生成系统提示词
* 将长期记忆插入聊天 messages
* 要求模型禁止编造未记录设定

当前上下文注入仍主要依赖现有 Memory Retriever。

FAISS 语义检索尚未完全接入正式聊天链路。

---

### 3.9 Embedding

已实现：

* Ollama Embedding API
* qwen3-embedding:0.6b
* 批量文本 Embedding
* 1024 维向量
* float32 转换
* 向量归一化
* 空输入检查
* 维度检查
* NaN 和 Infinity 检查
* HTTP 异常处理

语义验证结果：

```text
林凡性格谨慎。
林凡做事小心，从不轻易冒险。
相似度：0.8963
```

与无关世界设定的相似度：

```text
青云宗位于东荒大陆。
相似度：0.2758
```

语义区分测试通过。

---

### 3.10 FAISS 向量存储

已实现：

* FAISS IndexFlatIP
* FAISS IndexIDMap2
* 余弦相似度搜索
* memory_id 到 vector_id 映射
* 稳定 vector_id 生成
* 向量新增
* 向量更新
* 向量删除基础能力
* 索引全量重建
* 索引搜索
* 索引统计
* 索引文件持久化
* JSON ID 映射持久化
* 容器重启后自动加载

持久化文件：

```text
/app/data/vector_db/memory.index
/app/data/vector_db/memory_ids.json
```

---

### 3.11 SQLite 与 FAISS 同步

已实现：

* 从 SQLite 全量重建 FAISS
* SQLite memory ID 与 FAISS vector ID 映射
* 新增记忆后自动生成 Embedding
* 新增记忆后自动写入 FAISS
* 去重更新后自动执行 FAISS upsert
* FAISS 失败不影响 SQLite 主存储
* 可通过 rebuild 恢复向量索引

当前已验证 SQLite 和 FAISS 记录数量一致。

---

### 3.12 FAISS 语义搜索

已实现独立语义搜索。

验证问题：

```text
谁做事很小心，不愿意轻易冒险？
```

第一名结果：

```text
林凡性格谨慎。
```

相似度：

```text
0.6419
```

说明语义搜索能够召回文本表述不同但含义相近的记忆。

---

## 4. 当前主要代码目录

```text
backend/app/
├── api/
│   └── v1/
├── config/
├── core/
├── llm/
│   ├── bootstrap.py
│   ├── base.py
│   ├── manager.py
│   ├── registry.py
│   ├── schemas.py
│   └── providers/
├── memory/
│   ├── context.py
│   ├── extractor.py
│   ├── manager.py
│   ├── retriever.py
│   ├── schemas.py
│   ├── score.py
│   └── storage/
└── rag/
    ├── embedding.py
    ├── faiss_store.py
    └── memory_indexer.py
```

---

## 5. 当前依赖

主要运行依赖：

```text
fastapi
uvicorn
pydantic
pydantic-settings
python-dotenv
loguru
httpx
openai
numpy
faiss-cpu
```

当前已验证：

```text
openai：2.53.0
httpx：0.28.1
numpy：2.5.1
faiss：1.15.0
```

依赖完整性检查：

```text
No broken requirements found.
```

---

## 6. 当前未完成功能

### 6.1 Vector RAG 正式检索链路

待实现：

* FAISS 搜索结果批量读取 SQLite
* user_id 隔离
* novel_id 隔离
* 无效 memory_id 清理
* similarity 过滤
* similarity 与 SQLite score 混合评分
* importance 权重
* hit_count 权重
* 时间衰减
* 最终 top-k 排序
* 接入 MemoryContextBuilder
* 接入正式 Chat API

---

### 6.2 索引一致性

待完善：

* 删除 SQLite 记忆时同步删除 FAISS
* 修改记忆内容时更新向量
* 应用启动时自动检查一致性
* SQLite 与 FAISS 数量不一致时自动重建
* 索引文件损坏恢复
* 模型或向量维度变化后的版本迁移

---

### 6.3 自动化测试

待补充：

* LLM Registry 测试
* Qwen Provider 测试
* SQLite Storage 测试
* Memory Manager 测试
* 记忆去重测试
* Memory Extractor 测试
* Embedding 测试
* FAISS Store 测试
* Memory Indexer 测试
* Chat API 集成测试
* 容器重启持久化测试

---

### 6.4 尚未完成的原规划模块

待后续继续实现：

* OpenAI Provider
* Claude Provider
* DashScope/Qwen API Provider
* DeepSeek API 正式验收
* Session Memory
* Working Memory
* Novel Agent
* LangGraph 工作流
* Prompt Manager
* Plot RAG
* External Knowledge RAG
* Temporal Graph RAG
* 世界观知识图谱
* 人物关系图谱
* Planner
* Consistency Engine
* Chapter Generator
* Rewrite Agent
* Review Agent
* Frontend
* 项目管理界面
* 插件机制
* 完整 v1.0 发布

---

## 7. 当前版本说明

当前版本：

```text
v0.13.0-alpha.1
```

该版本表示：

* 本地 Qwen 聊天能力已实现；
* 长期记忆核心链路已实现；
* LLM 结构化记忆提取已实现；
* SQLite 记忆持久化已实现；
* 精确去重和动态评分已实现；
* Ollama Embedding 已实现；
* FAISS 持久化向量索引已实现；
* SQLite 与 FAISS 自动同步已实现；
* 独立语义搜索已验证；
* 正式混合检索链路尚未完成。

该版本不是正式的 Sprint 13 完成版本，也不是生产版本。

---

## 8. 后续开发原则

从该快照之后继续开发时，应恢复以下工程要求：

1. 每个功能模块必须有明确范围。
2. 每个阶段必须有运行验证。
3. 每个阶段必须有自动化测试。
4. 每个正式 Sprint 必须有完整文档。
5. 每个稳定阶段必须提交 Git。
6. 每个正式里程碑必须打版本标签。
7. 不允许把数据库、日志、模型文件和向量索引提交到 Git。
8. 正式版本发布前必须确保工作区干净。
9. 任何架构调整必须同步更新文档。
10. 每个 Sprint 完成后必须提供验收清单。

---

## 9. 下一步

当前下一项开发任务：

```text
完成 FAISS 与 SQLite 混合检索
```

目标链路：

```text
用户问题
    ↓
Qwen Embedding
    ↓
FAISS 语义召回
    ↓
按 user_id 和 novel_id 过滤
    ↓
SQLite 获取完整记忆
    ↓
similarity + importance + hit_count + score 综合排序
    ↓
MemoryContextBuilder
    ↓
注入 Qwen Chat 上下文
```

完成该功能并补齐自动化测试后，再评估是否发布：

```text
v0.13.0
```

Sprint 07A：NovelAgent Core Framework completed
Sprint 07B：Agent API and specialized agents completed

Registered agents:
- novel
- character
- world
- plot

Agent API:
- GET /api/v1/agents
- POST /api/v1/agents/{agent_name}/execute

Test status:
- 24 tests passed



## Sprint 07B.1：Agent Grounding Hardening

状态：Completed

版本：v0.14.0-alpha.2

新增能力：

* Agent `auto / grounded / creative` 任务模式
* 专业 Agent 确定性事实回答
* Hybrid Semantic Retrieval
* SQLite 类型全量扫描
* HybridMemoryResult `memory_id` 兼容
* 单一事实证据收缩
* Agent Grounding Evidence
* 专业 Agent 事实型幻觉防护
* Grounded 模式不调用 LLM
* Creative 模式调用本地 Qwen
* Qwen Thinking 默认关闭，防止正文输出为空

当前专业 Agent：

* novel
* character
* world
* plot

测试状态：

* Agent tests：22 passed
* Memory/RAG tests：8 passed
* Total：30 passed

端到端状态：

* Character Grounded：Passed
* World Grounded：Passed
* Plot Grounded：Passed
* World Creative：Passed


## Sprint 07C.2：高级小说专业 Agent

状态：Completed

版本：v0.15.0-alpha.1

新增 Agent：

* ChapterAgent
* RewriteAgent
* ReviewAgent

当前 Agent Registry：

* chapter
* character
* novel
* plot
* review
* rewrite
* world

新增能力：

* 完整章节生成
* 小说文本改写、润色、扩写和缩写
* 人物一致性审查
* 世界观一致性审查
* 剧情因果和时间线审查
* 文本节奏、对话和表达质量审查
* 专业 Agent 执行 Metadata
* 专业 Agent 推荐 Reasoning 强度
* ReviewAgent 未确认设定防幻觉约束

推荐 Reasoning：

* ChapterAgent：low
* RewriteAgent：none
* ReviewAgent：medium

测试状态：

* Advanced Agent tests：7 passed
* Total：41 passed

端到端状态：

* ChapterAgent：Passed
* RewriteAgent：Passed
* ReviewAgent：Passed
* Seven Agent Registry：Passed
## Sprint 07C.2：高级小说专业 Agent

状态：Completed

版本：v0.15.0-alpha.1

新增 Agent：

* ChapterAgent
* RewriteAgent
* ReviewAgent

当前 Agent Registry：

* chapter
* character
* novel
* plot
* review
* rewrite
* world

新增能力：

* 完整章节生成
* 小说文本改写、润色、扩写和缩写
* 人物一致性审查
* 世界观一致性审查
* 剧情因果和时间线审查
* 文本节奏、对话和表达质量审查
* 专业 Agent 执行 Metadata
* 专业 Agent 推荐 Reasoning 强度
* ReviewAgent 未确认设定防幻觉约束

推荐 Reasoning：

* ChapterAgent：low
* RewriteAgent：none
* ReviewAgent：medium

测试状态：

* Advanced Agent tests：7 passed
* Total：41 passed

端到端状态：

* ChapterAgent：Passed
* RewriteAgent：Passed
* ReviewAgent：Passed
* Seven Agent Registry：Passed

## v0.15.0-alpha.2 — Sprint 07D.1 Chapter Production Workflow

已实现章节生产工作流：

```text
ChapterAgent → ReviewAgent → Quality Gate → RewriteAgent
```

新增：

- `POST /api/v1/workflows/chapter`
- 结构化 Review JSON
- 可配置严重等级门禁
- 自动改写开关
- 三个阶段独立推理等级、温度和 Token 上限
- 工作流步骤、Token 和延迟聚合
- 安全失败状态和原始正文保留
- 6 条工作流测试

验收状态：

```text
47/47 tests passed
OpenAPI workflow route passed
External port 18080 passed
Real Qwen two-stage branch passed
Real Qwen three-stage rewrite branch passed
```

说明：Sprint 07D.1 不在 Rewrite 后执行第二次 Review，因此改写分支的 `quality_gate_passed` 保持为 `false`。复审闭环将在 Sprint 07D.2 实现。

## v0.15.0-alpha.3 — Sprint 07D.2 Multi-Round Chapter Quality Loop

章节生产工作流已升级为：

```text
Chapter → Review → Rewrite → Re-Review
```

新增最大修订轮次、复审历史、步骤轮次和尝试编号、正文循环保护、Review 自动降级重试，以及严格的最终质量门禁语义。

验收：

```text
15/15 targeted workflow tests passed
56/56 full regression tests passed
OpenAPI multiround fields passed
OpenAPI review retry fields passed
Real Qwen draft-review-rewrite-review loop passed
Real Qwen max revision termination passed
```

真实验收最终状态为 `max_revisions_reached`：复审仍发现问题且请求只允许 1 轮修订。系统保留最新修订稿，并正确保持 `quality_gate_passed=false`。

## v0.15.0-alpha.4 — Sprint 07D.3 Structured Quality Tracking

章节生产闭环新增结构化质量评分与问题追踪：

```text
Chapter → Review + Scores + Issue IDs → Rewrite → Re-Review
```

新增：

- 六维质量评分与总分
- 0～10 分自动归一化
- 缺失评分安全推断
- `minimum_overall_score`
- `minimum_dimension_score`
- `require_all_issues_resolved`
- 稳定 `ISSUE-xxx` 标识
- `new / persisting / resolved / reopened` 状态迁移
- 只向 Rewrite 传递未解决问题
- 每轮修订差异摘要
- 完整质量门禁原因

验收：

```text
23/23 targeted workflow tests passed
64/64 full regression tests passed
Host-side API and OpenAPI validation passed
Real Qwen quality score history passed
Real Qwen issue tracking and transitions passed
Real Qwen revision diff summary passed
```

真实验收结果保留一个持续存在的 `ISSUE-001`，因此在一轮修订上限下返回 `max_revisions_reached`，并正确保持 `quality_gate_passed=false`。

## v0.15.0-alpha.5 — Sprint 07D.4 Workflow Run Persistence

章节生产工作流新增运行持久化和精确 Checkpoint 恢复。

新增 API：

```text
POST /api/v1/workflows/chapter/runs
GET  /api/v1/workflows/runs
GET  /api/v1/workflows/runs/{run_id}
POST /api/v1/workflows/runs/{run_id}/resume
```

新增能力：

- SQLite 保存运行请求、结果和状态
- 保存 Workflow Step 审计事件
- 保存 Draft、Rewrite 和 Checkpoint 章节版本
- `run_id / root_run_id / parent_run_id`
- Backend 重启后继续查询
- 未通过质量门禁的运行标记为 `resumable`
- 从最新正文精确恢复
- Resume 不重新调用 ChapterAgent
- Resume 参数白名单保护
- 成功运行禁止重复恢复
- 运行失败状态持久化

恢复时首个步骤为：

```text
stage: draft
agent: checkpoint
provider: workflow_checkpoint
```

验收：

```text
9/9 targeted workflow-run tests passed
73/73 full regression tests passed
Runtime Agent Manager compatibility passed
Parent run persistence passed
Backend restart persistence passed
Exact checkpoint content match passed
Parent-child lineage query passed
```

## v0.15.0-alpha.6 — Sprint 07D.5 Async Workflow Queue

章节生产工作流新增持久化异步队列和运行控制。

新增 API：

```text
POST /api/v1/workflows/chapter/runs/async
GET  /api/v1/workflows/runs/{run_id}/control
POST /api/v1/workflows/runs/{run_id}/cancel
```

新增能力：

- HTTP 202 立即返回 `run_id`
- SQLite 持久任务队列
- 进程内后台 Worker
- 原子任务领取
- 幂等提交和 `Idempotency-Key`
- 默认单任务并发控制
- queued 和 running 任务取消
- Worker 租约与心跳
- 租约过期任务自动回收
- Backend 重启后恢复 Worker
- Run、Queue、Event 状态同步持久化
- 保持同步 Run 和 Resume API 兼容

队列状态：

```text
queued
running
cancelling
cancelled
completed
failed
```

验收：

```text
8/8 async workflow tests passed
9/9 workflow persistence tests passed
81/81 full regression tests passed
HTTP 202 immediate submission passed
Idempotency match passed
Real Qwen background execution passed
Queued cancellation passed
Restart persistence passed
```

## v0.15.0-alpha.7 — Sprint 07D.6 Standalone Workflow Worker

Workflow 执行从 Backend API 进程解耦到独立 Worker 容器。

容器模式：

```text
novelforge-backend: external
novelforge-worker: worker
novelforge-ollama: Qwen inference
```

新增能力：

- 独立 Worker 进程入口
- SQLite Worker 注册表
- Worker 心跳、容量和活动任务数
- Worker 状态查询 API
- 多 Worker 原子任务领取
- API 与 Worker 跨进程取消
- SIGINT/SIGTERM 优雅停机
- 停机任务释放回 queued
- Worker 崩溃后的租约恢复
- 新 Worker 自动接管同一 Run
- 独立 Compose Worker 覆盖配置
- embedded 模式向后兼容

新增 API：

```text
GET /api/v1/workflows/workers
```

验收：

```text
9/9 standalone Worker tests passed
90/90 full regression tests passed
Backend external mode passed
Worker mode and registration passed
Real Worker container crash passed
lease_recovered count = 1
run_completed count = 1
chapter version count = 1
```

## v0.15.0-alpha.8 — Sprint 07D.7 Queue Policies and DLQ

独立 Workflow Worker 增加持久化队列策略和失败恢复能力。

新增能力：

- `-100 ～ 100` 任务优先级
- 优先级、可执行时间和 FIFO 调度
- 最大尝试次数与指数退避
- `retry_wait` 和 `retrying` 状态
- Dead Letter Queue
- 手动重新入队
- DLQ 查询 API
- 队列 Metrics API
- 旧 SQLite 数据库原地迁移
- 终态任务优先级统计

新增 API：

```text
POST /api/v1/workflows/runs/{run_id}/retry
GET  /api/v1/workflows/dead-letter
GET  /api/v1/workflows/queue/metrics
```

验收：

```text
103/103 full regression passed
priority_min = -50
priority_max = 95
priority_average = 22.5
dead_letter_count = 3
run_claimed = 4
retry_scheduled = 2
run_dead_lettered = 2
run_requeued = 1
```

## v0.15.0-alpha.9 — Sprint 07D.8 Backpressure, Timeout and Worker Control

Added production queue protection and Worker operations:

- global queue backpressure
- per-user active-run quota
- idempotency-before-backpressure
- per-attempt execution timeout
- timeout retry and DLQ integration
- Worker pause / resume / drain
- persistent rejection and timeout metrics
- SQLite in-place migration

Acceptance:
```text
113/113 tests passed
queue_full_rejections_delta = 1
user_quota_rejections_delta = 1
timeout_failures_delta = 2
real timed_out_count = 2
production policy restore passed
```

## v0.15.0-alpha.10 — Sprint 07D.9 Queue Operations and Observability

Workflow 队列补齐批量运维、历史归档和可观测性闭环。

新增能力：

- DLQ 批量重放
- 终态 queue job 归档
- 默认 DLQ 归档保护
- Run / Event / Version 历史保留
- 窗口吞吐 Metrics
- 排队延迟 Metrics
- 执行耗时 Metrics
- Worker 集群健康汇总
- stale Worker 独立观测而不误判健康集群

新增 API：

```text
POST /api/v1/workflows/dead-letter/replay
POST /api/v1/workflows/queue/archive
GET  /api/v1/workflows/queue/archive
GET  /api/v1/workflows/workers/health
```

验收：

```text
124/124 full regression passed
DLQ replayed = 2
archived_count = 7
run history preserved
default DLQ archive protection passed
health_status = healthy
running_workers = 1
accepting_workers = 1
stale_workers = 2
```

## v0.15.0-alpha.11 — Sprint 07D.10 Operations Dashboard and Infrastructure Finalization

07D Workflow Infrastructure 正式收尾。

新增：

- Worker 批量 pause / resume / drain
- Worker 历史安全清理与 dry-run
- 运维操作审计
- Queue/Worker 告警阈值
- Operations Dashboard 聚合 API
- Prometheus exposition endpoint

新增 API：

```text
POST /api/v1/workflows/workers/control/batch
POST /api/v1/workflows/workers/history/cleanup
GET  /api/v1/workflows/operations/audit
GET  /api/v1/workflows/operations/dashboard
GET  /api/v1/workflows/metrics/prometheus
```

验收：

```text
136/136 full regression passed
batch worker pause/resume passed
worker history cleanup passed
operations audit passed
dashboard aggregation passed
prometheus live metrics passed
worker health healthy
```

最终 Dashboard 可保持 `warning`，例如历史 DLQ backlog 达到阈值；这与 Worker 集群健康状态独立。

## v0.15.0-alpha.12 — Sprint 08A.1 Novel Project and Story Bible Foundation

08A Novel Planning Foundation 正式启动。

新增：

- Novel Project 领域模型
- 独立 `novels.db`
- Story Bible 结构化数据
- Story Bible 不可变 revision 历史
- Novel Project optimistic revision
- Story Bible optimistic revision
- user/status Project 查询
- Backend 重启持久化
- Novel / Workflow 数据库隔离

新增 API：

```text
POST  /api/v1/novels
GET   /api/v1/novels
GET   /api/v1/novels/{novel_id}
PATCH /api/v1/novels/{novel_id}
GET   /api/v1/novels/{novel_id}/story-bible
PUT   /api/v1/novels/{novel_id}/story-bible
GET   /api/v1/novels/{novel_id}/story-bible/revisions
GET   /api/v1/novels/{novel_id}/story-bible/revisions/{revision}
```

验收：

```text
151/151 full regression passed
Project revision conflict -> HTTP 409
Story Bible revision conflict -> HTTP 409
Story Bible revisions = [3, 2, 1]
novels.db domain isolation passed
Backend restart persistence passed
```

## v0.15.0-alpha.13 — Sprint 08A.2 Novel Planner Foundation

NovelForge 新增总体小说规划层。

新增：

- Novel Plan
- Main Plot Beats
- Character Arcs
- Volume Plans
- Novel Plan immutable revisions
- optimistic revision conflict
- Project revision source tracking
- Story Bible revision source tracking
- dynamic `is_stale`
- existing Novel Project Plan backfill
- Backend restart persistence

新增 API：

```text
GET /api/v1/novels/{novel_id}/plan
PUT /api/v1/novels/{novel_id}/plan
GET /api/v1/novels/{novel_id}/plan/revisions
GET /api/v1/novels/{novel_id}/plan/revisions/{revision}
```

验收：

```text
168/168 full regression passed
Plan revision conflict -> HTTP 409
Project change -> Plan stale
Story Bible change -> Plan stale
Plan refresh -> source revisions synchronized
Plan revisions = [4, 3, 2, 1]
Planner SQLite persistence passed
Backend restart persistence passed
```

## v0.15.0-alpha.14 — Sprint 08A.3 Story Arc Planning

NovelForge 新增独立 Story Arc 规划层。

新增：

- Story Arc 独立领域实体
- Volume / Arc 顺序和位置唯一约束
- Story Arc immutable revisions
- optimistic revision conflict
- Project source revision tracking
- Story Bible source revision tracking
- Novel Plan source revision tracking
- three-source dynamic `is_stale`
- Turning Points
- Character Progression
- Plot Threads / Dependencies
- target chapter range
- Backend restart persistence

新增 API：

```text
POST /api/v1/novels/{novel_id}/arcs
GET  /api/v1/novels/{novel_id}/arcs
GET  /api/v1/novels/{novel_id}/arcs/{arc_id}
PUT  /api/v1/novels/{novel_id}/arcs/{arc_id}
GET  /api/v1/novels/{novel_id}/arcs/{arc_id}/revisions
GET  /api/v1/novels/{novel_id}/arcs/{arc_id}/revisions/{revision}
```

验收：

```text
186/186 full regression passed
Arc position conflicts -> HTTP 409
Arc revision conflict -> HTTP 409
Project change -> Arc stale
Story Bible change -> Arc stale
Novel Plan change -> Arc stale
Final Arc source revisions synchronized
Arc revisions = [5, 4, 3, 2, 1]
Story Arc SQLite persistence passed
Backend restart persistence passed
```

## v0.15.0-alpha.15 — Sprint 08A.4 Chapter Planning Foundation

NovelForge 新增独立 Chapter Plan 规划层。

新增：

- Chapter Plan 独立领域实体
- Story Arc binding
- full-novel chapter ordering
- chapter number uniqueness
- Arc rebind
- Scene Beats
- POV / conflict / reveal / hook
- continuity dependencies
- target word count
- Chapter Plan immutable revisions
- optimistic revision conflict
- Project source revision tracking
- Story Bible source revision tracking
- Novel Plan source revision tracking
- Story Arc source revision tracking
- four-source dynamic `is_stale`
- Backend restart persistence

新增 API：

```text
POST /api/v1/novels/{novel_id}/chapter-plans
GET  /api/v1/novels/{novel_id}/chapter-plans
GET  /api/v1/novels/{novel_id}/chapter-plans/{chapter_plan_id}
PUT  /api/v1/novels/{novel_id}/chapter-plans/{chapter_plan_id}
GET  /api/v1/novels/{novel_id}/chapter-plans/{chapter_plan_id}/revisions
GET  /api/v1/novels/{novel_id}/chapter-plans/{chapter_plan_id}/revisions/{revision}
```

验收：

```text
206/206 full regression passed
Chapter number conflicts -> HTTP 409
Chapter revision conflict -> HTTP 409
Arc rebind passed
Project change -> Chapter stale
Story Bible change -> Chapter stale
Novel Plan change -> Chapter stale
Story Arc change -> Chapter stale
Final four-source revisions synchronized
Chapter revisions = [6, 5, 4, 3, 2, 1]
Chapter SQLite persistence passed
Backend restart persistence passed
```

## v0.15.0-alpha.16 — Sprint 08A.5 Planner Agent + Local Qwen Structured Planning

NovelForge 在稳定的五层规划领域链之上新增 Planner Agent，并接入本地 `qwen3:8b` 生成结构化规划候选。

新增：

- Planner Agent 与独立 Planner API
- Novel Plan / Story Arc / Chapter Plan 三类候选
- `qwen_local` + `qwen3:8b` 默认推理配置
- Pydantic candidate 最终强校验
- Story Arc / Chapter Plan fixed coordinate 校验
- Novel Plan / Story Arc / Chapter Plan stale gates
- target-aware compact context
- 3600 字符 deterministic context hard budget
- compact prompt JSON Schema
- context / prompt size metadata
- provider、model、usage、latency、source revision metadata

新增 API：

```text
POST /api/v1/novels/{novel_id}/planner/generate
```

架构边界：

```text
/planner/generate returns validated candidate only
persisted = false
no Planner persistence tables
accepted candidates persist through existing domain APIs
```

Chapter target context：

```text
Project
Story Bible
Novel Plan
single selected Story Arc
nearby Chapter Plan summaries
```

不会重复携带完整 Story Arc collection 与 selected Story Arc。

真实 `qwen3:8b` 验收：

```text
Novel Plan Candidate: PASS
prompt_tokens = 1711
planner_context_chars = 2131

Story Arc Candidate: PASS
prompt_tokens = 1961
planner_context_chars = 2758

Chapter Plan Candidate: PASS
prompt_tokens = 2067
planner_context_chars = 3104

Ollama runtime n_ctx = 4096
input prompt truncation = false
```

验收同时证明：

```text
candidate non-persistence passed
explicit domain persistence passed
fixed coordinates passed
Plan stale gates returned HTTP 409
selected Arc stale gate returned HTTP 409
Planner database tables absent
Backend restart persistence passed
```

自动化验证：

```text
22/22 Planner focused tests passed
228/228 full regression passed
Docker Compose config passed
git diff --check passed
```

## v0.15.0-alpha.17 — Sprint 08A.6 Planner Candidate Review + Explicit Acceptance

Planner candidate-only 架构新增显式审核接受能力。

新增 API：

```text
POST /api/v1/novels/{novel_id}/planner/accept
```

正式边界：

```text
/planner/generate -> validated candidate, persisted=false
client review/edit -> explicit user action
/planner/accept -> existing domain persistence, persisted=true
```

新增能力：

- Novel Plan / Story Arc / Chapter Plan 三类候选显式接受。
- target 与 candidate 类型强绑定。
- Story Arc / Chapter Plan fixed coordinates 二次校验。
- 接受前重新执行 target-specific stale gate。
- 接受前比较完整 source revision snapshot。
- SQLite 写事务内再次核对 expected source revisions，防止检查与落库之间的竞态。
- 冲突统一返回 HTTP 409，且不产生部分写入。
- 接受继续复用既有规划领域服务和数据表。
- `/planner/generate` 行为保持不变，继续绝不自动落库。
- Planner 数据库表继续不存在。

真实 `qwen3:8b` 三阶段生成与接受：

```text
Novel Plan: prompt 1351, completion 2207, accept revision 2
Story Arc: prompt 1568, completion 1688, accept revision 1
Chapter Plan: prompt 1672, completion 1445, accept revision 1
persisted on all generation responses = false
persisted on all acceptance responses = true
Ollama truncated = 0, 0, 0
```

冲突与持久化验收：

```text
old candidate acceptance -> HTTP 409
persisted revision unchanged after conflict
planner tables = []
Backend restart persistence passed
Chapter Plan Arc binding preserved
```

自动化验证：

```text
33/33 Planner focused tests passed
239/239 full regression passed
Docker Compose config passed
git diff --check passed
```

项目后续主线统一记录于：

```text
docs/ROADMAP.md
```

## v0.15.0-alpha.18 — Sprint 08A.7 Canonical Entity Foundation

NovelForge 在既有 Novel Project 领域内新增稳定实体身份基础，开始解决长篇生成中的同名、近名和别名串角色问题。

新增数据表：

```text
novel_entities
novel_entity_aliases
```

新增 API：

```text
POST  /api/v1/novels/{novel_id}/entities
GET   /api/v1/novels/{novel_id}/entities
GET   /api/v1/novels/{novel_id}/entities/{entity_id}
PATCH /api/v1/novels/{novel_id}/entities/{entity_id}
POST  /api/v1/novels/{novel_id}/entities/resolve
```

正式语义：

- `(novel_id, entity_id)` 是稳定身份，名字只用于显示和解析。
- 支持 character、organization、location、item、creature、concept；当前重点为 character。
- entity update 保留 ID，并使用 `expected_revision` 乐观并发。
- alias 索引在同一 SQLite 事务中重建。
- 解析优先级固定为 exact canonical、exact alias、normalized canonical、normalized alias。
- 规范化使用空白清理、Unicode NFKC 和 casefold。
- 同一优先级命中多个实体时返回 ambiguous candidates，不默认选择任一实体。

保持不变：

```text
Story Bible legacy character dictionaries remain compatible
Planner generate remains candidate-only and persisted=false
Planner accept remains explicit
Novel Plan / Story Arc / Chapter Plan schemas and stale semantics remain unchanged
Memory / FAISS remain retrieval evidence, not Canon authority
```

自动化验证：

```text
15/15 Entity Registry focused tests passed
15/15 Novel Project focused tests passed
17/17 Novel Planner focused tests passed
33/33 Planner Agent focused tests passed
254/254 full regression passed
Python compileall passed
Docker Compose config passed
git diff --check passed
```

真实 API 与重启验收：

```text
exact canonical resolution passed
normalized alias resolution passed
shared alias returned 2 ambiguous candidates without guessing
stable entity ID and revision conflict passed
alias index replacement passed
Backend restart persistence passed
existing Novel Plan revision remained 1
Planner database tables remained absent
```

详细一致性审计与后续 P0/P1/P2 路线：

```text
docs/architecture/LONG_FORM_CONSISTENCY.md
docs/ROADMAP.md
```

## v0.15.0-alpha.19 — Sprint 08A.8 Story Bible Entity Alignment + Canon Context

NovelForge 完成一致性 P0.2，将 legacy Story Bible、Entity Registry、Planner 和 Agent Context 串成可验收的 Canon 身份链。

新增 API：

```text
POST /api/v1/novels/{novel_id}/story-bible/entities/align
```

新增能力：

- legacy `id`、`character_id`、`entity_id` 兼容识别。
- Story Bible 人物显式绑定 stable entity ID。
- 缺失实体可在显式操作中创建。
- 同名/别名歧义不猜测。
- 重复实体绑定、ID/名称冲突、类型冲突整体回滚。
- `expected_revision` 乐观并发。
- 第二次无变化对齐不增加 revision。
- Entity create/update 推进 Canon revision，使旧规划进入 stale。
- Novel Plan、Story Arc、Chapter Plan 人物/地点引用校验。
- Planner candidate 输出未知 Canon ID 时拒绝。
- 显式接受被编辑成未知 ID 时返回 HTTP 409。
- `CanonContextBuilder` 以 P0 system message 注入 Agent。
- 3600 字符确定性 Canon budget。
- active entity / POV entity 定向选择。
- Memory/RAG 明确为低优先级 evidence。
- Planner target-aware context 内携带 compact canonical entities，且不重复注入通用 Canon block。

保持不变：

```text
/planner/generate remains candidate-only and persisted=false
/planner/accept remains an explicit action
no Planner persistence tables
fixed coordinates and stale gates remain enforced
legacy Story Bible free-form fields remain readable and writable
unmigrated entity types remain compatible
```

自动化验证：

```text
22/22 Canon/Alignment focused tests passed
35/35 Planner focused tests passed
15/15 Entity Registry focused tests passed
278/278 full regression passed
Python compileall passed
Docker Compose config passed
git diff --check passed
```

真实 `qwen3:8b` 验收：

```text
Novel Plan: prompt 1412, completion 2171, context chars 1593
Story Arc: prompt 1607, completion 1649, context chars 2193
Chapter Plan: prompt 1691, completion 1529, context chars 2518
all candidates persisted=false
all candidate character references used canonical Registry IDs
invalid canonical acceptance -> HTTP 409 and no persistence
Ollama n_ctx=4096, truncated=0/0/0
Backend restart persistence passed
Planner tables=[]
```

## v0.15.0-alpha.20 — Sprint 08B.1 Chapter Plan -> Chapter Workflow Bridge

NovelForge 完成一致性 P0.3，将已接受的 Chapter Plan revision 正式接入 Chapter Production Workflow。

新增能力：

- 新 Chapter Workflow HTTP 执行强制携带 `chapter_plan_id` 和 `chapter_plan_revision`。
- 在任何 Agent 调用前加载并验证 Project、Story Bible、fresh Novel Plan、selected Story Arc 和 selected Chapter Plan。
- revision mismatch、stale Plan/Arc/Chapter 统一在生成前返回 HTTP 409。
- selected Project/Bible/Plan/Arc/Chapter 与紧邻章节形成 3600 字符确定性 Grounding Context。
- 自动派生 POV、active character/location IDs、continuity dependencies 和 Memory query。
- Chapter、Review、Rewrite 全阶段共享 P0.3 权威规划 system message。
- Canon 与规划上下文位于 Memory/RAG 证据之前。
- Workflow result 与 persisted Run 记录 binding、source revisions、context chars、active entities 和 adjacent chapters。
- sync Run、resume、async submission 和外部 Worker 均重新校验相同绑定。
- 入队后规划变 stale 的 Job 在 LLM 调用前进入 dead-letter。
- Qwen Review 返回 `finish_reason=length` 时自动使用无推理 fallback 重试，不解析半截 JSON。

HTTP 语义：

```text
missing Chapter Plan binding -> 422
unknown Chapter Plan -> 404
revision conflict -> 409
stale Novel Plan / Story Arc / Chapter Plan -> 409
```

保持不变：

```text
Planner generate remains candidate-only and persisted=false
Planner accept remains explicit
Novel Plan / Story Arc / Chapter Plan remain independent persisted domains
chapter_plans still do not physically store volume_number or arc_number
Memory/RAG remains supporting evidence, not Canon or accepted planning authority
no new Workflow Grounding persistence table
```

自动化验证：

```text
24/24 Chapter Workflow focused tests passed
14/14 Workflow Grounding focused tests passed
293/293 full regression passed
Python compileall passed
Docker Compose config passed
git diff --check passed
```

真实 `qwen3:8b` 验收：

```text
grounding_context_chars = 3595 / 3600
sync resume Review total tokens = 3997 / 4096
external Worker Draft total tokens = 3127 / 4096
external Worker Review total tokens = 4001 / 4096
sync resume quality gate = passed
external Worker queue/run = completed/succeeded
all real Chapter/Review steps grounding_enforced=true
```

竞态与重启验收：

```text
fresh Job submitted while Worker stopped
Story Bible revision advanced 5 -> 6
Worker revalidation rejected stale Novel Plan
Job dead_lettered with latest_content_length=0
sync and async stale gates returned HTTP 409
Backend/Worker restart persistence passed
OpenAPI binding requirement persisted
```

## v0.15.0-alpha.21 — Sprint 08B.2 Manuscript / Chapter Draft / Revision Domain

NovelForge 新增正式 Manuscript 领域，将 Workflow 正文输出与权威接受稿分离。

新增数据表：

```text
manuscript_chapters
manuscript_revisions
```

新增能力：

- `(novel_id, chapter_number)` 对应稳定 Manuscript Chapter ID。
- 正文 revision append-only，并保存 content hash、Workflow Run/Version 和规划来源 revision。
- 只允许导入 succeeded、completed、quality-gated 的持久化 Workflow Run。
- Workflow draft/rewrite/checkpoint 版本被复制为 immutable Manuscript revisions。
- 最终 Workflow 正文成为 reviewed candidate，但导入不自动接受。
- 显式接受使用 Manuscript 聚合 revision 乐观并发。
- 导入和接受都在事务内重验 Project/Bible/Plan/Arc/Chapter freshness。
- 同一 Run 重复导入和同一 revision 重复接受均幂等。
- 后续 Chapter Workflow 只加载最多两个 accepted prior Manuscript revisions。
- candidate-only 内容不会进入 Agent Grounding，也不会替换既有 accepted revision。

新增 API：

```text
POST /api/v1/novels/{novel_id}/manuscript/chapters/import-workflow
GET  /api/v1/novels/{novel_id}/manuscript/chapters
GET  /api/v1/novels/{novel_id}/manuscript/chapters/{manuscript_chapter_id}
GET  /api/v1/novels/{novel_id}/manuscript/chapters/{manuscript_chapter_id}/revisions
GET  /api/v1/novels/{novel_id}/manuscript/chapters/{manuscript_chapter_id}/revisions/{revision}
POST /api/v1/novels/{novel_id}/manuscript/chapters/{manuscript_chapter_id}/revisions/{revision}/accept
```

自动化验证：

```text
16/16 Manuscript focused tests passed
14/14 Workflow Grounding focused tests passed
24/24 Chapter Workflow focused tests passed
309/309 full regression passed
Python compileall passed
Docker Compose config passed
git diff --check passed
```

真实 `qwen3:8b` 验收：

```text
Chapter 1 Workflow succeeded/completed and passed quality gate
first import created one approved candidate; second import deduplicated
candidate accepted_revision remained null before explicit accept
Chapter 2 pre-accept grounding contained no candidate Manuscript IDs
explicit accept advanced aggregate revision; repeated accept changed=false
Chapter 2 post-accept grounding contained Chapter 1 Manuscript revision 1
Story Bible revision 5 -> 6 caused accept to return HTTP 409
stale rejection left Chapter 2 accepted_revision=null
```

## v0.15.0-alpha.22 — Sprint 08B.3 Full Novel Orchestrator

NovelForge 新增持久化全小说 Orchestrator，在既有 Workflow Queue 与 Manuscript 领域之间提供可恢复的跨章节控制流。

新增数据表：

```text
novel_orchestrations
novel_orchestration_steps
novel_orchestration_events
```

核心边界：

- 创建时冻结选择范围、Chapter Plan ID/revision、章节顺序、Workflow 和 Queue 策略。
- 每次只排入当前章节的一个 Workflow Run，不并发生成后续章节。
- `advance` 显式协调 succeeded/completed/quality-gated Run，并复用 Manuscript 导入服务形成 candidate。
- candidate 的 `accepted_revision` 保持 `null`；接受仍只能调用既有 Manuscript API。
- 只有当前 step 对应的精确 candidate revision 被接受后，Orchestrator 才排入下一章。
- 后续章节继续由既有 Grounding 读取 accepted-only prior Manuscript revisions。
- Orchestrator 聚合使用 revision 乐观并发；每个状态变化写入 append-only event。
- pause 不取消在途 Workflow，而是阻断候选导入和跨章推进；resume 会恢复原状态并 reconcile。
- Queue/DLQ failure 可重试同一 Run；质量门失败或人工拒绝候选可创建新的 Workflow attempt。
- 创建支持 `Idempotency-Key`，进程重启后聚合、steps、events 和关联 Run 仍可恢复。

新增 API：

```text
POST /api/v1/novels/{novel_id}/orchestrations
GET  /api/v1/novels/{novel_id}/orchestrations
GET  /api/v1/novels/{novel_id}/orchestrations/{orchestration_id}
POST /api/v1/novels/{novel_id}/orchestrations/{orchestration_id}/advance
POST /api/v1/novels/{novel_id}/orchestrations/{orchestration_id}/pause
POST /api/v1/novels/{novel_id}/orchestrations/{orchestration_id}/resume
POST /api/v1/novels/{novel_id}/orchestrations/{orchestration_id}/retry
```

自动化验证：

```text
19/19 Orchestrator focused tests passed
16/16 Manuscript focused tests passed
14/14 Workflow Grounding focused tests passed
8/8 Workflow Async focused tests passed
328/328 full regression passed
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
```

真实外部 Worker `qwen3:8b` 验收：

```text
orchestration_id = 8eb289fe-1aaa-4a95-8f2a-24ef107f234f
Chapter 1 Run succeeded/completed and passed quality gate
pause blocked candidate import and Chapter 2 queueing after Run completion
resume imported Chapter 1 candidate without accepting it
explicit Manuscript accept then queued exactly one Chapter 2 Run
Chapter 2 Grounding contained Chapter 1 accepted Manuscript revision 1
Chapter 2 candidate remained gated until explicit Manuscript accept
final orchestration revision = 9, status = completed, accepted = 2/2
same Idempotency-Key returned deduplicated=true
Story Bible revision 2 -> 3 made new orchestration creation return HTTP 409
```

控制流目前是线性的，SQLite 聚合状态与既有 Queue/DLQ 已足够表达持久恢复、人工门禁和重试，因此本 Sprint 未引入 LangGraph，避免形成第二套执行/checkpoint 权威源。

## v0.15.0-alpha.23 — Sprint 08C.1 Three-tier Memory

NovelForge 将 Memory 内容分类与生命周期正式拆开：

```text
memory_type = character / world / plot / short_term
memory_tier = session / working / long_term
```

新增 `memories` 列：

```text
memory_tier
session_id
expires_at
revision
```

新增表：

```text
memory_lifecycle_events
```

生命周期规则：

- 旧 rows 自动迁移为 `long_term`，不改变稳定 ID、内容类型或旧 API 默认行为。
- Session 必须绑定 `session_id`，默认 24 小时 TTL，不写入 FAISS；同内容只在同 session 内去重。
- Working 为小说级当前创作窗口，默认 30 天 TTL，写入 FAISS。
- Long-term 为跨会话检索证据，无自动 TTL，写入 FAISS，但不是 Canon。
- 只允许 `session -> working -> long_term` 相邻提升，保持同一 memory ID。
- Session 的 frequency 提升要求 `hit_count >= 2`；user-confirmed 提升要求 `importance >= 0.5`。
- Working -> Long-term 要求权威 basis 与 `importance >= 0.7`；accepted Manuscript / Story Bible basis 必须有 `metadata.source_reference`。
- promote 使用 `expected_revision`，冲突返回 HTTP 409；创建、强化、提升、淘汰和显式删除写 append-only events。
- sweep 只淘汰已过期 Session/Working；Long-term 永不被自动 sweep。
- FAISS consistency 只以 Working/Long-term 为权威集合，Session 误入索引会被 rebuild 清理。
- Agent tiered Memory block 内按 Session、Working、Long-term 排列，整体仍位于 Canon 与 Chapter Plan Grounding 之后。

扩展/新增 API：

```text
POST /api/v1/memory
GET  /api/v1/memory/{user_id}/{novel_id}?memory_tier=&session_id=
POST /api/v1/memory/{memory_id}/promote
GET  /api/v1/memory/{memory_id}/lifecycle/events
POST /api/v1/memory/lifecycle/sweep
POST /api/v1/memory/sessions/{session_id}/close
```

同时修复 `MemoryExtractor` 对单个抽取事实重复保存两次的问题。

自动化验证：

```text
15/15 Memory Lifecycle focused tests passed
8/8 existing Memory/RAG tests passed
48/48 Agent/Canon/Workflow Grounding related tests passed
343/343 full regression passed
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
```

真实 HTTP + Qwen Embedding 验收：

```text
acceptance memory_id = 0783f006-efba-424d-ba14-b245f7827ffb
Session revision 1 did not appear in /retrieve
stale expected_revision returned HTTP 409
Session -> Working kept ID, produced revision 2 and entered /retrieve
Working -> Long-term kept ID, produced revision 3 and removed TTL
events = memory_created, memory_promoted, memory_promoted
expired Session dry-run/execute each selected exactly one ID
session close evicted only the selected session
final scope contains no Session and preserves one Long-term row
```

## v0.15.0-alpha.24 — Sprint 08C.2 External Knowledge Base

NovelForge 新增与小说内部 Memory/Canon 分离的外部知识库：

```text
external_knowledge.db
  -> external_knowledge_sources
  -> external_knowledge_revisions
  -> external_knowledge_chunks

vector_db/external_knowledge.index
vector_db/external_knowledge_ids.json
```

核心边界：

- 外部知识不进入 `memory.db`、Canon、Story Bible 或已接受正文。
- Source 使用稳定 UUID；`source_uri` 在 `(user_id, knowledge_base_id)` 内唯一。
- 内容变更形成 append-only revision，并通过 `expected_revision` 乐观并发；冲突返回 HTTP 409。
- 当前 revision 按 1000 字符、120 字符 overlap 确定性切块；chunk 保存字符坐标和内容 hash。
- SQLite 是权威源，独立 FAISS namespace 负责语义召回；启动时检查并修复 missing/orphan vectors。
- 读取和检索都强制 `user_id + knowledge_base_id` scope，跨作用域 GET 返回 404，检索返回空集。
- Citation 格式为 `EK:<source_id>:r<revision>:c<chunk>`，同时包含 URI、标题、来源类型和字符坐标。
- Novel Agent/Chat 仅在显式给出 `external_knowledge_base_ids` 时加载 P6 External Knowledge。
- 外部证据中的命令只视为数据；不能覆盖 P0-P5 权威上下文，也不触发自动 Memory 抽取。
- 返回边界只保留本轮检索上下文中的 citation；同源缩写会规范成完整 revision/chunk 引用，漏引会补入最高相关证据。

新增 API：

```text
POST   /api/v1/external-knowledge/sources
GET    /api/v1/external-knowledge/sources
GET    /api/v1/external-knowledge/sources/{source_id}
PUT    /api/v1/external-knowledge/sources/{source_id}
DELETE /api/v1/external-knowledge/sources/{source_id}
GET    /api/v1/external-knowledge/sources/{source_id}/revisions
POST   /api/v1/external-knowledge/retrieve
```

自动化验证：

```text
16/16 External Knowledge focused tests passed
359/359 full regression passed after final citation hardening
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
```

真实本地 Qwen 验收：

```text
source_id = 73622379-3a96-4abe-b260-aecc044b70c3
create revision 1 returned 201 and indexed=true
cross-user GET returned 404; cross-user retrieval returned zero hits
update advanced revision 1 -> 2; stale update returned HTTP 409
retrieval citation advanced from r1:c1 to r2:c1
backend restart preserved source revision 2 and independent FAISS retrieval
qwen3:8b answered 74 degrees with the complete r2:c1 citation
embedded instruction requesting 999 degrees was not executed
Chat marked memory_extraction_skipped=true; acceptance Memory count stayed 0
```

## v0.15.0-alpha.25 — Sprint 08C.3 Dual-path Retrieval

NovelForge 新增可插拔的 Vector/Graph 双路检索执行与确定性融合层：

```text
Vector Memory Provider ─┐
                        ├─ concurrent lanes -> RRF -> dedup -> budget
Temporal Graph Provider ┘                    -> provenance + diagnostics
```

核心边界：

- Vector lane 复用现有 Hybrid Memory，只检索 Working/Long-term；Session Memory 继续由 SQLite 按 `session_id` 精确加载。
- 两条 lane 使用 `asyncio` 并发执行，并分别应用超时；不可用、异常或超时只降级对应 lane。
- 默认 Graph Provider 明确返回 `unavailable`，直到 08D.1 提供真正的 Temporal Graph 存储；本 Sprint 不新增 Graph/Planner 表，也不伪造 Graph 结果。
- 融合使用 `RRF_K=60`，以 NFKC、空白归一化和 case-fold 后的 SHA-256 内容指纹去重。
- 排序、来源顺序、`top_k` 和字符预算均为确定性；每条证据保留 path、source ID、rank、原始 score 与 metadata。
- lane 错误对外只返回清理后的诊断，不泄露内部异常正文、路径或 secret。

新增 API：

```text
POST /api/v1/retrieval/fused
```

请求支持 `top_k`、`char_budget`、Vector 相似度门槛、lane timeout、Memory 类型过滤，以及供未来 Graph Provider 使用的 active entity/time 坐标。响应返回 `dual/vector_only/graph_only/unavailable`、`degraded`、融合证据和两条 lane 诊断。

接入行为：

- Memory Context 保持 Session -> Working -> Long-term -> Temporal Graph 分区顺序，并携带检索诊断。
- Novel Agent 与 Chat metadata 返回 `memory_retrieval_mode`、`memory_retrieval_degraded`、`memory_retrieval_lanes`。
- 专业 Agent 的语义检索策略变为 `dual_path_fusion`，证据保留原 Vector memory ID、`source_paths` 和 `fusion_score`。
- 类型枚举/冲突扫描仍走精确 SQLite 查询，不错误地包装成语义双路检索。

自动化验证：

```text
13/13 Dual Retrieval focused tests passed
23/23 Agent related tests passed
23/23 Memory related tests passed
14/14 Workflow Grounding tests passed
373/373 full regression passed
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
```

真实运行态验收：

```text
scope user = sprint08c1-acceptance
scope novel = memory-lifecycle-20260811
memory_id = 0783f006-efba-424d-ba14-b245f7827ffb
marker = 08C1-AMBER-20260811

qwen3-embedding:0.6b Vector lane returned the exact Long-term memory
Graph lane reported unavailable with no fabricated Graph evidence
HTTP mode = vector_only, degraded = true
backend restart preserved the same source memory ID and retrieval result
online OpenAPI version after restart = 0.15.0-alpha.25
grounded Plot Agent exposed provenance and both lane diagnostics
qwen3:8b medium returned the correct memory-backed sentence
prompt/completion/total tokens = 549/284/833
finish_reason = stop
```

验收记录保存在 `data/sprint08c3_acceptance.json`；既有验收数据未删除。下一项为 Sprint 08D.1 Temporal Graph Foundation。

## v0.15.0-alpha.26 — Sprint 08D.1 Temporal Graph Foundation

NovelForge 新增独立 Temporal Graph 权威库，并将真实 Graph Provider 接入既有双路检索：

```text
novel_entities (canonical identity)
          │
          v
temporal_graph.db
  ├── temporal_events
  ├── temporal_event_participants
  ├── temporal_event_revisions
  ├── temporal_relations
  └── temporal_relation_revisions
          │
          v
Graph Provider + Vector Provider -> RRF / dedup / budget
```

核心边界：

- `novel_entities` 仍是实体身份的唯一权威；Graph 只保存对稳定 entity ID 的引用。
- Event 与 Relation 使用当前聚合加 append-only revision snapshot，更新受 `expected_revision` 与 `BEGIN IMMEDIATE` 保护。
- Event participants 物理规范化，地点必须引用 `location` 实体；不存在或跨小说的实体不能写入。
- 时间范围使用闭合 chapter interval，支持指定章节的 current 查询和显式 historical 查询。
- 来源仅允许精确 Story Bible revision 或 accepted Manuscript revision；后者必须匹配正文 chapter。
- 本 Sprint 不自动抽取、不回写、不修改 Canon/Memory/Manuscript，保留 08D.3 的事实写入边界。

Temporal Graph API 提供 Event/Relation 创建、读取、更新、列表、revision 历史与统一 query。查询支持 active entity、chapter、context、event type、predicate 和 historical 过滤，并返回有效区间、confidence、来源 revision 与 Graph revision。

检索与 Agent 接入：

- 默认 Graph lane 已替换为真实 `TemporalGraphRetrievalProvider`；数据库查询在线程中执行，不阻塞异步 lane 调度。
- Graph Provider 消费 `active_entity_ids`、`allowed_memory_types` 和 `as_of=chapter:N`，输出完整 provenance。
- Memory Context、Chat、Novel Agent、Character/World/Plot 等 grounded Agent 自动从 metadata 转发 active character/location/entity IDs 与 chapter number。
- 正确 scope 下 Graph 与 Vector 可同时成功并按规范化内容去重；错误用户 scope 返回零证据并安全降级。

自动化验证：

```text
16/16 Temporal Graph focused tests passed
14/14 Dual Retrieval focused tests passed
390/390 first full regression passed
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
```

真实运行态验收：

```text
scope user = acceptance-08d1-15468ee84ff2
scope novel = 6bb1eaa5-d175-4a93-892e-3ec7271ddd95
marker = 08D1-AZURE-15468ee84ff2

event revision advanced 1 -> 2; stale update returned HTTP 409
chapter 2 current = historical hostile relation only
chapter 3 current = oath event + current ally relation
chapter 3 historical = current facts + ended hostile relation
fused evidence preserved Vector memory ID and Graph event ID
grounded Character Agent answered the chapter-valid ally relation without LLM
qwen3:8b answered the exact oath event; retrieval mode = dual, degraded = false
wrong-user retrieval returned zero evidence
```

验收记录保存在 `data/sprint08d1_acceptance.json`；既有数据库与验收数据未删除。下一项为 Sprint 08D.2 Consistency Engine。

## v0.15.0-alpha.27 — Sprint 08D.2 Consistency Engine

NovelForge 在 Temporal Graph 之上增加 candidate-only 的一致性分析与 Chapter Workflow 硬门禁：

```text
Project / Bible / Canon / current Graph
                 │
                 v
       bounded P0.4 constraints
                 │
                 v
Draft -> Review fact candidates -> deterministic conflicts
                 │                         │
                 └──── Rewrite <───────────┘
                           │
                           v
                       Re-review
```

写作前约束：

- Project constraints、Story Bible rules、Canonical Entity 和指定章节有效的 Temporal Event/Relation 统一为带精确来源 revision 的结构化约束。
- 约束使用确定性 severity/category/ID 排序与字符预算；完整 API 默认 3600 字符，Workflow P0.4 最多 1400 字符。
- Workflow 已由 P0 Canon Context 提供身份信息，因此 P0.4 文本过滤重复 identity，但结果仍保留完整 constraint 列表。
- Novel Agent 将 Chapter Plan Grounding 与 Consistency Constraints 作为权威 system messages，顺序高于 Session/Working/Long-term Memory 和双路 RAG。

写作后检查：

- 候选事实覆盖 relationship、life_state、location、identity 与 event。
- 知识范围统一为 WORLD_TRUTH、CHARACTER_KNOWLEDGE、CHARACTER_BELIEF、READER_KNOWLEDGE。
- 确定性规则检查 unknown/ambiguous entity、ID/name mismatch、relationship、life state、location、timeline、unsupported evidence 与 knowledge scope。
- alias 歧义不会猜测；关系同义词使用受控词表；对称盟友/敌对关系检查反向边。
- transition 必须同时具有明确 evidence，不能仅靠模型标签绕过冲突门禁。
- Qwen 抽取和 grounded Review 的章节号强制绑定请求/Chapter Plan；外部 `/check` 提交错误坐标仍返回 `timeline_conflict`。

API：

```text
POST /api/v1/novels/{novel_id}/consistency/constraints
POST /api/v1/novels/{novel_id}/consistency/check
POST /api/v1/novels/{novel_id}/consistency/analyze
```

`/analyze` 默认使用本地 `qwen3:8b` medium reasoning 抽取候选事实，再交给确定性检查器。三个端点均执行 user/novel scope 门禁，并保持 `persisted=false`。一致性实现没有 Graph/Memory/Vector/Canon/Manuscript 写路径；事实接受与回写留给 08D.3。

Workflow Review 输出新增 `candidate_facts`。确认的 blocking conflict 会强制审核失败、生成一致性 Review issue 并携带完整冲突数据进入 Rewrite；下一次 Review 对修订正文重新抽取和检查。结果暴露 constraints、当前 conflicts、逐轮 conflict history、上下文字符数和 `consistency_fact_persisted=false`。

自动化验证：

```text
16/16 Consistency Engine focused tests passed
25/25 Chapter Workflow focused tests passed
15/15 Workflow Grounding focused tests passed
408/408 full regression passed in 103.532s
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
```

真实运行态验收复用并保留 08D.1 小说 `6bb1eaa5-d175-4a93-892e-3ec7271ddd95`。第 3 章当前 Graph 记录岚与祁为盟友；输入“岚对祁拔剑，宣称两人一直是敌人”后，在线确定性 API 与修复后的真实 `qwen3:8b` 抽取路径均返回 blocking `relationship_conflict`。真实调用 token 为 258/440/698，章节固定为 3，`persisted=false`；调用前后 Temporal Graph revision 行数保持 Event 2、Relation 2。

验收记录保存在 `data/sprint08d2_acceptance.json`；既有数据库与验收数据未删除。下一项为 Sprint 08D.3 accepted Manuscript 后的原子、幂等事实回写。
