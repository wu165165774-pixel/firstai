# NovelForge 部署安全

## 默认边界

NovelForge 是本地优先应用。标准 Compose 默认将以下宿主端口仅绑定到 `127.0.0.1`：

```text
127.0.0.1:18081 -> Frontend/Nginx
127.0.0.1:18080 -> Backend/FastAPI
127.0.0.1:11434 -> Ollama
```

Backend 默认 `DEBUG=false`、`AUTH_ENABLED=false`、`ALLOW_INSECURE_NETWORK_EXPOSURE=false`。这种组合只允许 loopback 使用，不向局域网或公网开放。Ollama 的宿主端口固定为 loopback；Backend/Worker 仍通过 Compose 内部网络访问 `http://ollama:11434`。

## 配置

```text
NOVELFORGE_BIND_HOST=127.0.0.1
DEBUG=false
AUTH_ENABLED=false
AUTH_TOKENS_JSON={}
ALLOW_INSECURE_NETWORK_EXPOSURE=false
```

`NOVELFORGE_BIND_HOST` 只接受 IPv4 字面量。策略矩阵：

| 绑定 | 鉴权 | Debug | 风险开关 | 结果 |
| --- | --- | --- | --- | --- |
| loopback | 任意 | 任意 | 任意 | 允许；标准配置仍使用 Debug=false |
| 非 loopback | true | false | false | 允许启动，仅适合有额外网络保护的受控环境 |
| 非 loopback | false | 任意 | false | 拒绝启动：`unsafe_network_exposure` |
| 非 loopback | 任意 | true | false | 拒绝启动：`unsafe_network_exposure` |
| 非 loopback | 任意 | 任意 | true | 显式接受风险后允许，并在启动日志标记 override |

无效主机名、IPv6 或非 IP 文本返回稳定错误码 `invalid_bind_host`。策略在插件加载、索引恢复和 API 接受请求之前执行。

## 远程访问

内置 Nginx 提供 HTTP，不终止 TLS。面向不可信网络时推荐保持 NovelForge 绑定 `127.0.0.1`，由同一宿主上的 HTTPS 反向代理连接 Frontend，并用防火墙阻止直接访问 18080/18081/11434。Bearer token 只能通过受保护传输发送，不应写入 URL、仓库、日志或验收记录。

如果确实在受控局域网直接绑定非 loopback 地址：

1. 设置 `AUTH_ENABLED=true`。
2. 为普通用户和管理员配置不同的长随机 token。
3. 保持 `DEBUG=false`。
4. 将 `NOVELFORGE_BIND_HOST` 设置为明确的宿主 IPv4 地址，不使用主机名。
5. 保持 `ALLOW_INSECURE_NETWORK_EXPOSURE=false`。
6. 用 `docker port` 核对实际 HostIp，并验证匿名业务请求返回 401。

`ALLOW_INSECURE_NETWORK_EXPOSURE=true` 只用于已有独立隔离层的特殊环境。它不是认证、TLS 或防火墙的替代品。

## 浏览器响应头

Frontend 和经 Nginx 代理的 API 响应包含：

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`
- 限制为同源资源的 Content Security Policy

这些响应头降低浏览器攻击面，但不替代身份认证、输入校验或网络隔离。

## 验收

从仓库根目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\sprint10c_rc_security_drill.ps1
```

脚本验证 Compose、两种暴露策略、三镜像构建、实际 Docker HostIp、运行时 Debug/override、OpenAPI 版本、Nginx 安全头、插件默认禁用和 Worker 存活。它会重建服务，但不修改业务数据库。
