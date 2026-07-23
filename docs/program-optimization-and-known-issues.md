# SecMind 程序优化方向与已知问题

> 评估日期：2026-07-22
>
> 评估对象：`C:\kaifa\tool\anquan2` 源码与 `http://127.0.0.1:15173` 当前部署
>
> 文档性质：当前状态快照，不替代架构契约、测试报告或发布记录

## 1. 结论摘要

SecMind 已经具备多智能体协作、MCP、统一事件、实时步骤流、独立验证、长期任务状态和 GraphQL 等核心能力，当前主要矛盾已经从“功能是否存在”转为“能否稳定、可恢复、可复现地在真实任务中运行”。

当前最需要处理的四类问题是：

1. 源码、构建镜像和正在运行的版本不一致，部署结果无法从一个确定提交精确复现。
2. 工具运行沙箱未启用，安全工具与 MCP 工具缺少进程级或容器级执行隔离。
3. Agent 图只能恢复持久化记录，不能恢复 inbox、coroutine 和运行中的控制状态。
4. 实际样例中出现 `reflector TypeError` 和 `llm.error` 后，流程仍以“部分完成”结束，失败传播与最终状态语义需要收紧。

前端星空背景已经生效，实时步骤也能够显示。但当前 Agent Network 是横向角色列表，不是能够表达父子委派、通信和实时状态的协作拓扑，尚未达到此前设计的可视化目标。

## 2. 当前基线

### 2.1 已实现能力

| 能力 | 当前状态 |
| --- | --- |
| 多智能体协作 | 已实现 15 个原生角色，以及创建、委派、通信、等待和停止 |
| MCP | 已作为原生工具来源接入；当前 6 个 MCP Server 均为 `connected` |
| 统一工具层 | 当前共 67 个 Native/MCP Tool，使用统一公开定义 |
| 运行事件 | 已实现 `EventEnvelope 1.1`、公开 `DecisionRecord` 和工具唯一终态 |
| 实时与审计 | 已实现实时步骤流、搜索/筛选、审计回放和断线续传基础能力 |
| 稳定性与安全 | 已实现防循环、Circuit Breaker、超时、Scope Guard 和遥测脱敏 |
| 验证 | 已实现独立验证器及 `confirmed/rejected/inconclusive` 三态契约 |
| 长期任务 | 已实现 Skill、Todo、Notes、结构化上下文压缩和 `/state` 管理页面 |
| API | 已实现 GraphQL Query、Mutation、Subscription 契约，同时保留 REST/WebSocket |
| 前端背景 | 星空背景已部署到 `15173` 前端 |

### 2.2 测试与运行状态

最近一次记录的自动化回归结果：

| 测试集 | 结果 |
| --- | ---: |
| 后端 | `184 passed, 1 skipped, 1 warning` |
| 前端 | `26 passed` |
| Benchmark | `29 passed` |

当前运行状态：

| 项目 | 状态 |
| --- | --- |
| 前端 | `http://127.0.0.1:15173`，健康 |
| 主后端 | `http://127.0.0.1:18000`，健康 |
| PostgreSQL | 容器健康 |
| Qdrant | 容器健康，但应用侧 `SECMIND_QDRANT_ENABLED=false` |
| 模型 | DeepSeek 已配置；当前记录模型为 `deepseek-v4-flash` |
| Demo | `SECMIND_RUNTIME_DEMO_MODE=true` |
| 投影 | `SECMIND_PROJECTION_ENABLED=true` |
| 沙箱 | `/api/v1/info` 返回 `sandbox: disabled` |

### 2.3 版本状态

| 对象 | 当前值 |
| --- | --- |
| 源码 Git HEAD | `badca4b1615d472ef800488de78daadb0426e186` |
| 主后端运行提交 | `68874bc3eb3d96ee1169bd2ed69ca88df66dc340` |
| 源码工作树 | `dirty`，30 个变更路径 |
| 主后端镜像标识 | `sha256:432ec8fa43d7c6cfc346cba65d0f2315ba9e63776ec3c0d7072848e933d808e4` |
| 前端镜像标识 | `sha256:93f02d9b90d3adf7a6ca2ab8a45a30cd2a14baba722212b172a551f9d8f1f4d3` |

## 3. 已知问题清单

优先级定义：`P0` 阻碍可信部署或可能产生错误审计结论；`P1` 阻碍完整生产验收；`P2` 影响可维护性、性能或使用体验。

