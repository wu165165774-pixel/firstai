# NovelForge

NovelForge 是面向长篇小说的本地优先 AI 创作系统。它把故事规划、章节生产、审核、正式正文与连续性事实分成可恢复、可审计的领域边界，默认使用本地 Ollama `qwen3:8b` 与 `qwen3-embedding:0.6b`。

## 当前能力

- `Novel Project -> Story Bible -> Novel Plan -> Story Arc -> Chapter Plan` 权威规划链。
- Planner 结构化候选生成与显式接受，固定坐标、revision 与 stale 门禁。
- Chapter Draft / Review / Rewrite / Re-review 工作流、持久队列和外部 Worker。
- 正文候选导入、人工接受、不可变 Manuscript revision 与全小说 Orchestrator。
- Session / Working / Long-term Memory、外部知识库、FAISS 与 Temporal Graph 双路检索。
- 接受后事实通过事务 outbox 和逐存储 checkpoint 回写 Memory、Vector 与 Temporal Graph。
- Vue 3 创作工作台：项目库、规划领域编辑、Planner 候选审核接受、章节生产、正文审核和事实投影状态。
- 可选 Bearer 身份认证：令牌绑定固定用户、资源所有权隐藏和管理员运维门禁。
- Provider 能力目录：区分注册、配置与实时可用状态，工作台按能力选择 Provider/Model。
- Prompt Catalog：内部 LLM 调用记录不可伪造的 prompt revision 与最终渲染摘要，Planner/Workflow 在工作台展示所选版本。
- 小说级确定性 ZIP 导出：仅包含 accepted manuscript、当前规划与逐文件 SHA-256 manifest。
- CI 与 tag 发布工程：自动回归、三镜像构建、确定性源码制品、checksum 及升级/回滚 runbook。
- 默认关闭的本地可信插件运行时：Manifest v2 完整性、Plugin API/Core SemVer 兼容、显式权限授权、事务式扩展注册、生命周期回滚和管理员 Catalog。
- RC 默认部署安全：宿主端口仅绑定 `127.0.0.1`、Debug 默认关闭、非本机暴露 fail closed，并由 Nginx 返回基础浏览器安全响应头。

## 启动

先确认 Docker Desktop 与 GPU 容器运行环境可用，再从仓库根目录执行：

```powershell
docker-compose -f docker-compose.yml -f docker-compose.worker.yml up -d --build
```

服务地址：

- 创作工作台：`http://localhost:18081`
- Backend API：`http://localhost:18080`
- OpenAPI：`http://localhost:18080/docs`
- Ollama：`http://localhost:11434`

三个宿主端口默认只监听 `127.0.0.1`。不要为了远程访问直接改成 `0.0.0.0`；非本机绑定至少要求启用 Bearer 鉴权并关闭 Debug，面向不可信网络时还应在本机 loopback 前增加 HTTPS 反向代理与防火墙。完整边界见 [部署安全说明](docs/operations/DEPLOYMENT_SECURITY.md)。

工作台通过 Nginx 将同源 `/api/` 请求代理到 Backend，不依赖浏览器跨域配置。开发模式默认关闭鉴权；首次进入时填写用于隔离项目的 `user_id`。

## 启用身份认证

复制 `.env.example` 为不提交的 `.env`，设置 `AUTH_ENABLED=true` 与 `AUTH_TOKENS_JSON`。令牌映射格式如下：

```json
{
  "至少16字符的随机令牌": {
    "user_id": "author-1",
    "roles": ["user"]
  },
  "另一个管理员随机令牌": {
    "user_id": "operator",
    "roles": ["admin"]
  }
}
```

启用后，除 `/api/v1/health` 外的业务 API 都要求 `Authorization: Bearer <token>`。普通用户只能访问令牌绑定的用户、小说、Workflow Run 和 Memory；队列、Worker、DLQ、Operations 与 Prometheus 接口要求 `admin`。工作台令牌只保存在浏览器 `sessionStorage`，关闭会话后清除。不要把真实令牌写入仓库、URL、日志或验收文档。

插件 manifest 放在 `plugins/<package>/novelforge-plugin.json`，通过 `PLUGIN_ENABLED_JSON` 精确声明允许启用的插件 ID。代码执行默认关闭；启用时还需要 Manifest v2 entry point SHA-256、`PLUGIN_EXECUTION_ENABLED=true` 和 `PLUGIN_PERMISSION_GRANTS_JSON` 显式授权。`GET /api/v1/plugins` 仅允许管理员读取并返回当前 Backend 进程状态。插件运行在宿主应用进程权限下，不是恶意代码沙箱，只应加载来源可信且已审计的本地代码。完整契约见 [插件运维说明](docs/operations/PLUGINS.md)。

可在 Backend 容器内用临时随机令牌运行不暴露宿主端口的认证矩阵验收：

```powershell
docker exec -w /app novelforge-backend python scripts/verify_auth_runtime.py
```

## 配置模型 Provider

本地 Qwen 默认由 Compose 配置为 `http://ollama:11434` 与 `qwen3:8b`。可选 DeepSeek 配置放在不提交的 `backend/.env`；从 `backend/.env.example` 复制后填写：

```text
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

空 key 表示未配置。`GET /api/v1/providers` 返回能力与配置状态但不发起网络请求；增加 `?probe=true&timeout_ms=3000` 才会并行执行有界健康探测。响应不会包含 key 或 base URL。工作台使用同一目录选择 Provider/Model，并在目录暂时不可访问时保留手工输入回退。

`GET /api/v1/prompts` 返回内部 Prompt ID、当前 revision 和可用 revisions，不返回 Prompt 正文。Agent、Planner、Workflow、Consistency 与 Memory extraction 的结果 metadata 使用 `prompt_provenance` 记录所选 revision、最终渲染字符数和 SHA-256；摘要用于核对实际请求，不作为正文或配置存储。

## 前端开发

```powershell
cd frontend
npm ci
npm test
npm run build
npm run dev
```

开发服务器运行于 Vite 默认端口，并把 `/api` 代理到 `http://localhost:18080`。生产镜像使用 `npm ci` 构建静态资源，并由 Nginx 提供 SPA fallback、静态缓存与后端代理。

## 文档

- [当前实现](docs/CURRENT_IMPLEMENTATION.md)
- [产品与工程 Roadmap](docs/ROADMAP.md)
- [Sprint 08E.1](docs/sprints/Sprint08E1.md)
- [发布、升级与回滚](docs/operations/RELEASE.md)
- [插件契约与安全边界](docs/operations/PLUGINS.md)
- [Sprint 08E.2](docs/sprints/Sprint08E2.md)
- [Sprint 09A](docs/sprints/Sprint09A.md)
- [Sprint 09B.1](docs/sprints/Sprint09B1.md)
- [Sprint 09B.2](docs/sprints/Sprint09B2.md)
- [Changelog](docs/CHANGELOG.md)
