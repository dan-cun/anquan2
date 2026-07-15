# 操作报告 05：模型配置前后端协作

日期：2026-07-15

## 完成链路

```text
前端读取后端配置
  -> 提交候选 Provider、模型、Base URL 和可选新密钥
  -> 后端验证输入和密钥复用边界
  -> 候选 Provider 执行最小连接测试
  -> 测试成功后加锁替换当前 Provider
  -> 新运行使用当前 Provider 生成审计摘要
  -> LLM request/response 写入运行账本
  -> 前端读取账本聚合用量
```

## API

- `GET /api/v1/model-config`：读取脱敏配置，只返回 `api_key_configured`。
- `PUT /api/v1/model-config`：默认测试候选连接，成功后热替换。
- `POST /api/v1/model-config/test`：只测试候选配置，不替换当前 Provider。
- `GET /api/v1/model-usage`：聚合请求数和 prompt/completion/total tokens。

## 密钥规则

- API 响应、运行账本和浏览器 localStorage 均不保存或返回密钥原文。
- Provider 或 Base URL 变化时必须提交新密钥，禁止把旧端点密钥发送到新端点。
- 仅在 Provider 和 Base URL 不变时允许留空并复用后端当前密钥。
- 热更新密钥只保存在后端进程内；服务重启后重新读取 `.env` 或密钥文件。
- 模型配置测试和更新写入 `system-model-config` 哈希链，只记录非敏感元数据。

## 主执行链

- `RuntimeRunService` 通过 `LLMProviderManager` 获取当前 Provider。
- 已配置模型时，使用结构化且已验证的发现生成中文执行摘要。
- 模型失败、返回空内容或超出预算时使用确定性摘要，不使安全任务整体失败。
- denied/failed 任务不调用外部模型。

## 用量

- 从 `llm.response.raw.usage` 读取 OpenAI-compatible usage。
- 支持 `prompt_tokens/completion_tokens` 和 `input_tokens/output_tokens` 字段。
- 当前未配置模型价格，因此 `estimated_cost` 返回 `null`，避免展示错误费用。

## 测试安全修正

测试期间发现测试 Settings 仍可能继承本地 `.env` 密钥，并在更换 Base URL 时复用。现已显式隔离测试密钥，并增加端点变化时强制新密钥的规则。由于修正前曾向测试 URL 发出一次携带现有模型 Authorization 头的请求，应轮换当时 `.env` 中的模型 API Key。
