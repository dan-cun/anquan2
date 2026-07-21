# SecMind 长期任务能力

状态：implemented
契约版本：`LONG_TERM_CONTRACT_VERSION=1.0`

## 能力边界

- Skill 是可注册、可版本化、按 `run_id/agent_instance_id` 加载的指令资产。后续新增 Skill
  通过 GraphQL `registerSkill` 或管理页完成，无需修改运行时代码。
- Todo 是有优先级、依赖、状态和 Evidence 引用的持久任务项。
- Note 明确区分 `fact/hypothesis/constraint/decision/observation/error`，避免将假设当成事实。
- ContextSnapshot 是不可变结构化压缩结果，保留 `Tools/Endpoints/Findings/Errors/Todos/Notes/Skills`
  和源 Ledger 序号范围；原始 Ledger、工具输出和 Evidence 永不改写。

## 原生 Agent 工具

- `native:skill.list`
- `native:skill.load`
- `native:todo.list`
- `native:todo.create`
- `native:todo.update`
- `native:notes.list`
- `native:notes.record`
- `native:context.compress`

所有异常转换为 `UnifiedToolResult(status=failed)`，不会因一个状态工具异常终止 Agent。
Agent 启动时自动获得可用 Skill 元数据、已加载 Skill 内容、Todo、Notes 和最近 ContextSnapshot。

## 数据库

Alembic `20260720_0004` 创建：

- `skills`
- `skill_loads`
- `task_todos`
- `task_notes`
- `context_snapshots`

Skill 内容以 UTF-8 SHA256 校验。Skill 加载、Todo/Note 变更和上下文压缩同时写入
`runtime_ledger_events`，业务表提供查询，Ledger 提供不可篡改审计。

## GraphQL

Query：`skills`、`skillLoads`、`todos`、`notes`、`contextSnapshots`。

Mutation：`registerSkill`、`loadSkill`、`unloadSkill`、`createTodo`、`updateTodo`、
`recordNote`、`archiveNote`、`compressContext`。

管理页面：`/state`。
