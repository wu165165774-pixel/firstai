# Sprint 10C - 1.0 RC 本地部署硬化

## 状态

```text
已完成
目标版本：v1.0.0-rc.1
基线版本：v0.16.0-alpha.2
```

## 目标

在不改变业务领域或数据库结构的前提下，关闭正式候选版的默认宿主网络暴露、Debug 和浏览器响应头缺口，并把 Backend Python 包版本纳入统一发布身份。

## 实现

- Backend 与 Frontend 默认绑定 `127.0.0.1`；Ollama 宿主端口固定 loopback。
- Backend Settings 与 Compose 默认 `DEBUG=false`。
- 新增启动安全门：非 loopback 绑定要求 `AUTH_ENABLED=true` 且 Debug 关闭，否则以稳定错误码 fail closed；显式风险 override 会进入可观测状态。
- 绑定地址只接受 IPv4 字面量，避免主机名解析与 Compose 短端口语法歧义。
- Nginx 隐藏版本，并为 SPA、静态资源、healthz 和代理 API 设置 nosniff、DENY frame、no-referrer 和 CSP。
- Release Engineering 同时校验 `APP_VERSION`、Backend `pyproject.toml`、Frontend 与 lockfile 五处版本身份。
- 生产演练核对实际 Docker HostIp 和 live HTTP header，不把静态配置检查冒充运行状态。

## 验收结果

```text
6/6 deployment security focused tests passed
9/9 release engineering focused tests passed
9/9 plugin catalog focused tests passed
12/12 plugin runtime focused tests passed
7/7 authentication focused tests passed
21/21 frontend tests passed
526/526 backend full regression passed in 113.046s
Python compileall passed
Both Compose configurations passed
git diff --check passed
Backend / Frontend / Worker production images built
RC security live drill passed
```

真实生产演练确认 Backend、Frontend 与 Ollama 分别只绑定 `127.0.0.1:18080`、`127.0.0.1:18081` 和 `127.0.0.1:11434`。不安全的非 loopback 配置被拒绝，启用鉴权且关闭 Debug 的远程配置通过准入；运行态 Debug 和风险 override 均为关闭。Backend、Frontend、Ollama 返回 HTTP 200，安全响应头存在，Worker 正常运行，插件执行保持关闭。

三镜像分别为 Backend `dcd952e4...a0ee`、Frontend `0b62f0cc...62bc`、Worker `b006f3e3...41c9`。验收记录保存在 `data/sprint10c_acceptance.json`，既有业务与验收数据未删除或改写。

## 后续

本 Sprint 已通过完整本地门禁，可封板 `v1.0.0-rc.1`。RC 后续收口聚焦依赖锁定、升级/回滚矩阵和完整产品旅程验收；不会在部署硬化 Sprint 中扩展业务模型或插件执行权限。
