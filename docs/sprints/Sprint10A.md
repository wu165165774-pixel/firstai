# Sprint 10A - 插件契约与只读目录

## 状态

```text
已完成
目标版本：v0.16.0-alpha.1
基线版本：v0.15.0-alpha.38
```

## 目标

在允许任何第三方代码进入运行时之前，建立可审计、可兼容、可禁用的插件 manifest 和 Catalog 边界。

## 实现

- Manifest v1 对 ID、版本、entry point、能力、权限和 Core 兼容范围执行 Pydantic 严格校验。
- 自有 SemVer 比较器支持 prerelease，并以 `Plugin API 精确匹配 + Core min inclusive/max exclusive` 判断兼容性。
- Backend 只读扫描一级 package，限制 manifest 为 64 KiB、最多 100 个 package，并拒绝 package/manifest 符号链接。
- `PLUGIN_ENABLED_JSON` 是精确 allow-list；缺失、重复、损坏、未知或不兼容的已启用插件 fail closed。
- `GET /api/v1/plugins` 只允许管理员访问，返回稳定状态、manifest SHA-256 和声明，不暴露绝对路径或异常详情。
- Backend/Worker 只读挂载宿主插件目录；第三方插件默认不进入 Git 或 NovelForge 源码发行包。
- 本阶段 `execution_enabled=false`、`loaded=false`，发现和 Catalog 不导入 entry point；不提供上传/安装 API。

## 当前验证

```text
9/9 plugin catalog focused tests passed in 0.883s
8/8 release engineering tests passed in 0.039s
7/7 authentication tests passed in 4.053s
10/10 schema migration tests passed in 9.225s
507/507 backend full regression passed in 137.525s
19/19 frontend tests passed
Entry-point non-execution boundary passed
Admin-only API and OpenAPI security passed
Backend/Frontend/Worker production image builds passed
Live Plugin drill passed
247-file deterministic source artifact independently verified
```

生产验收由 `scripts/sprint10a_plugin_drill.ps1` 完成三镜像构建、服务重建、OpenAPI/version、空只读插件根、`execution_enabled=false` 和 Worker 存活检查。Backend/Frontend HTTP 200、Worker running，Backend/Frontend/Worker 镜像分别为 `a04a8ff9...fdf0d`、`e9e0d379...c869`、`b18d7a92...af235`。若生产启用了 Bearer 鉴权，执行脚本时通过 `-AdminToken` 传入管理员 token；脚本不记录 token。

验收记录保存在 `data/sprint10a_acceptance.json`。GitHub 托管 CI/Release 仍需配置 remote 并推送后才会实际运行，不把本地等价门禁冒充远端 run。

## 后续

Sprint 10B：受控运行时激活、扩展上下文、能力级授权和插件生命周期；在签名/来源与回滚策略完成前不开放远程安装。
