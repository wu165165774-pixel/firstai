# Sprint 09D - CI 与发布工程

## 状态

```text
已完成
目标版本：v0.15.0-alpha.38
基线版本：v0.15.0-alpha.37
```

## 目标

把此前人工执行的回归、Compose、镜像和版本封板门禁固化为 CI/tag Release；生成可离线验证的源码与镜像制品，并明确数据安全优先的升级/回滚流程。

## 实现

- 修复 Backend Compose build context 的 `D:\AI\novel-ai\backend` 主机绑定，统一为跨平台 `./backend`。
- 新增 Backend `.dockerignore`，排除测试/字节码/缓存/数据/日志/本地环境文件，避免污染或放大发布构建上下文。
- PR/master CI 分别执行 Backend 全量测试、Frontend test/build/bundle、两套 Compose config 和三镜像构建。
- tag workflow 重跑完整门禁，生成确定性源码 ZIP、三镜像 gzip、`SHA256SUMS`、Actions artifact 与 GitHub Release。
- 发布校验要求 Backend/Frontend/package-lock 四处版本一致，tag 精确为 `v{version}`，且当前版本至少一份 acceptance 为 PASS。
- 源码制品只收录运行源码、Compose、Dockerfile、运维/Sprint 文档和脚本；manifest 记录 acceptance 的 path/sprint/PASS 摘要但不打包原始验收 JSON，避免生产标识与制品哈希自引用；数据库、向量、密钥、日志、缓存和本地交接文件全部排除。
- `release-manifest.json` 逐成员记录字节数与 SHA-256，ZIP 使用固定排序/时间戳/压缩，独立 verify 拒绝路径穿越、重复成员、未声明成员和内容篡改。
- 升级必须先做 09C.1 备份；回滚前检查旧版本 schema 上限，不兼容时只能恢复隔离验证过的升级前完整备份，不原地覆盖生产数据。

## 当前验证

```text
8/8 release engineering focused tests passed in 0.034s
498/498 backend full regression passed in 141.642s
19/19 frontend tests passed
Python compileall passed
Base and Worker overlay Compose configuration passed after portable-context fix
PowerShell release drill syntax passed
v0.15.0-alpha.37 source release rehearsal passed: 233 files, deterministic SHA-256 1af702e43bbeba0cc865c07a390305b21477f4ea9d98be18b314b1c8b6fb080b
v0.15.0-alpha.38 Backend/Frontend/Worker production image builds passed
Backend image SHA-256: 619ec1bc89995feff710a9c498e12dd6c3610367a03114234eadf96bcec4db6f
Frontend image SHA-256: e9e0d379ab7812c492f983eb29a2cd6b46c02f38515a258af9c3832f5801c869
Worker image SHA-256: 9860cb8200d8c00b21aede47c6e719a93b685b6ff1a5d668f30808bb68a8ae2d
v0.15.0-alpha.38 source release drill passed: 237 files, independently verified and byte-for-byte deterministic
```

`.38` 同版本 acceptance-gated release drill 已独立复验 manifest 和全部成员，并通过二次构建逐字节一致性检查；原始 acceptance 与本地 `AGENTS.md`/`CODEX_HANDOFF.md` 均未进入制品。验收记录保存在 `data/sprint09d_acceptance.json`。GitHub 托管 workflow 只有在提交推送到远端后才会实际运行；本地通过等价命令、工作流内容和制品工具验证其门禁，不伪造远端 run 结果。

## 后续

Sprint 1.0：插件边界、兼容策略、安装/禁用、升级和完整产品验收。
