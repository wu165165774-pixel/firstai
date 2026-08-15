# Sprint 09B.1 - Provider 能力与配置状态

## 状态

```text
实现与验收已完成，待 commit/tag
目标版本：v0.15.0-alpha.32
基线版本：v0.15.0-alpha.31
```

## 目标与边界

本 Sprint 建立 Provider 配置和可用性边界，不引入 Prompt 持久化，也不新增云厂商适配：

```text
registry registration
  -> immutable capability descriptor
  -> configured state (no network)
  -> explicit bounded health probe
  -> workbench Provider/Model selection
```

Prompt revision 与可审计选择留给 09B.2；OpenAI、Claude、DashScope 适配留给后续 09B 子 Sprint。

## API 合约

`GET /api/v1/providers` 保留原有 `data.providers` 名称列表，并增加 `data.catalog`。默认请求不实例化 Provider、不访问外部网络；`probe=true` 时才并行探测，`timeout_ms` 限制为 100-30000ms。

每项 Catalog 返回：

- `registered`：工厂已注册。
- `configured`：必需配置存在，不代表网络可达。
- `available`：仅探测请求返回布尔值；未探测为 `null`。
- capability：kind、default/supported models、streaming、reasoning efforts、requires_api_key。
- 探测诊断只允许 `not_configured`、`health_check_failed`、`health_check_timed_out`，不返回异常详情、key 或 base URL。

## 配置与兼容

- `QWEN_BASE_URL`、`QWEN_MODEL` 进入 Settings；OpenAI-compatible 路径确定性补全 `/v1`。
- Backend 与外部 Worker Compose 均显式使用 `qwen3:8b` 配置。
- 可选 DeepSeek 继续从不提交的 `backend/.env` 读取 key/base URL/model，避免 Compose 空值覆盖既有配置。
- DeepSeek 空 key 明确报未配置；修复旧代码访问不存在大写属性的问题，并保留合法的 `temperature=0`。
- Registry 的 `register/get/list/contains` 兼容接口保持不变。

## 工作台

单章 Workflow 弹窗加载并探测 Catalog：未配置 Provider 禁用，可用/暂不可用/未探测状态可见，模型来自 capability。Catalog 因鉴权或网络暂不可访问时仍回退为原有文本输入，不阻断兼容流程。

## 验证

```text
7/7 Provider focused tests passed
4/4 Qwen reasoning tests passed
16/16 frontend tests passed
447/447 backend full regression passed in 98.357s
Python compileall passed
Docker Compose base + worker overlay config passed
git diff --check passed
Frontend production image built successfully
Frontend root / healthz / API proxy returned HTTP 200
OpenAPI version = 0.15.0-alpha.32
Provider query parameters = probe, timeout_ms
qwen_local configured = true, available = true, model = qwen3:8b
deepseek configured = true, available = false, health_error = health_check_failed
```

DeepSeek 的运行结果只证明配置与可用状态能够被正确区分；本 Sprint 不宣称 DeepSeek 在线调用验收通过。验收全过程未打印或写入任何 key，也未删除既有业务/验收数据。

## 后续

Sprint 09B.2：Prompt revision、选择策略与调用链审计。
