# CI、发布、升级与回滚

## RC 默认部署安全门禁

正式发布镜像必须保持宿主 Backend/Frontend/Ollama 端口为 loopback-only 默认绑定，Backend `DEBUG=false`，插件执行默认关闭。任何非 loopback 绑定都必须通过启动安全策略；面向不可信网络时继续使用本机 loopback，并在前方部署 HTTPS 反向代理和防火墙。发布验收必须核对实际 Docker HostIp，而不是只检查 Compose 文本。完整策略见 `docs/operations/DEPLOYMENT_SECURITY.md`。

## 自动化边界

- `.github/workflows/ci.yml`：master push、Pull Request 和手工触发时执行 Backend 全量测试、Frontend 测试/构建/bundle 校验、两套 Compose 解析以及 Backend/Frontend/Worker 镜像构建。
- `.github/workflows/release.yml`：只对 `v*` tag 或显式指定的既有 tag 执行完整门禁，生成源码 ZIP、三镜像归档和 `SHA256SUMS`，上传 Actions artifact 并创建或更新 GitHub Release。
- Release workflow 不推送容器 registry；镜像以 `docker save` 归档交付，避免隐式依赖未配置的 registry 凭据。

## 版本门禁

以下五处必须完全一致：

```text
backend/app/version.py
backend/pyproject.toml project.version
frontend/package.json
frontend/package-lock.json root version
frontend/package-lock.json packages[""].version
```

tag 必须是 `v{version}`，且 `data/sprint*_acceptance.json` 至少有一份同版本 `result=PASS` 记录。Compose build context 必须是仓库相对路径。任一条件不满足都拒绝制品生成。

## 制品

```text
novelforge-v{version}-source.zip
novelforge-v{version}-images.tar.gz
SHA256SUMS
```

源码 ZIP 使用固定成员顺序、时间戳和压缩级别；`release-manifest.json` 记录每个成员的字节数和 SHA-256，并记录当前版本验收文件的 path/sprint/PASS 摘要。原始 acceptance JSON 不进入制品，避免生产标识与制品哈希自引用。ZIP 只收录运行源码、Compose、Dockerfile、运维/Sprint 文档和维护脚本，不收录 `.env`、密钥、数据库、FAISS、日志、缓存或本地交接文件。

## 本地发布演练

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\sprint09d_release_drill.ps1
```

输出位于忽略目录 `dist/release-drill`。脚本验证版本/验收、Compose、制品 manifest，并重复生成以证明字节级确定性。

## 升级

1. 阅读目标 release notes、`CURRENT_IMPLEMENTATION.md` 和相关 Sprint 文档。
2. 执行 Sprint 09C.1 离线备份/恢复演练，保留 `BACKUP_ID`；涉及 schema 版本变化时先在隔离副本执行迁移。
3. 使用 `SHA256SUMS` 验证下载制品，运行 release CLI `verify` 验证源码 ZIP 内部 manifest。
4. 加载镜像归档：`docker load -i novelforge-v{version}-images.tar`；若为 `.gz`，先在可信目录解压。
5. 停止 Worker writer，再停止 Backend；应用目标 Compose/环境配置。
6. 启动 Backend，验证 schema compatibility、OpenAPI 版本和 health；再启动 Worker 与 Frontend。
7. 执行目标版本 smoke/drill，确认 Worker accepting、Frontend 200，最后才结束维护窗口。

禁止用删除数据库、清空 acceptance 数据或重建权威库来绕过升级失败。

## 回滚

1. 先停止 Worker 与 Backend，保存失败版本日志和当前数据副本。
2. 检查目标旧版本支持的 schema 上限。若当前数据库版本更高，禁止直接启动旧 Backend。
3. schema 兼容时，可加载上一版本镜像并重建 Backend/Worker/Frontend，随后验证 health、OpenAPI 和 Worker。
4. schema 不兼容或数据迁移有破坏性时，只能恢复升级前 09C.1 完整备份到隔离目录，验证通过后按维护流程切换；不得原地覆盖生产目录。
5. 回滚不会撤销升级期间产生的外部 Provider 请求；涉及外部副作用时单独审计。

当前 schema v1 的兼容范围由目标版本的启动门禁决定，不能仅凭应用版本号推测。
