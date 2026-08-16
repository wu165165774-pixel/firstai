# Sprint 09C.1 - 离线一致备份与安全恢复基础

## 状态

```text
实现与验收已完成，待 commit/tag
目标版本：v0.15.0-alpha.35
基线版本：v0.15.0-alpha.34
```

## 目标与边界

本 Sprint 先建立可验证、可恢复且不覆盖生产数据的备份基础。Schema migration 与小说级导出分别留给 09C.2、09C.3。

当前生产数据分散在五个 SQLite authority 和两组 FAISS index/mapping。它们没有跨库事务，因此不虚构在线原子快照：创建操作明确要求 Backend 与 Worker 停写，并在 Manifest 中固定记录 `consistency_mode=offline_required`。

## 实现

- 新增 `app.backup` 领域与 `python -m app.backup.cli` 管理 CLI。
- 创建操作只枚举固定 authority allowlist，不递归打包日志、密钥、旧数据库或已有备份。
- SQLite 使用只读源连接与 SQLite Backup API，备份后执行完整 integrity check，并记录 `user_version` 与业务表数量。
- FAISS 必须 index/mapping 成对存在；实际加载索引，记录 dimension/count，并要求 `ntotal` 等于 mapping 数量。
- 两个 FAISS 对均缺失时记录 `rebuild_required`；只缺一侧时 fail closed。
- Manifest 使用严格 Pydantic schema，拒绝未知字段、重复/越界路径、未知文件、缺失 authority 和非法 rebuild 状态。
- 每个文件记录 SHA-256 与字节数；verify 重新检查哈希、数据库完整性、FAISS 可加载性和未登记文件。
- restore 默认 dry-run，只允许写入不存在的新目录，并通过 staging directory 完成后原子切换；拒绝原地覆盖与已有目标。
- FastAPI 版本统一由 `app.version.APP_VERSION` 提供，避免运行时版本与发布版本漂移。

## 安全语义

Manifest 不记录源绝对路径、业务内容、API key 或 endpoint。错误输出只包含稳定的文件名/组件信息。

SHA-256 用于发现传输或存储损坏，不是数字签名。能够同时改写备份文件与 Manifest 的攻击者仍可伪造备份，因此备份介质的访问控制、加密与签名属于后续发布工程。

## 自动化验证

当前专项覆盖：

- 必须显式确认停写。
- authority 集合与 Manifest 最小披露。
- SQLite schema/integrity 元数据。
- FAISS 可加载、维度/数量元数据与 mapping 数量一致。
- FAISS 缺失重建状态与部分缺失拒绝。
- 路径穿越、authority 遗漏、文件变更和未登记文件拒绝。
- restore dry-run、新目录恢复与已有目标拒绝。
- CLI create/verify/restore 边界。

```text
12/12 backup/restore focused tests passed
472/472 backend full regression passed in 126.837s
18/18 frontend tests passed
Python compileall passed
Docker Compose base + worker overlay config passed
Frontend Docker/Vite production build passed (16 BuildKit steps)
git diff --check passed
```

真实生产数据演练使用 `sprint09c1-20260816T234604`：在 Backend/Worker 停写窗口创建 9 文件、1,541,306 字节快照，校验无重建项；dry-run 写入 0 文件，随后向全新隔离目录恢复 9 文件。恢复文件 SHA-256 全部匹配，五个 SQLite integrity check 与两组 FAISS/mapping 数量校验通过；Backend HTTP 200，Worker 恢复为 running/accepting。既有生产与验收数据均未删除或覆盖。

验收记录保存在 `data/sprint09c1_acceptance.json`。

## 运维入口

完整命令、停写顺序、恢复演练与风险说明见 `docs/operations/BACKUP_RESTORE.md`。

## 后续

- Sprint 09C.2：显式 schema version、可重复 migration、升级与回滚兼容验证。
- Sprint 09C.3：按小说导出正文、规划与可追踪元数据，不泄漏其他用户/小说数据。
