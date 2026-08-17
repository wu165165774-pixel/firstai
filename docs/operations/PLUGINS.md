# NovelForge 插件契约与安全边界

## 当前阶段

Sprint 10A 只发现并验证本地 manifest，不导入或执行第三方 entry point，也不提供 HTTP 上传、安装、升级或删除接口。`enabled` 表示 manifest 已通过 allow-list，`activation_allowed` 表示兼容性门禁通过；`loaded` 和顶层 `execution_enabled` 在本阶段始终为 `false`。

## 目录与配置

每个插件使用独立一级目录：

```text
plugins/
  example-package/
    novelforge-plugin.json
```

Compose 将宿主 `./plugins` 只读挂载到 Backend/Worker 的 `/app/plugins`。仓库只跟踪 `plugins/.gitkeep`；本地第三方插件目录默认被 Git 忽略，不会进入 NovelForge 源码发行包。

`.env` 中使用精确 JSON allow-list：

```text
PLUGIN_ROOT=/app/plugins
PLUGIN_ENABLED_JSON=["example.plugin"]
```

空数组表示全部禁用。修改后重启 Backend；配置中存在缺失、重复、损坏或不兼容的已启用插件时，启动校验 fail closed。不要使用通配符。

## Manifest v1

```json
{
  "manifest_version": 1,
  "plugin_id": "example.plugin",
  "name": "Example Plugin",
  "version": "1.0.0",
  "description": "Example only",
  "entry_point": "example_plugin:activate",
  "capabilities": ["prompt"],
  "permissions": ["model_access"],
  "requires": {
    "plugin_api": 1,
    "min_core_version": "0.16.0-alpha.1",
    "max_core_version_exclusive": "1.0.0"
  }
}
```

支持的 capability：`agent`、`exporter`、`frontend`、`llm_provider`、`prompt`、`retrieval`。

支持的 permission 声明：`database_read`、`database_write`、`filesystem_read`、`filesystem_write`、`model_access`、`network`。权限目前只是不可变审计声明，不代表系统已经授予访问；在隔离/授权执行层完成前不会加载代码。

兼容规则：

- `manifest_version` 必须为 `1`。
- `requires.plugin_api` 必须精确等于 Core Plugin API `1`。
- Core 版本必须满足 `min_core_version <= current < max_core_version_exclusive`。
- 版本使用不含 build metadata 的 SemVer，prerelease 按 SemVer 优先级比较。
- manifest 禁止未知字段、重复 capability/permission、非法 ID 和非法 entry point。

## 防护与可观测性

- 只扫描插件根目录的一级子目录，拒绝 package/manifest 符号链接。
- 单个 manifest 最大 64 KiB，单次最多扫描 100 个 package。
- 重复 `plugin_id`、未知 allow-list ID 和启用但不兼容的插件使配置无效。
- Catalog 只返回 package 名、manifest SHA-256、声明和稳定错误码，不返回插件根绝对路径、文件内容或异常详情。
- `GET /api/v1/plugins` 受 Bearer 保护；启用鉴权后只有 `admin` role 可访问。

## 后续激活阶段

下一阶段才会设计受控 entry point 加载、扩展上下文、能力级权限、生命周期、升级/回滚和签名/来源策略。在这些门禁完成前，不应把 `activation_allowed=true` 理解为代码已运行。
