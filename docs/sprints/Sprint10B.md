# Sprint 10B - 受控插件运行时

## 状态

```text
已完成
目标版本：v0.16.0-alpha.2
基线版本：v0.16.0-alpha.1
```

## 目标

在 10A 只读 Catalog 之上增加默认关闭、可审计、可回滚的本地插件执行边界，同时明确不把进程内 Python 加载器描述为恶意代码沙箱。

## 实现

- Manifest v2 强制声明 entry point SHA-256；v1 保持 Catalog 兼容但禁止执行。
- 运行时重新核对 Manifest 哈希，拒绝 package/Manifest/entry point 符号链接，只支持插件一级目录中的单文件 module，并限制源码为 1 MiB。
- entry point 源码只读取一次，哈希通过后直接编译同一批字节，避免完整性校验与执行之间再次读取文件。
- `PLUGIN_EXECUTION_ENABLED=false` 是默认总开关；`PLUGIN_ENABLED_JSON` 精确选择插件，`PLUGIN_PERMISSION_GRANTS_JSON` 必须覆盖 Manifest 声明权限。
- 能力上下文只允许插件在已声明 capability 下注册自身命名空间的扩展和 cleanup；激活完成后上下文封存。
- 扩展在单插件激活成功后事务式提交；后续插件失败时，本轮已激活插件逆序卸载，扩展注册全部回滚。
- 同步/异步 activate、handle.deactivate 和 cleanup 均受支持；清理失败不阻断其余清理，只进入稳定 `deactivation_failed` 状态。
- Backend 与 Worker 均接入启动/退出生命周期，覆盖正常退出、启动取消和 Worker 异常。
- 管理员 Catalog 增加 `manifest_version`、`active_plugins`、`runtime_generation`、`failed` 状态和稳定错误码，不泄露路径、源码或插件异常详情。

## 安全边界

该运行时只面向本地可信、经过人工审计并由 SHA-256 固定的插件。permission 是启动准入与上下文声明，不是 Python import、文件系统、网络或 OS 权限沙箱；启用插件等同于允许其以 NovelForge 进程权限运行。

本 Sprint 不增加 HTTP 上传、远程安装、在线升级、热重载或第三方包解析。通用扩展注册表提供生命周期与事务边界，但各 capability 接入 Core 业务注册表仍由后续 Core-owned adapter 完成。

## 当前验证

```text
12/12 plugin runtime focused tests passed in 2.988s
9/9 plugin catalog focused tests passed in 0.847s
9/9 standalone worker tests passed in 6.920s
7/7 authentication tests passed in 7.685s
8/8 release engineering tests passed in 0.038s
10/10 schema migration tests passed in 13.738s
519/519 backend full regression passed in 232.106s
19/19 frontend tests passed
Python compileall and PowerShell syntax passed
Both Compose configurations and git diff check passed
Backend/Frontend/Worker production image builds passed
Live Backend/Worker activation and default-disable rollback drill passed
```

生产演练由 `scripts/sprint10b_runtime_drill.ps1` 创建一个不进入 Git 的临时 Manifest v2 fixture，构建并重建三镜像，在 Backend 与 Worker 两个容器内验证激活标记和 Backend Catalog 状态，随后恢复默认关闭配置并删除精确 fixture 目录。OpenAPI 为 `0.16.0-alpha.2`，Backend/Frontend HTTP 200、Worker running；Backend/Frontend/Worker 镜像分别为 `45d48255...d4ad`、`e9e0d379...c869`、`22d6dc67...c575`。脚本未写入业务数据库、密钥或 Provider endpoint。

本地 release drill 生成 250 文件确定性源码包，通过独立验证和重复字节对比；最终 SHA-256 记录在 `data/sprint10b_acceptance.json`。托管 CI/Release 仍需配置 remote 并推送后才能实际运行，不把本地等价门禁冒充远端 run。

## 后续

`v0.16.0-alpha.2` 已具备本地封板条件。下一项为 1.0 Release Candidate 收口；远程分发、来源签名、进程级隔离和 capability-specific Core adapter 必须拆分为后续显式 Sprint，不能从本地进程内运行时能力推断已经完成。
