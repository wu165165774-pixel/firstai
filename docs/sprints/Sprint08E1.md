# Sprint 08E.1 - Vue 创作工作台基础

## 状态

```text
实现与验收已完成，待 commit/tag
目标版本：v0.15.0-alpha.29
基线版本：v0.15.0-alpha.28
```

## 目标与边界

本 Sprint 建立第一个可运行的 Vue 3 创作界面，把已经稳定的后端领域串成可视化操作入口，但不改变任何权威写入边界：

```text
Project Library
  -> Planning Chain Overview
  -> Chapter Plans / Workflow Runs / Orchestration
  -> Manuscript Candidate Review + explicit accept
  -> Fact Projection checkpoints + retry
```

- Planner 候选仍不自动持久化。
- Workflow 成功仍不自动导入正文。
- Manuscript 候选仍必须人工接受。
- 事实仍只在接受后由后端 outbox 投影；前端只能查询和重试。
- 08E.1 不新增后端业务表、鉴权模型或领域写入捷径。

## 页面与交互

- 项目库按 `user_id` 隔离，支持搜索、创建、选择和本地记忆最近项目。
- 创作总览展示六段权威链、revision/stale、故事弧、章节数、Workflow 与正文接受进度。
- 章节生产展示 Chapter Plan 地图、Workflow 状态/质量门/导入动作、全书编排创建及暂停/恢复/重试/推进。
- 正文审核展示聚合目录、不可变修订、质量分、正文阅读和带 optimistic revision 的显式接受。
- 事实回写展示冻结候选事实、Memory/Vector/Graph checkpoint、失败错误与安全 retry。
- 本地 Backend 健康状态来自真实 `/api/v1/health` 探测，不使用静态在线标识。

## 部署

`novelforge-frontend` 使用 Node 22 多阶段构建和 Nginx 1.27 运行：

```text
host :18081 -> Nginx :80
                  ├── /assets/*  immutable cache
                  ├── /api/*     -> backend:8000
                  ├── /healthz   container healthcheck
                  └── /*         SPA fallback
```

开发态 Vite 同样把 `/api` 代理到宿主 `18080`。所有字体使用系统字体栈，不依赖 Google Fonts 或其他运行时 CDN。

## 已完成验证

```text
8/8 frontend pure/API tests passed
Vue SFC script/template compile passed
Single-process Rollup bundle verification passed (330654 bytes)
CSS parse passed (210 top-level rules)
Frontend Docker image build passed
Vite production build passed (JS 96.09 KB, CSS 19.96 KB)
Frontend container HTTP runtime passed on host port 18081
Docker Compose base config passed
Docker Compose base + worker overlay config passed
Backend health HTTP 200 passed
Retained 08D.3 read-only API integration passed
434/434 backend full regression passed in 198.522s
```

只读联调使用并保留：

```text
user_id = acceptance-08d3-d85958a2019f
novel_id = c561bb57-d151-4032-8a61-3abd8a144536
```

工作台依赖的 Project、Bible、Plan、Arc、Chapter Plan、Workflow、Manuscript、revision 与 completed Fact Projection 均成功返回，未创建、修改或删除验收数据。

## 真实运行态验收

- `http://localhost:18081/` 返回 200 和正确工作台标题。
- 生产 JS 返回 200、97772 bytes，并带 `public, max-age=31536000, immutable`。
- `/healthz` 返回 `ok`；未知 SPA 深链回落到 `index.html`。
- Nginx `/api/v1/health` 代理返回 `NovelForge backend running`。
- 经 `18081` 代理查询保留 08D.3 user scope 返回精确 1 个项目。
- 运行态未创建、修改或删除任何验收数据。

完整记录保存在 `data/sprint08e1_acceptance.json`。

## 后续

08E.2 将补齐 Story Bible、Novel Plan、Story Arc 与 Chapter Plan 的可视化编辑/Planner 候选审核接受，以及 Workflow 创建表单；08E.1 不跨越这些领域 API 的既有门禁。
