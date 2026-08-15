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

可在 Backend 容器内用临时随机令牌运行不暴露宿主端口的认证矩阵验收：

```powershell
docker exec -w /app novelforge-backend python scripts/verify_auth_runtime.py
```

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
- [Sprint 08E.2](docs/sprints/Sprint08E2.md)
- [Sprint 09A](docs/sprints/Sprint09A.md)
- [Changelog](docs/CHANGELOG.md)
