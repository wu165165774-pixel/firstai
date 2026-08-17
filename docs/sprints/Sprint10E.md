# Sprint 10E - 完整产品旅程与 Go/No-Go

## 状态

```text
本地验收通过；Hosted CI/Release 待执行
目标版本：v1.0.0
基线版本：v1.0.0-rc.2
```

## 目标

不再增加业务能力，用一个可重复、可审计的真实本地 Qwen 产品旅程贯穿已发布领域边界，并让正式版准入由机器聚合历史 PASS 与当前旅程证据。把“允许创建正式 tag”和“Hosted 分发已经成功”明确拆开。

## 产品旅程

```text
Novel Project
  -> Story Bible
  -> Canon Entity Alignment
  -> Planner generate (persisted=false)
  -> explicit Plan / Arc / Chapter acceptance
  -> idempotent async Worker Workflow
  -> complete quality gate
  -> Manuscript import candidate
  -> explicit Manuscript acceptance
  -> Memory / Vector / Temporal Graph projection
  -> deterministic Novel export
  -> Backend restart durability
  -> user-scope isolation
```

三次 Planner generation 必须保持 `persisted=false`，固定 Story Arc 和 Chapter Plan 坐标只能经现有 `/planner/accept` 进入领域存储。Workflow 必须通过独立 Worker、幂等 key 和完整质量门；import 不得自动接受正文。事实投影失败可通过既有 retry 修复，但最终必须 completed 且 failed count 为 0。

## Go/No-Go 契约

- `release-readiness.json` 要求 09C.1、09C.2、09C.3、09D、10A、10B、10C、10D、10E 九项 PASS。
- 10E 当前版本 acceptance 必须逐项记录 11 个 required journey check。
- `go-no-go` 缺失任何证据均 fail closed。
- 本地完整门禁通过返回 `local_decision=go`。
- Hosted CI/Release 未执行时分发决策保持 `pending_hosted_release`；不能冒充远程发布完成。
- 稳定版源码 package 在生成前强制复核 Go/No-Go，并在 manifest 写入 readiness 摘要。

## 验收脚本

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\sprint10e_v1_release_drill.ps1
```

若生产配置启用了 Bearer 鉴权，使用 `-AccessToken`；脚本会从 `/auth/me` 采用 token 绑定的用户，并验证伪造的其他用户声明被拒绝。默认最多执行两个独立 Workflow 尝试；失败尝试保留用于审计，不通过删除记录制造成功。

脚本会新增专属 `v1-release-journey-*` 用户和一部验收小说，属于明确的生产验收写入。它不会删除该小说、既有验收、数据库或索引数据；最终记录必须设置 `production_data_modified=true`。

## 当前验证

```text
Version identity: 1.0.0 across five locations
Schema version: unchanged at 1
RC2 -> 1.0 upgrade: direct
1.0 -> RC2 rollback at schema v1: direct
Newer-schema rollback: restore_backup
Readiness requirements: 9 acceptance capabilities / 11 journey checks
PowerShell drill syntax passed
Frontend regression: 21/21 passed
Backend focused regression: Release Engineering 14/14, Dependency Lock 3/3, Schema Migration 10/10, Plugin Catalog 9/9, Plugin Runtime 12/12
Backend full regression: 534/534 passed in 134.334s
Production image locks: Backend 34 packages / Frontend 80 packages
Real product journey: 15/15 passed
Local decision: go
Distribution decision: pending_hosted_release
```

本地正式旅程使用独立用户 `v1-release-journey-20260817T174054` 和小说 `3ae59779-ef4e-47d5-ad9a-3232bd98acbf`。三次 Planner generation 共使用 9168 tokens，均保持 candidate-only 并经显式接受；首次 Workflow 因 `review_parse_failed` 保留为可恢复审计记录，第二次完成完整质量门。Manuscript revision 1 经显式接受后完成 2/2 事实投影；10 文件导出两次字节一致，manifest SHA-256 为 `f98d40b92f7b98868f3fa905543ba83ee92e83490042ac8544eae423c72f3e19`，Backend 重启后仍可读取且跨用户访问被隔离。

本轮构建的 Backend、Frontend、Worker 镜像分别为 `sha256:fcd06025639d2619266e96b331c61985ffe53940a2f6b58a74f6d664a74aeecc`、`sha256:0b62f0ccd32be029ee473a54653fce402891d8b3642189cb0b7e91ff84f462bc`、`sha256:5348bf1f56f05a3ba33304b29e947e0596cdbd922d707aff03714c350bd1179b`。本地 Go/No-Go 已返回 `local_decision=go`；因为 Hosted CI 与 GitHub Release 尚未执行，分发决策仍为 `pending_hosted_release`。

## 非目标

- 不增加数据库表或迁移。
- 不改变 Planner candidate-only、显式接受、stale gate 或 fixed coordinates。
- 不降低 Workflow 质量门以接受失败正文。
- 不把本地演练声明为 Hosted CI/Release。
- 不删除失败尝试、验收小说或已有生产数据。
