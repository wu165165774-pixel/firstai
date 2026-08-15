# Sprint 09A - 鉴权与多用户安全边界

## 状态

```text
实现与验收已完成，待 commit/tag
目标版本：v0.15.0-alpha.31
基线版本：v0.15.0-alpha.30
```

## 目标

09A 把客户端自报 `user_id` 升级为可由运维配置的身份边界：

```text
Bearer token
  -> constant-time token match
  -> fixed user_id + roles
  -> declared request scope validation
  -> Novel / Workflow Run / Memory owner validation
  -> user or admin authorization
```

## 安全边界

- `AUTH_ENABLED=false` 保留本地开发兼容；启用后空、无效或不安全的 token 配置拒绝启动/请求。
- `/api/v1/health` 保持匿名；其他业务 API 在 OpenAPI 中声明 `BearerAuth`。
- 请求 path、query、JSON body 和嵌套 metadata 中的 `user_id` 必须与令牌身份一致。
- 已存在的 `novel_id`、Workflow `run_id` 和 Memory ID 会反查所有者；跨用户访问统一返回 404，避免确认资源是否存在。
- 普通用户不能无 `user_id` 过滤列出全部 Novel/Workflow，也不能访问 Worker、Queue、DLQ、Operations 或 Prometheus 运维接口。
- `admin` 可执行跨用户运维；令牌不进入响应、URL、日志或仓库。
- 工作台只把访问令牌存入当前浏览器会话的 `sessionStorage`，并通过 `/auth/me` 校正创作者 ID。

## 配置

Compose 从未提交的 `.env` 读取：

```text
AUTH_ENABLED=true
AUTH_TOKENS_JSON={"random-token":{"user_id":"author-1","roles":["user"]}}
```

令牌长度必须为 16-512 字符；每个 principal 必须有 1-128 字符的 `user_id` 与非空 roles 数组。示例文件只包含占位内容，不包含真实 secret。

## 专项验证

```text
6/6 Authentication tests passed
15/15 Novel Project tests passed
9/9 Workflow Run tests passed
15/15 Memory Lifecycle tests passed
15/15 frontend tests passed
Vue bundle verification passed (377316 bytes)
440/440 backend full regression passed in 112.999s
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
Frontend Docker build passed: 16/16 steps
Frontend runtime root / healthz / API proxy returned HTTP 200
Enabled-auth isolated Uvicorn acceptance passed
```

生产前端镜像最终写入：

```text
image = sha256:06ac94617b341af44911caae39147896316dd3cb022a45376c41536dd40fe0d5
JavaScript = /assets/index-vPC3u7h3.js (120983 bytes)
CSS = /assets/index-DNyWOLdy.css (24556 bytes)
```

Backend 主服务已重新加载 `.31` 源码；默认 `AUTH_ENABLED=false` 下 OpenAPI 版本、Bearer security scheme、受保护业务 operation 与匿名 Health 标注均已在线验证。

仓库提供 `backend/scripts/verify_auth_runtime.py`，它使用进程内临时随机令牌启动只监听容器 loopback 的隔离 Uvicorn，验证后在 `finally` 中关闭子进程；不会输出 token、暴露宿主端口或修改主服务配置。

真实启用鉴权的隔离 Uvicorn 返回：

```text
health=200
anonymous=401
authenticated=200
mismatch=403
owned=200
hidden=404
user_ops=403
admin_ops=200
identity=acceptance-08e2-6c744aa142
AUTH RUNTIME ACCEPTANCE: PASS
```

验收后主 Backend 保持默认开发模式，匿名 Providers 仍为 HTTP 200。验收记录保存在 `data/sprint09a_acceptance.json`，未修改或删除既有业务/验收数据。

## 后续

Sprint 09B：Provider 能力与密钥状态、云 Provider 适配、Prompt revision 与可审计选择。
