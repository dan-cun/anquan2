# anquan4 运行输出合并核查报告

日期：2026-07-15

## 故障根因

- DeepSeek 配置和连接测试成功，后端访问 `api.deepseek.com/chat/completions` 返回 `200 OK`。
- 工作台输入“你好”时，`TaskRequest.objective` 的最小长度为 3，Pydantic 抛出校验异常。
- 异常没有在 WebSocket 用户消息分支中收敛为 `server.error`，连接直接中断。
- 工作台把 `runtime.*` 账本事件名直接显示为消息正文，真实的 `server.done.report` 不够突出。
- 完成报告没有写入 Flow JSONL，断线重连只能恢复技术事件，不能恢复最终输出。

## 与 anquan4 的取舍

采用的设计：

- 参考 `RunService._start()`，将执行异常收敛为失败状态和可观察事件。
- 保留结构化 `AgentReport`，以 `executive_summary` 作为工作台最终回答。
- 保留事件发布和账本回放分离，工作台展示业务输出，审计页展示完整技术事件。

没有直接覆盖的实现：

- anquan4 同样要求 objective 至少 3 字符，不适合短中文输入。
- anquan4 使用 `InMemorySaver`，当前项目继续使用可注入 PostgreSQL/SQLite checkpointer。
- anquan4 使用启动时固定 Qwen Gateway，当前项目继续使用可热切换 Provider Manager。
- anquan4 没有 Projection reducer 和 React 工作台，当前实现继续保留这些能力。

## 合并结果

- objective 接受任意非空 Unicode 文本，并在校验前去除首尾空白。
- WebSocket 捕获任务校验和执行异常，返回结构化 `server.error` 并更新 Flow 状态。
- LangGraph 节点在工作台显示为中文进度，不再显示事件类型占位符。
- `server.done` 显示模型生成的报告正文和限制项。
- 完成结果写入 `flow.completed`，刷新或断线后仍可从账本恢复。
- 前端根据流式事件同步 `running/waiting/finished/failed`，不再长期停留在 RUNNING。
- 未配置模型时返回包含原始任务和下一步建议的中文说明，不伪造安全发现。

## 验证

```text
backend full tests: 64 passed, 1 skipped
focused backend tests: 12 passed
frontend tests: 9 passed
Ruff: passed
frontend production build: passed
Compose frontend/backend/PostgreSQL/Qdrant: healthy
short Chinese input: server.done is terminal event
report payload: present
flow.completed: persisted in ledger
deployed Unicode regression: result length 300, Flow status finished
backend errors after deployment: none
```

Compose 重启会清除模型页面仅保存在内存中的 API Key。真实 DeepSeek 输出验收前，需要操作者在“模型与额度”页面重新验证并应用密钥。