| 编号 | 优先级 | 问题 | 影响与证据 |
| --- | --- | --- | --- |
| ISS-001 | P0 | 源码、镜像和运行版本漂移 | 源码 HEAD 为 `badca4b...`，主后端仍运行 `68874bc...`，前端由脏工作树构建。无法确认某次运行对应的唯一源码、Prompt、模型和 Tool 定义。 |
| ISS-002 | P0 | 工具执行隔离未启用 | `/api/v1/info` 明确返回 `sandbox: disabled`。高风险 CLI、MCP Tool 和第三方依赖与主编排进程之间缺少足够隔离。 |
| ISS-003 | P0 | Agent 运行状态无法完整恢复 | Ledger、Agent 图记录可恢复，但 inbox、Python coroutine 和运行中控制状态不能恢复；重启前的 `RUNNING` Agent 可能变为不可控制的陈旧状态。 |
| ISS-004 | P0 | 失败传播与最终状态不一致 | 当前页面样例中先出现 `reflector TypeError`，随后出现 `llm.error`，但仍产生报告并以“部分完成”结束。若没有明确的降级依据和失败摘要，最终状态会掩盖核心执行失败。 |
| ISS-005 | P1 | 缺少真实端到端生产验收 | 单元与集成测试覆盖较好，但尚无一条可重复证据证明“附件上传到重启恢复”的完整链路在真实 Qwen/DeepSeek、MCP 和数据库上通过。 |
| ISS-006 | P1 | 前端实时事件通道重复 | Workbench/Audit 使用 REST + 手写 WebSocket，管理页使用 GraphQL HTTP，GraphQL Subscription 尚未成为统一实时入口；`App.jsx` 内存在两套重连/心跳逻辑。 |
| ISS-007 | P1 | Agent Network 可视化仍是角色条 | `15173` 当前页面只显示 15 个角色的横向列表，需要横向滚动；不能直观看到实际创建节点、父子委派边、Agent 通信、活跃路径和失败分支。 |
| ISS-008 | P1 | “每一步原因”尚未形成关联链 | 已有公开 `DecisionRecord`，但页面没有稳定展示 `decision -> tool call -> result -> evidence -> finding` 的可展开关系，用户仍需人工跨事件寻找原因和结果。 |
| ISS-009 | P1 | Prompt 科学评测未落地 | 41 个 Prompt 的静态校验已通过，`docs/prompt-validation-plan.md` 已定义 L1-L4；但 `prompt-evals/` 不存在，尚无 Qwen/DeepSeek 重复实验、反事实样例、证据支撑率和幻觉率结果。 |
| ISS-010 | P1 | 长期任务能力缺少跨重启 E2E | Skill/Todo/Notes/ContextSnapshot 已实现且有测试，但尚未证明真实任务中跨进程重启后的回放、恢复和引用一致性。 |
| ISS-011 | P1 | 生产数据库迁移版本证据不足 | `migrate` 容器曾成功退出，但未记录数据库的 `alembic current` 和 `alembic heads` 对照，不能仅凭容器退出码确认 `20260720_0004` 已应用。 |
| ISS-012 | P2 | 前端主包过大 | Vite 构建曾报告约 `676 KB` 和 `939 KB` 主 chunk；Workbench、Audit、管理页、Three.js 与 Ant Design 未充分拆包。 |
| ISS-013 | P2 | Demo 与知识检索仍是开发配置 | `SECMIND_RUNTIME_DEMO_MODE=true`；Qdrant 容器健康但应用未启用，真实 embedding、检索召回和引用链没有生产验收。 |
| ISS-014 | P2 | 依赖告警尚未清理 | 后端存在 Starlette/httpx TestClient 弃用警告；前端构建存在 Ant Design `\"use client\"` 提示和大 chunk 警告。 |

## 4. 优化方向与验收标准

### 4.1 建立可复现发布基线

实施方案：

- 禁止从未记录的脏工作树直接发布生产镜像。
- 每次构建写入完整 Git SHA、dirty 状态、镜像 digest，以及 Prompt/model/tool provenance。
- 后端 `/api/v1/info` 与前端“系统信息”展示同一份 Build Manifest。
- 部署脚本在源码 SHA、镜像标签和运行 manifest 不一致时失败退出。

验收标准：给定任意 `run_id`，能够反查唯一 Git SHA、前后端镜像 digest、Prompt 哈希、模型非敏感配置哈希和 Tool Schema 哈希，并可据此重建相同版本。

### 4.2 为工具执行增加隔离，而不弱化原生能力

MCP 和多智能体继续作为原生能力，不增加不必要的总开关。隔离只作用于执行边界：

- 主编排器只负责决策、授权、事件和状态，不直接执行高风险命令。
- Native Tool 与需要本地执行的 MCP Tool 通过独立 worker/container 运行。
- 每次调用使用临时工作目录、只读输入挂载、有限输出目录和非 root 用户。
- 将 CPU、内存、进程数、网络目标、超时和最大输出量作为 Tool Policy 的运行参数。
- Scope Guard 在执行前校验授权目标，遥测层在持久化前脱敏。

