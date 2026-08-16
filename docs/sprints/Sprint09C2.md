# Sprint 09C.2 - 显式 Schema Migration

## 状态

```text
实现、真实 v0 -> v1 迁移、运行时验证与完整验收均已完成
目标版本：v0.15.0-alpha.36
基线版本：v0.15.0-alpha.35
```

## 目标

将五个长期由各 Storage `CREATE IF NOT EXISTS` / 条件 `ALTER TABLE` 隐式维护的 SQLite authority 纳入显式、可验证、可审计的 schema version 管理，同时保持 v0 到 v1 的部署兼容窗口。

## 实现

- 为五库定义完整业务表、列与命名索引契约，不把存在某几个关键表误判为完整 schema。
- 新增 `status`、`upgrade`、`verify` 管理 CLI；状态输出不包含数据库绝对路径或业务内容。
- v1 在每库独立事务中创建 `novelforge_schema_migrations` ledger、写固定 migration checksum，并设置 `PRAGMA user_version=1`。
- 升级前强制 verify 09C.1 备份与操作员停写确认。
- v0 先复用现有 Storage 兼容初始化，补齐已发布历史列和索引，再运行完整预检；无法补齐的残缺库拒绝盖章。
- 重复升级保持幂等，ledger 一库一版本一行。
- 迁移 callback 失败时回滚该库新增表、ledger 与 `user_version`。
- ledger checksum 被修改、version/ledger 不一致、表列索引残缺时 verify fail closed。
- Backend 与 Worker 在业务模块初始化前拒绝更高版本，并在启动阶段验证 v0/v1 schema 契约；启动检查不做全库 integrity 扫描。
- 标准 PowerShell 脚本先在同一备份的隔离恢复副本演练，再升级生产五库，并在所有失败路径尝试恢复服务。

## 自动化验证

```text
10/10 schema migration focused tests passed
6/6 authentication tests passed
9/9 standalone worker tests passed
482/482 backend full regression passed before migration in 152.194s
482/482 backend full regression passed after production v1 migration in 47.187s
18/18 frontend tests passed
Python compileall passed
PowerShell migration script syntax passed
Docker/Compose Backend, Frontend and Worker image builds passed
Base and Worker overlay Compose configuration validation passed
git diff --check passed
```

专项覆盖只读 status、停写/备份门禁、五库 v0→v1、幂等重跑、历史 Memory 列补齐、缺索引修复、残缺列拒绝、事务失败回滚、ledger 篡改与新版本启动拒绝。

真实维护窗口使用备份 `sprint09c2-20260817T002047`：先快照 9 个文件并恢复到隔离目录，演练五库 v0→v1 upgrade/verify 成功后再升级生产数据。生产与演练副本的五库均为 `user_version=1`，ledger version/checksum/application version 有效，SQLite integrity 为 `ok` 且无 foreign-key error。迁移前后业务表摘要一致；唯一运行期变化是 Worker 重启后正常新增一条 `workflow_workers` 注册记录，没有删除或覆盖既有业务数据。

服务恢复后 Backend/Frontend HTTP 200、OpenAPI 版本为 `0.15.0-alpha.36`、Worker 正常注册；生产 v1 上再次执行 Backend 482 项全量回归全部通过。Backend、Frontend、Worker 生产镜像均构建成功。验收记录保存在 `data/sprint09c2_acceptance.json`。

## 后续

Sprint 09C.3：按小说导出 accepted manuscript、规划、必要元数据和可验证 manifest，并保持用户/小说隔离。
