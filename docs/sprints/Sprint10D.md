# Sprint 10D - RC 依赖锁定与升级/回滚矩阵

## 状态

```text
已完成
目标版本：v1.0.0-rc.2
基线版本：v1.0.0-rc.1
```

## 目标

消除同一 RC 因 Python 解析、基础镜像或 CI Action 可变引用而产生的构建漂移，并把升级/回滚兼容从文字约定提升为 fail-closed 的机器契约和隔离实机探针。

## 实现

- 从已验收 RC1 生产镜像采集 34 个 Backend Linux/Python 3.12 运行时包，形成精确、唯一、排序的 `requirements.lock`。
- Backend/Worker Docker 与 CI/Release workflow 只安装 lock 并执行 `pip check`；`pyproject.toml` 保留声明范围，不再承担生产求解。
- Frontend lockfile v3 的 80 个 registry 包必须具备 version/resolved/integrity，继续通过 `npm ci` 安装。
- Python、Node、Nginx、Ollama 四个镜像来源固定 digest；9 个 GitHub Action 固定完整 commit。
- Release Engineering 校验 lock、直接依赖覆盖、兼容入口、镜像 digest、Action commit、Frontend integrity 与生产 Dockerfile 安装语义。
- 新增镜像内 runtime lock 对照，缺失、多余或版本不匹配均返回稳定错误且失败。
- 新增 `release-compatibility.json` 与 `assess` CLI；同 schema 明确路径可 direct，未知路径 blocked，超过旧版本 schema 上限必须 restore_backup。
- live drill 先做离线备份和隔离恢复，再用 RC1 镜像打开隔离 schema v1；旧版本不会接触生产数据目录。

## 验收结果

```text
Backend dependency lock: 34 packages
Frontend dependency lock: 80 packages with integrity
Digest-pinned images: 4
Commit-pinned GitHub Actions: 9
12/12 release engineering focused tests passed
3/3 dependency runtime lock tests passed
10/10 schema migration focused tests passed
21/21 frontend tests passed
532/532 backend full regression passed in 128.364s
Python compileall passed
Both Compose configurations passed
git diff --check passed
Backend / Frontend / Worker production images built
Dependency and rollback live drill passed
```

Backend 与 Worker 镜像内安装集均与 34 包 lock 精确一致，无缺失、多余或版本偏差。离线备份 `sprint10d-20260817T160013` 覆盖 9 个文件，并将 9 个文件恢复到隔离目录；保留的 RC1 Backend 在隔离 schema v1 上启动并返回 HTTP 200，随后 RC2 Backend、Frontend 和 Worker 均保持健康。

三镜像分别为 Backend `43ee7fb5...53fa`、Frontend `0b62f0cc...62bc`、Worker `f801cc6c...2b29`。清理复验确认 RC1 探针已删除，Backend HTTP 200、Worker running。验收记录保存在 `data/sprint10d_acceptance.json`。

## 非目标

- 不升级任何已经验收的 Python 或 Frontend 包。
- 不改变 schema v1、业务表、插件权限或领域模型。
- 不把旧版本 Backend 指向生产数据目录进行破坏性试跑。
- 不声称未知版本天然兼容；未列入矩阵的路径必须阻断。

## 后续

本 Sprint 已通过完整本地门禁，可封板 `v1.0.0-rc.2`。下一阶段执行端到端产品旅程、发布候选缺陷清零和正式 `v1.0.0` Go/No-Go，不再新增大范围业务能力。
