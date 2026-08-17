# NovelForge 插件运行与安全边界

## 当前能力

Sprint 10B 提供默认关闭的本地进程内插件运行时。Manifest v1 仍可用于只读 Catalog，但只有带 entry point SHA-256 的 Manifest v2 才能执行。Backend 与 Worker 分别在启动时校验、激活，在退出或启动取消时按逆序卸载。

这不是恶意代码沙箱。启用插件等同于允许经过本地审计的 Python 代码在 NovelForge 进程权限下运行；permission 是启动准入和上下文声明，不会阻止插件直接调用 Python 标准库。只应安装来源可信、内容已审计且哈希已固定的插件。

系统不提供 HTTP 上传、远程安装、在线升级或热重载。插件目录由运维人员在宿主机维护，并以只读方式挂载进容器。

## 目录与配置

每个插件使用独立一级目录：

```text
plugins/
  example-package/
    novelforge-plugin.json
    example_plugin.py
```

Compose 将宿主 `./plugins` 只读挂载到 Backend/Worker 的 `/app/plugins`。仓库只跟踪 `plugins/.gitkeep`；本地第三方插件目录默认被 Git 忽略，不会进入 NovelForge 源码发行包。

默认配置不会执行任何插件：

```text
PLUGIN_ROOT=/app/plugins
PLUGIN_ENABLED_JSON=[]
PLUGIN_EXECUTION_ENABLED=false
PLUGIN_PERMISSION_GRANTS_JSON={}
```

启用时必须同时满足三个门禁：

```text
PLUGIN_ENABLED_JSON=["example.plugin"]
PLUGIN_EXECUTION_ENABLED=true
PLUGIN_PERMISSION_GRANTS_JSON={"example.plugin":["model_access"]}
```

- `PLUGIN_ENABLED_JSON` 是无通配符的精确 allow-list。
- `PLUGIN_EXECUTION_ENABLED` 是总开关；为 `false` 时不会读取或导入 entry point。
- `PLUGIN_PERMISSION_GRANTS_JSON` 按插件 ID 显式授权。Manifest 声明的全部 permission 都必须包含在授权中，非法权限名、重复项或错误结构会 fail closed。
- Backend 和 Worker 是独立进程，会分别加载同一插件；插件实现必须按进程隔离状态并支持幂等清理。
- 修改配置或文件后必须重建/重启对应容器；运行时不监听文件变化。

## Manifest v2

```json
{
  "manifest_version": 2,
  "plugin_id": "example.plugin",
  "name": "Example Plugin",
  "version": "1.0.0",
  "description": "Example only",
  "entry_point": "example_plugin:activate",
  "capabilities": ["prompt"],
  "permissions": ["model_access"],
  "requires": {
    "plugin_api": 1,
    "min_core_version": "1.0.0-rc.1",
    "max_core_version_exclusive": "2.0.0"
  },
  "integrity": {
    "entry_point_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
  }
}
```

用 PowerShell 计算 entry point 哈希：

```powershell
(Get-FileHash .\plugins\example-package\example_plugin.py -Algorithm SHA256).Hash.ToLowerInvariant()
```

Manifest v2 规则：

- `requires.plugin_api` 必须精确等于 Core Plugin API `1`。
- Core 版本必须满足 `min_core_version <= current < max_core_version_exclusive`。
- 版本使用不含 build metadata 的 SemVer，prerelease 按 SemVer 优先级比较。
- entry point 当前只允许插件一级目录中的单个 Python 文件，格式为 `module:callable`；不接受带点的 module 路径、package 导入或符号链接。
- entry point 最大 1 MiB。运行时重新校验 Manifest SHA-256，再读取 entry point 一次、核对 v2 完整性哈希，并直接编译这批已校验字节，避免校验后再次读取文件。
- Manifest 禁止未知字段、重复 capability/permission、非法 ID、非法 entry point 和不完整的 v2 integrity。
- Manifest v1 不含 integrity，只能进入 Catalog；执行会以 `runtime_manifest_upgrade_required` 失败。

支持的 capability：`agent`、`exporter`、`frontend`、`llm_provider`、`prompt`、`retrieval`。

支持的 permission：`database_read`、`database_write`、`filesystem_read`、`filesystem_write`、`model_access`、`network`。

## 激活契约

entry point 可以是同步或异步 callable，接收一个受控上下文：

```python
class Handle:
    async def deactivate(self):
        pass


async def activate(context):
    context.register_extension(
        "prompt",
        "example.plugin.prompt",
        {"name": "example"},
    )
    context.register_cleanup(lambda: None)
    return Handle()
```

- 插件只能为 Manifest 已声明的 capability 注册扩展。
- extension ID 必须以 `<plugin_id>.` 开头，且在同一 capability 内唯一。
- 上下文只暴露插件/Core 版本、声明能力、已授予权限、扩展注册和 cleanup 注册，不传递 Settings、密钥、数据库连接或应用单例。
- 激活返回后上下文立即封存，不能继续注册扩展或 cleanup。
- 多插件按确定性目录顺序激活。任一插件失败时，候选插件和本次已激活插件全部逆序卸载，扩展注册回滚。
- 正常退出、Worker 异常和 Backend 启动取消都会卸载；`handle.deactivate()` 或 cleanup 可以同步或异步。
- 卸载钩子失败不会阻止其余清理，Catalog 只报告稳定错误码 `deactivation_failed`，不暴露插件异常正文。

扩展注册表是 10B 的运行时基础边界，不代表每种 capability 已自动接入所有业务 Provider/Agent 注册表。具体能力适配仍应通过后续 Core-owned adapter 完成，插件不应直接篡改 Core 全局对象。

## 防护与可观测性

- 只扫描插件根目录的一级子目录；package 名必须是有界安全字符，并拒绝 package/Manifest/entry point 符号链接。
- 单个 Manifest 最大 64 KiB，entry point 最大 1 MiB，单次最多扫描 100 个 package。
- 重复 `plugin_id`、未知 allow-list ID、启用但不兼容的插件、哈希变化或权限未授权都会 fail closed。
- Catalog 只返回 package 名、Manifest SHA-256、声明、运行状态和稳定错误码，不返回插件根绝对路径、文件内容、异常详情、配置或密钥。
- `GET /api/v1/plugins` 受 Bearer 保护；启用鉴权后只有 `admin` role 可访问。
- 顶层 `active_plugins` 是当前进程的激活顺序，`runtime_generation` 用于观察生命周期变化；`loaded=true` 只表示当前 Backend 进程已激活。

遇到启动失败时，先将 `PLUGIN_EXECUTION_ENABLED=false` 并重建 Backend/Worker，使系统回到只读 Catalog 模式，再核对稳定错误码、Manifest/entry point 哈希和权限授权。不要通过删除业务数据库或验收数据规避插件错误。
