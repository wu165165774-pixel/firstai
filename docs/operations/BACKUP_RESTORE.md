# NovelForge 离线备份与恢复

## 适用范围

Sprint 09C.1 的备份工具覆盖当前全部生产权威数据与派生向量索引：

- `novels.db`
- `workflow_runs.db`
- `memory.db`
- `external_knowledge.db`
- `temporal_graph.db`
- `vector_db/memory.index` 与 `memory_ids.json`
- `vector_db/external_knowledge.index` 与 `external_knowledge_ids.json`

`novelforge.db` 是无运行时代码引用的历史文件，不属于当前权威集合。SQLite 是业务事实来源；FAISS 成对缺失时允许恢复后重建，单边缺失则拒绝创建备份。

## 一致性边界

当前五个 SQLite 数据库没有共享事务锁，因此一致快照必须在 Backend 与 Worker 均停止写入的维护窗口创建。`--confirm-offline` 是操作员确认，不会自动判断业务是否仍有其他写入者。Frontend 与 Ollama 可以保持运行。

工具会对每个 SQLite 使用 SQLite Backup API，执行 `PRAGMA integrity_check`，并记录 schema 元数据；FAISS 会被实际加载，校验维度、向量数量和 ID 映射数量。Manifest 记录文件大小与 SHA-256，但不包含业务内容、源绝对路径或密钥。

## 创建备份

完整的创建、校验、dry-run、隔离恢复和健康检查可通过仓库脚本一次执行：

```powershell
& .\scripts\sprint09c1_restore_drill.ps1
```

以下分步命令用于需要手工控制维护窗口的场景。

在仓库根目录的 PowerShell 中执行。请为每次演练使用新的 `$backupId`：

```powershell
$backupId = "manual-$(Get-Date -Format 'yyyyMMddTHHmmss')"

docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml stop worker
if ($LASTEXITCODE -ne 0) { throw "无法停止 Worker" }

docker-compose stop backend
if ($LASTEXITCODE -ne 0) {
  docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml up -d --no-deps worker
  throw "无法停止 Backend"
}

try {
  docker-compose run --rm --no-deps backend `
    python -m app.backup.cli create `
      --data-root /app/data `
      --output-root /app/data/backups `
      --backup-id $backupId `
      --confirm-offline
  if ($LASTEXITCODE -ne 0) { throw "备份创建失败" }
}
finally {
  docker-compose up -d --no-deps backend
  docker-compose -f .\docker-compose.yml -f .\docker-compose.worker.yml up -d --no-deps worker
}
```

成功输出应包含 `"result": "ok"`、`"consistency_mode": "offline_required"` 和校验文件数。备份保存在 `data/backups/<backup-id>`。

## 校验与恢复演练

校验备份：

```powershell
docker-compose exec -T backend `
  python -m app.backup.cli verify "/app/data/backups/$backupId"
```

恢复默认只做 dry-run，不写文件：

```powershell
docker-compose exec -T backend `
  python -m app.backup.cli restore "/app/data/backups/$backupId" `
    --target-root "/app/data/restore-drills/$backupId"
```

确认 dry-run 输出 `"dry_run": true` 后，恢复到一个不存在的新目录：

```powershell
docker-compose exec -T backend `
  python -m app.backup.cli restore "/app/data/backups/$backupId" `
    --target-root "/app/data/restore-drills/$backupId" `
    --execute
```

恢复工具不会覆盖现有目录，也不支持原地覆盖生产 `data`。正式灾难恢复应先恢复到新目录、完成校验，再通过受控部署切换数据目录。

## 安全与保留

- Manifest 与数据文件必须一起放在受访问控制的存储中。SHA-256 能检测意外损坏，但本 Sprint 没有签名，不能抵御攻击者同时篡改文件和 Manifest。
- 备份可能包含小说正文、账号作用域元数据和 Provider 运行记录，应按敏感业务数据保护。
- 不要把 `data/backups` 或 `data/restore-drills` 提交到 Git。
- 不要删除生产数据库或已有验收数据来完成恢复演练。
- 异地复制、加密、签名、保留策略和自动调度属于后续发布工程范围。
