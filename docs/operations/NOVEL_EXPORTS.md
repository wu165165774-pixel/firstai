# 小说导出运维说明

## API

```text
GET /api/v1/novels/{novel_id}/export
Content-Type: application/zip
```

启用鉴权时必须提供资源所有者或管理员的 Bearer token。其他用户请求按既有资源隐藏规则返回 HTTP 404。

响应头：

- `Content-Disposition`：建议下载文件名。
- `X-NovelForge-Manifest-SHA256`：`manifest.json` 原始字节的 SHA-256。
- `X-NovelForge-Export-Files`：ZIP 成员总数，包含 manifest。
- `X-NovelForge-Accepted-Chapters`：包内 accepted manuscript 章节数。

## 包格式 v1

```text
manifest.json
project.json
planning/story_bible.json
planning/entities.json
planning/novel_plan.json
planning/story_arcs.json
planning/chapter_plans.json
manuscript/index.json
manuscript/accepted.md
manuscript/chapters/000001.md
...
```

`manifest.json` 的 `files` 数组列出 manifest 之外每个成员的相对路径、字节数和 SHA-256。`manuscript/index.json` 记录接受 revision、原始正文 hash，以及 Project/Bible/Plan/Arc/Chapter Plan 来源 revision。

正文选择固定为 `accepted_only`。未接受候选、草稿、superseded revision、Memory、External Knowledge、Temporal Graph、Provider 密钥和服务器配置不导出。

## 一致性与失败语义

- 导出只读，不创建数据库记录或服务器端持久文件。
- 相同权威快照使用固定成员顺序、ZIP 时间戳与 JSON 编码，产生相同 archive bytes。
- 服务在组包前后比较 Project、Bible、Plan、Entity、Arc、Chapter Plan 和 Manuscript 聚合 revision 指纹；并发变化返回 HTTP 409，客户端可安全重试。
- accepted Manuscript 内容必须匹配冻结的 `content_hash`，否则返回 HTTP 500 且不交付损坏包。
- 导出不是数据库备份，也不能替代 Sprint 09C.1 的离线恢复快照。

## 生产验收

从仓库根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\sprint09c3_export_drill.ps1
```

启用鉴权时通过参数传入 token；脚本不会输出 token：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\sprint09c3_export_drill.ps1 -AccessToken $token
```

脚本自动选择一个已有 accepted manuscript 的小说，也可用 `-NovelId` 指定。它通过真实 HTTP 下载两次、验证所有成员长度与 SHA-256、验证响应 manifest hash 和 archive 确定性，并在 `finally` 删除两个临时 ZIP。
