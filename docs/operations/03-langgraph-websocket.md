# 操作报告 03：LangGraph 流式编排与 WebSocket 接入

日期：2026-07-15

## 完成内容

- 新增 `LangGraphRuntime`，使用 `StateGraph` 和 `MemorySaver` 构建可恢复的异步执行图。
- 图节点包含 `confirmation_gate`、`runtime`、`runtime_approval_gate`，支持从节点条件路由到结束或下一次人工确认。
- 使用 LangGraph `interrupt()` 暂停人工确认，使用 `Command(resume=...)` 恢复图执行。
- `RuntimeOrchestrator` 改为消费 `graph.astream(..., stream_mode="updates")`，并把节点完成转换为 `server.status`。
- LangGraph 中断转换为现有前端兼容的 `server.interrupt`，审批响应转换为图恢复输入。
- 保留现有 runtime ledger，并将新的 runtime 事件增量镜像到 flow JSONL 账本，避免审批恢复时重复写入。
- WebSocket 协议仍接收 `client.user_message` 和 `client.approval_response`，前端无需改协议。

## 验证

- 原有 WebSocket 普通消息测试通过。
- 原有人工确认中断和恢复测试通过。
- 后端 Ruff 通过，pytest 结果为 `14 passed, 1 warning`。

## 当前边界

- LangGraph checkpoint 当前使用进程内 `MemorySaver`；运行状态本身仍持久化在 `RuntimeLedgerStore`。多进程部署前应切换到共享 checkpoint backend（例如 PostgreSQL 或 LangGraph SQLite checkpointer）。
- 当前图节点把现有 runtime kernel 作为一个可替换节点，工具执行仍由现有 `RuntimeToolBroker` 管理；后续可按规划拆成规划、工具、观察、分析和验证节点。
- WebSocket 连接断开后的恢复依赖服务端仍在运行以及 LangGraph checkpoint 存在；服务重启恢复应在生产 checkpointer 接入后补充。