验收标准：工具超时、崩溃、OOM 或恶意退出不能终止 API/Agent 主进程；越权目标在执行前被拒绝；错误仍以模型可见 ToolResult 返回，并产生唯一终态事件。

### 4.3 实现 Agent Recovery Coordinator

实施方案：

- 在 checkpoint 中保存可恢复执行点、父子关系、等待条件、inbox cursor 和 stop intent。
- 服务启动时扫描非终态 Agent，根据 lease/heartbeat 判断 `RESUMABLE`、`STALE` 或 `FAILED_RECOVERY`。
- 只有具备可恢复 checkpoint 的 Agent 才重新调度；其余 Agent 显式终止并记录恢复失败原因。
- 使用幂等 command ID，避免重启后重复发送消息或重复执行 Tool。

验收标准：在 Agent 委派、Tool 调用前后、等待消息和上下文压缩四个位置强制重启，恢复后不得丢消息、重复调用 Tool 或留下永久 `RUNNING` 记录。

### 4.4 收紧运行状态机与降级语义

实施方案：

- 明确 `COMPLETED`、`PARTIAL`、`FAILED`、`CANCELLED`、`INCONCLUSIVE` 的进入条件。
- 核心 Agent、独立验证器或模型调用失败时，必须由显式降级规则决定能否继续。
- 报告必须列出失败步骤、未执行步骤、降级路径和结论覆盖范围。
- 禁止在没有有效证据时把“流程走完”解释为“安全分析成功”。

验收标准：重放当前 `reflector TypeError + llm.error` 场景，最终状态、报告摘要和审计事件三者一致；若允许 `PARTIAL`，报告必须清楚说明哪些结论不可得。

### 4.5 统一前端事件 Store

实施方案：

- 以 `EventEnvelope` 为唯一前端事件模型，统一 `sequence/cursor/correlation_id/causation_id`。
- 抽出单一连接管理器，统一心跳、指数退避、断点续传、去重和乱序处理。
- Workbench、Audit、Agent Graph 和长期任务页面从同一个 Store 派生视图。
- GraphQL Subscription 可作为统一传输层；若短期保留 WebSocket，也必须共享同一连接与归并逻辑。

验收标准：同一事件在所有页面只入库一次；断网 30 秒后自动从最后 cursor 恢复；切换页面不新建重复连接；10,000 条事件回放无顺序错乱。

### 4.6 将 Agent Network 改为真实协作拓扑

实施方案：

- 节点表示实际 `agent_instance`，而不是固定展示全部角色。
- 有向边分别表达 `delegated`、`message`、`waiting` 和 `result`，使用图例区分语义。
- 默认聚焦活跃子图，支持状态/角色筛选、缩放、平移、自动布局和时间回放。
- 选中节点后显示职责、父 Agent、当前任务、最近决策、最近 Tool、Todo 和错误。
- 15 角色目录保留为“可用角色”，与“本次实际实例图”分开。

验收标准：一个包含至少 8 个 Agent、两层委派和一条失败分支的运行，在 1440px 与 390px 视口下均可定位当前活跃节点、父子路径和错误来源，不依赖横向角色条猜测关系。

### 4.7 建立公开理由与证据关联视图

实施方案：

- 为每个 `DecisionRecord` 显示目标、公开理由、候选动作摘要、所选动作和预期结果。
- 使用 `correlation_id` 与 `causation_id` 串联 ToolCall、ToolResult、Evidence、Finding 和 Verification。
- 提供“为什么执行”“执行了什么”“得到什么证据”“如何影响结论”四段式展开视图。
- 不存储、不传输、不展示模型 private chain-of-thought；只展示为审计设计的结构化公开理由。

验收标准：从任一 Finding 可在三次操作内追溯到原始证据和 ToolResult；从任一 ToolCall 可看到触发它的公开决策与后续结论。

### 4.8 建立真实 E2E 与故障注入测试

推荐固定验收链路：

```text
上传授权范围和样本
  -> 创建任务
  -> Root Agent 拆解
  -> 两层 Agent 委派与通信
  -> Native Tool 和 MCP Tool 各至少一次
  -> Todo/Note 更新
  -> Context compress
  -> Independent verifier
  -> 报告生成
  -> Audit replay
  -> 后端重启并恢复
```

必须注入的故障包括：模型超时、无效 JSON、Tool 异常、MCP 断连、重复事件、WebSocket 断线、数据库短暂不可用和后端重启。

验收标准：正常链路全通过；故障链路均产生可解释终态；所有 Finding 均能追溯证据；不得出现重复 Tool 副作用、永久 `RUNNING` 或静默失败。

