# 依赖锁定与受控更新

## 权威输入

生产构建使用以下不可变或精确输入：

- `backend/requirements.lock`：Linux/Python 3.12 完整运行时解析，所有行必须是排序且唯一的 `name==version`。
- `backend/pyproject.toml`：包元数据与直接依赖兼容范围；每个直接依赖必须出现在 lock 中，但 Docker/CI 不从这些范围重新求解。
- `frontend/package-lock.json`：lockfile v3；除 root/link 外每个包必须同时存在 version、resolved 与 integrity。
- Backend/Frontend Dockerfile 的 Python、Node、Nginx 基础镜像，以及 Compose 的 Ollama 镜像：必须包含 `@sha256:<64 hex>`。
- `.github/workflows` 中所有 Action：必须使用完整 40 位 commit SHA，尾注保留人类可读 release tag。

`requirements.txt` 仅为兼容旧工具而存在，唯一有效内容是 `-r requirements.lock`。生产 Dockerfile 禁止 `pip install --upgrade pip` 和 `pip install .`；它安装 lock、执行 `pip check`，然后复制应用源码。

当前 Python lock 是从已完成 526/526 回归和 RC1 live drill 的生产镜像采集，不代表自动接受未来版本。精确版本防止解析漂移；源码包、镜像归档与 release checksum 继续提供交付物完整性。当前 lock 未内嵌逐 wheel hash，因此依赖源仍必须使用可信 HTTPS package index；若改用私有镜像，应在受控配置中固定 index 和证书，不得把凭据写入仓库。

## 校验

静态发布契约：

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path
python -c "from app.release_engineering.service import ReleaseEngineeringService; print(ReleaseEngineeringService('.').dependency_contract())"
```

镜像内实际分发包必须与 lock 完全一致；pip/setuptools/wheel 等引导工具不作为应用运行时包计入：

```powershell
docker run --rm --entrypoint python novel-ai-backend `
  -m app.release_engineering.runtime_lock `
  --lock /app/requirements.lock
```

## 更新流程

1. Dependabot 或维护者提出单独的依赖更新，不把业务功能混入同一变更。
2. 在临时 Linux/Python 3.12 环境按 `pyproject.toml` 求解候选，记录全部分发包；不要直接覆盖已验收 lock。
3. 审核上游 release notes、安全公告、许可证和直接/传递依赖变化。
4. 用候选精确版本更新 `requirements.lock`，保持规范化名称排序；Frontend 更新必须通过 `npm install --package-lock-only` 产生 lockfile，而不是手工修改 integrity。
5. 更新基础镜像时同时保留可读 tag 和精确 digest；更新 Action 时同时更新完整 commit 与尾注 tag。
6. 运行 Dependency/Release 专项、Backend 全量、Frontend test/build、两套 Compose、三镜像构建和 live drill。
7. 只有镜像内 runtime lock 对照与回滚探针也通过，才能写 PASS acceptance、commit 和 tag。

禁止只因“版本较新”批量升级全部依赖，也禁止删除 lock、改回可变 tag 或跳过回归来处理求解冲突。

## 升级/回滚判定

当前版本的显式矩阵位于 `release-compatibility.json`：

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path
python -m app.release_engineering.cli assess `
  --repo-root . `
  --operation rollback `
  --other-version 1.0.0-rc.1 `
  --schema-version 1
```

判定值：

- `direct`：版本和 schema 组合已显式列入矩阵；仍需先备份。
- `restore_backup`：目标旧版本不能打开当前 schema，只能恢复隔离验证过的升级前完整备份。
- `blocked`：路径未声明或坐标不匹配，禁止猜测兼容性。

完整生产演练：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\sprint10d_dependency_rollback_drill.ps1
```

脚本保留 RC1 镜像、停止写入者、创建离线备份、恢复隔离副本、构建 RC2、验证镜像 lock，并在独立端口用 RC1 打开隔离 schema v1。无论成功或失败，都会清理临时 probe 并尝试恢复当前 Backend/Worker；备份和隔离恢复目录会保留用于审计，不自动删除。
