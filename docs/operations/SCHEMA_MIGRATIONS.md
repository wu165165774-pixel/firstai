# NovelForge Schema Migration

## 版本模型

Sprint 09C.2 为五个 SQLite authority 建立统一显式版本：

- `novels.db`
- `workflow_runs.db`
- `memory.db`
- `external_knowledge.db`
- `temporal_graph.db`

SQLite `PRAGMA user_version` 是当前物理库版本，`novelforge_schema_migrations` 是逐版本审计 ledger。每条记录包含 authority、version、migration name、固定 checksum、UTC 应用时间与应用版本。

当前目标版本为 1：

- v0 是 09C.2 之前的 legacy schema。运行时允许完整的 v0 契约，便于先部署兼容代码再执行维护窗口。
- v1 表示完整表/列/索引契约、integrity check、foreign key check 与 migration ledger 均通过。
- 高于当前程序支持版本的数据库会在业务模块初始化前 fail closed，防止旧程序打开新 schema。

## 安全边界

- `status` 是只读操作，可在线执行。
- `upgrade` 必须明确传入 `--confirm-offline`，且必须提供通过 09C.1 verify 的备份目录。
- Backend 与 Worker 必须同时停止写入。Frontend 与 Ollama 可以继续运行。
- 每个 authority 的版本写入在独立 `BEGIN IMMEDIATE` 事务中完成；单库失败会回滚该库的 ledger、DDL 与 `user_version`。
- SQLite 不支持五库共享事务。跨库中断后，已完成库保持可审计 v1，未完成库保持 v0；命令可幂等续跑，或使用维护前备份恢复整个数据集合。
- 不要手工降低 `PRAGMA user_version`、删除 ledger 或只恢复其中一个 authority。

## 状态与校验

在线只读状态：

```powershell
docker-compose exec -T backend `
  python -m app.schema_migrations.cli status `
  --data-root /app/data
```

升级后的严格校验：

```powershell
docker-compose exec -T backend `
  python -m app.schema_migrations.cli verify `
  --data-root /app/data
```

`verify` 要求五库全部为 current，并执行完整 SQLite integrity、foreign-key、表、列、索引和 ledger checksum 检查。

## 标准升级演练

仓库脚本在同一个停写窗口依次执行：

```text
在线 status
  -> 停止 Worker / Backend
  -> 创建并 verify 09C.1 备份
  -> 恢复到全新 migration-drills 目录
  -> 隔离副本 upgrade + verify
  -> 生产五库 upgrade + verify
  -> 重启 Backend / Worker
  -> HTTP health + 在线 v1 verify
```

在仓库根目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\sprint09c2_schema_migration.ps1
```

脚本生成唯一 backup ID，并保留 `data/backups/<id>` 与 `data/migration-drills/<id>`，不覆盖或删除已有目录。如果任何步骤失败，脚本仍会尝试恢复 Backend/Worker；在确认五库状态前不要删除维护前备份。

## 手工升级命令

只有在已经停写且备份通过 verify 后，才能直接运行：

```powershell
docker-compose run --rm --no-deps backend `
  python -m app.schema_migrations.cli upgrade `
  --data-root /app/data `
  --backup-dir /app/data/backups/<backup-id> `
  --confirm-offline
```

重复执行是幂等的：已是 current 的 authority 会进入 `already_current`，不会新增重复 ledger。

## 回退

v1 只新增版本 ledger 并将已存在的历史兼容 schema 明确盖章，不删除业务列或数据。若仍需回退，应停止 Backend/Worker，把整个维护前备份恢复到全新目录并验证，再通过受控部署切换数据根目录。不要在正在使用的生产目录原地拼接或覆盖数据库。