### 4.9 落地 Prompt 科学评测

实施方案：

- 建立 `prompt-evals/cases`、`fixtures`、`results`、`reports` 和 `candidates`。
- 对 Qwen 与 DeepSeek 使用相同输入、工具、参数、预算和重复次数进行基线测试。
- 覆盖标准、边界、反事实、证据冲突、工具失败和长上下文样例。
- 主要指标使用任务完成率、Tool Schema 合法率、证据支撑率、虚假发现率、恢复成功率、耗时与 Token 成本。
- Prompt 修改只能修复已定位为 Prompt 原因的问题，不能用 Prompt 掩盖状态机或工具层缺陷。

验收标准：所有 L1/L2 确定性测试通过；候选 Prompt 不增加硬失败；至少两种模型、每个核心样例多次运行，证据支撑率不下降且虚假发现率不升高。

### 4.10 验证长期状态和数据库迁移

实施方案：

- 增加 Skill/Todo/Notes/ContextSnapshot 跨重启的真实 PostgreSQL E2E。
- 校验 snapshot 的 source sequence、evidence IDs 和 Agent 引用在恢复后保持一致。
- 部署阶段记录 `alembic current`、`alembic heads` 与迁移镜像 digest。
- 迁移未达到唯一 head 时阻止应用启动或发布。

验收标准：`20260720_0004` 在目标数据库中可验证；相同 `run_id` 重启前后的长期状态内容、顺序和引用一致。

### 4.11 生产配置与性能优化

实施方案：

- 关闭 Demo Mode，并通过真实 DeepSeek/Qwen 场景验收。
- 配置 embedding 后启用 Qdrant，验证召回质量、隔离范围和证据引用。
- 按 Workbench、Audit、管理页拆分路由 chunk，延迟加载 Three.js 和重型组件。
- 清理 Starlette/httpx 弃用告警，固定兼容依赖范围。

验收标准：首屏关键资源和主 chunk 达到团队设定预算；生产环境无 Demo 数据混入；Qdrant 关闭时明确降级、启用时检索结果可追溯；测试运行不再产生已知弃用告警。

## 5. 分阶段路线图

### 阶段 A：可信运行基线（P0）

1. 固化并统一源码、镜像和运行 provenance。
2. 修复失败传播、终态状态机和当前 `TypeError`。
3. 为 Tool/MCP 执行增加 worker/container 隔离。
4. 实现 Agent Recovery Coordinator 的最小闭环。

阶段出口：能够从一个干净提交构建并部署；强制重启和 Tool 故障不会造成错误成功状态、重复副作用或陈旧 Agent。

### 阶段 B：完整产品验收（P1）

1. 建立统一事件 Store 和单一重连机制。
2. 完成实际 Agent 协作拓扑与理由-证据关联视图。
3. 完成真实 E2E、长期状态跨重启和迁移验证。
4. 建立 Qwen/DeepSeek Prompt 评测基线。

阶段出口：用户能够看懂一次任务由谁、因何、调用什么工具、得到什么证据并形成什么结论，且整条链路可重复验证。

### 阶段 C：生产优化（P2）

1. 关闭 Demo Mode，启用并验收知识检索。
2. 拆分前端 bundle，优化长事件列表和大图渲染。
3. 清理依赖告警，建立性能与兼容性预算。

阶段出口：生产配置、性能、依赖和运维证据满足持续发布要求。

## 6. 暂不建议的调整

- 不把 MCP 改成可有可无的外围插件；它继续作为统一工具层的一等来源。
- 不削弱 15 角色协作模型；应区分“角色目录”和“本次运行的 Agent 实例图”。
- 不展示 private chain-of-thought；公开结构化理由已经足够支撑审计和解释。
- 不在版本漂移、状态机和恢复问题解决前继续大规模扩展角色或 Tool 数量。
- 不只凭测试数量宣布生产可用；真实模型、真实数据库、真实 MCP 和故障注入结果才是阶段验收依据。

## 7. 建议持续记录的质量指标

| 维度 | 指标 |
| --- | --- |
| 可靠性 | 任务完成率、恢复成功率、永久非终态数、重复 Tool 副作用数 |
| Agent 协作 | 委派成功率、消息送达率、无进展循环率、平均委派深度 |
| Tool/MCP | Schema 合法率、成功率、超时率、Circuit Breaker 触发率 |
| 科学性 | 证据支撑率、虚假发现率、验证器三态分布、负向基线通过率 |
| 可解释性 | Finding 到 Evidence 可追溯率、Decision 关联完整率 |
| 性能 | 首事件延迟、完整任务耗时、Token/任务、前端主包体积、事件渲染耗时 |
| 可复现性 | 可反查完整 provenance 的运行占比、干净构建占比 |
