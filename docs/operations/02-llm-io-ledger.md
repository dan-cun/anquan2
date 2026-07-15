# 操作报告 02：LLM I/O 账本封装

日期：2026-07-15

## 完成内容

- 新增 `LedgerLLMProvider` 装饰器，保持原有 `LLMProvider.complete()` 调用方式。
- 调用时传入 `run_id` 后，依次记录 `llm.request` 和 `llm.response`。
- 上游异常时记录 `llm.error` 后重新抛出异常，避免失败调用被误记为成功。
- 请求消息、模型参数、响应正文、原始响应和异常信息都进入运行账本。
- 复用 `RuntimeLedgerStore.redact()` 脱敏密钥字段和 Bearer token，并继续使用哈希链校验。
- 在应用服务装配时自动包装已配置的 Qwen/OpenAI-compatible provider。

## 调用约定

```python
response = await services.llm_provider.complete(
    messages,
    run_id=state.run_id,
)
```

`run_id` 是账本关联所需的上下文；未传入时仍可调用模型，但不会写入运行账本，适合健康检查或独立配置测试。

## 验证

- 新增成功响应和异常路径测试。
- 验证请求参数中的 `api_key`、响应中的 Bearer token、异常文本中的 Bearer token均被替换为 `[REDACTED]`。
- 验证 request/response 或 request/error 事件的哈希链均有效。
