# 工作台黑屏修复与 anquan4 对比报告

日期：2026-07-15
分支：`codex/merge-integration`

## 1. 故障现象与日志

复现步骤：

1. 打开 `http://127.0.0.1:15173/workbench?source=feature-entry`。
2. 点击“新建流程”。
3. 后端 `POST /api/v1/flows` 返回 `201 Created`。
4. React 根节点被错误边界卸载，页面只剩黑色背景。

浏览器异常：

```text
TypeError: Failed to construct 'URL': Invalid URL
at buildFlowWebSocketUrl(...)
```

Nginx 和 FastAPI 日志中只有成功的流程创建请求，没有后续 `/ws/flows/{flow_id}`，说明异常发生在浏览器构造 WebSocket URL 时，并非后端执行失败。

根因是 Compose 默认注入：

```text
VITE_API_BASE_URL=/
VITE_WS_BASE_URL=/
```

旧实现会删除 `/` 的尾部斜杠并得到空字符串，随后 `new URL('/ws/flows/...')` 因缺少绝对基地址而抛错。

## 2. 本次代码修改

- `fronted/src/app/transport.js`：使用 `new URL(value, location.origin)` 将 `/` 等相对配置解析为同源绝对 URL；WebSocket 再根据 HTTP 协议切换为 `ws:` 或 `wss:`。
- `fronted/tests/transport.test.js`：增加 Compose 根路径配置回归测试，并验证最终流程 WebSocket URL 是合法绝对地址。

本次修复没有修改后端、数据库、账本、LangGraph 或 Compose 拓扑。

## 3. 修复验证

```text
frontend transport tests: 7 passed
frontend production build: passed
frontend container health: healthy
POST /api/v1/flows: 201 Created
GET /ws/flows/{flow_id}?after_sequence=0: accepted
browser page errors: 0
React #app child count after flow creation: 1
LangGraph node completion messages: 7
final UI state: 流程完成
ledger event count shown by UI: 10
```

Compose 构建曾连续 30 秒没有返回控制台内容。熔断检查显示 Docker Desktop 正常响应且新镜像已经生成；最终构建在 42.2 秒完成，耗时主要来自 Vite 转换 4814 个模块，不是构建死锁。

## 4. 与 anquan4 的代码差异

| 领域 | `anquan4/my-competition-secmind` | 当前 `anquan2` |
|---|---|---|
| LangGraph | 16 个核心节点，直接在单体 Orchestrator 中编排 | 17 个节点，增加前置确认门；运行节点委托给 `RuntimeRunService`，支持依赖注入和 WebSocket 流式更新 |
| Checkpoint | 固定 `InMemorySaver`，重启后依靠账本快照补偿恢复 | `memory/sqlite/postgres` 工厂，FastAPI lifespan 管理异步 checkpointer，命名空间隔离 |
| LLM | 启动时固定 `QwenGateway` | `LLMProviderManager` 支持运行时替换，统一 `SECMIND_LLM_*`，LLM 请求与响应进入账本 |
| 知识库 | Qdrant 适配器存在，但编排中的检索固定返回 0 条 | 可注入 Qdrant 检索；验证后的 episodic memory 写入独立 collection |
| 账本 | JSONL 哈希链和状态快照 | 保留哈希链，并增加 Projection 表、offset、增量 reducer、重建接口和 Alembic 迁移 |
| WebSocket | 后端事件发布为主，无 React 工作台 | `/ws/flows/{flow_id}` 支持输入、审批、断线游标 `after_sequence` 和账本补发 |
| Compose | API、PostgreSQL、Qdrant 三个服务 | frontend/Nginx、backend、migrate、PostgreSQL、Qdrant；带健康检查、只读根文件系统和迁移失败阻断 |
| 前端 | 无 React 工作台 | 对话工作台、人工确认、审计回放、模型配置与同源 Nginx 代理 |

从基线提交 `bdd4ff6` 到持久化集成提交 `7e261ee`，实际修改 23 个文件，共 `441 insertions / 55 deletions`。主要变更集中在 checkpointer 生命周期、Projection 注入、Qdrant 知识服务、WebSocket 游标协议、Compose 迁移服务和相应测试。

## 5. 当前边界

- 本次 Compose 验收使用 `SECMIND_LLM_PROVIDER=null` 和 demo runtime，没有读取真实 Qwen 密钥。
- Qdrant 容器健康，但验收时 `SECMIND_QDRANT_ENABLED=false`；真实向量检索仍需配置 Qwen embedding 密钥后再做端到端验证。
- Vite 构建仍提示大于 500 kB 的 chunk；不影响本次黑屏修复，但后续可按页面拆分动态 import。
- Nginx 代理 WebSocket 时记录了一条重复 `Date` 响应头警告；握手和消息流正常，不是黑屏原因。
