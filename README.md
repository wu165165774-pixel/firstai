# NovelForge

NovelForge 是面向长篇小说的本地优先 AI 创作系统。它把故事规划、章节生产、审核、正式正文与连续性事实分成可恢复、可审计的领域边界，默认使用本地 Ollama `qwen3:8b` 与 `qwen3-embedding:0.6b`。

## 当前能力

- `Novel Project -> Story Bible -> Novel Plan -> Story Arc -> Chapter Plan` 权威规划链。
- Planner 结构化候选生成与显式接受，固定坐标、revision 与 stale 门禁。
- Chapter Draft / Review / Rewrite / Re-review 工作流、持久队列和外部 Worker。
- 正文候选导入、人工接受、不可变 Manuscript revision 与全小说 Orchestrator。
- Session / Working / Long-term Memory、外部知识库、FAISS 与 Temporal Graph 双路检索。
- 接受后事实通过事务 outbox 和逐存储 checkpoint 回写 Memory、Vector 与 Temporal Graph。
- Vue 3 创作工作台：项目总览、章节生产、正文审核和事实投影状态。

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

工作台通过 Nginx 将同源 `/api/` 请求代理到 Backend，不依赖浏览器跨域配置。首次进入时填写用于隔离项目的 `user_id`。

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
- [Changelog](docs/CHANGELOG.md)
