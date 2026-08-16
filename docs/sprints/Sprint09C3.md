# Sprint 09C.3 - 小说导出

## 状态

```text
实现、自动化回归、生产构建与真实 HTTP 导出验收均已完成
目标版本：v0.15.0-alpha.37
基线版本：v0.15.0-alpha.36
```

## 目标与边界

按用户/小说边界提供便携、可读、可验证的 ZIP，导出当前规划与 accepted manuscript。导出只读，不承担数据库备份/恢复，不包含候选正文、Memory、External Knowledge、Temporal Graph、Provider 配置或密钥。

## 实现

- 新增 `GET /api/v1/novels/{novel_id}/export` 与 Vue 工作台下载入口。
- 包含 Project、Story Bible、Canonical Entities、Novel Plan、Story Arcs、Chapter Plans、accepted 章节 Markdown、合并正文和来源 revision index。
- 只遍历 accepted revision；草稿、superseded 与未接受候选没有导出路径。
- manifest v1 为每个 payload member 记录精确字节数与 SHA-256；响应头提供 manifest 自身 SHA-256。
- 固定 ZIP 时间戳、成员排序与 canonical JSON，使同一 authority 快照字节级确定。
- 导出前后比较所有相关聚合 revision 指纹，并发变化 HTTP 409；接受正文 hash 异常 fail closed。
- 所有查询限定同一 `novel_id`；既有 Bearer 中间件继续隐藏其他用户小说。
- 生产 drill 通过真实 HTTP 双下载复算全部成员，并始终清理临时文件。

## 当前验证

```text
7/7 novel export focused tests passed in 4.009s
7/7 authentication tests passed in 4.280s
490/490 backend final full regression passed in 143.521s
19/19 frontend tests passed
Python compileall passed
PowerShell export drill syntax passed
Base and Worker overlay Compose configuration validation passed
Backend, Frontend and Worker production image builds passed
git diff --check passed
```

真实生产 drill 对小说 `e872414f-8e9b-48fb-95a1-1da63dc8a0e6` 通过 HTTP 下载两次：每包 11 个成员、包含 2 章 accepted manuscript；manifest SHA-256 为 `24567e614930604c1c9eb45a3e9992742bbf351899f6d1f8655095f55b5cfcbf`。所有成员的长度与 SHA-256 均复算一致，两次 archive bytes 完全相同，临时 ZIP 在 `finally` 清理。Backend HTTP 200、OpenAPI 为 `0.15.0-alpha.37` 且导出路由已注册；Frontend `.37` 镜像重建后 HTTP 200，生产 bundle 已确认包含“导出小说”入口。验收记录保存在 `data/sprint09c3_acceptance.json`。

## 后续

Sprint 09D：CI、发布制品、升级/回滚清单与自动发布门禁。
