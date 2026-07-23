# 当前融合项目列表

> 本表记录 SecMind（`anquan2`）当前已经原生移植、融合或明确吸收实现方案的上游项目。普通框架、数据库和运行依赖不计入本表。

| 名称 | 功能 | 网址 |
| --- | --- | --- |
| PentAGI | 核心能力主来源：Flow/Task/Subtask 任务分层、15 角色 Agent 协作、Prompt 体系、Agent 委派与消息链、统一工具调用、MCP、审计账本、GraphQL 契约以及工作台结构。相关能力已按 SecMind 数据模型和运行时进行原生实现。 | [vxcontrol/pentagi](https://github.com/vxcontrol/pentagi) |
| Strix | 协作与长期任务能力来源：Agent Graph 的创建、查看、通信、等待和停止；SDK stream 到 Agent/Tool/Status/Result 事件的统一投影；Tool 异常的模型可见错误包装；Skill 按需加载以及 Todo/Notes 长期任务状态。 | [usestrix/strix](https://github.com/usestrix/strix) |
| Xalgorix | 事件、验证与稳定性能力来源：统一事件结构、WebSocket DTO、可筛选 Live Feed、独立验证器三态结论、负向基线与证据检查、防循环 Hook、Circuit Breaker、Scope Guard、遥测脱敏，以及保留 Tools/Endpoints/Findings/Errors 的结构化上下文压缩。 | [xalgord/xalgorix](https://github.com/xalgord/xalgorix) |
| my-competition-secmind（anquan4） | 运行输出与异常处理来源：执行异常收敛为可观察失败状态、结构化 `AgentReport`、工作台业务输出与审计技术事件分离、最终报告写入 Ledger 并支持断线回放，以及前端运行状态同步。当前项目保留了更完整的 PostgreSQL/SQLite checkpointer、Provider Manager、Projection reducer 和 React 工作台。 | [fanjrfan/my-competition-secmind](https://github.com/fanjrfan/my-competition-secmind) |

## 融合边界说明

- “融合”表示能力、契约或实现方案已进入 SecMind，不代表直接复制整个上游仓库。
- MCP 和多智能体协作在 SecMind 中属于原生能力，不作为外围可选插件处理。
- Strix 与 Xalgorix 主要提供设计与实现参考，最终数据模型、事件契约和代码由 SecMind 统一维护。
- 上游项目名称、协议和来源网址应在后续发布物的第三方声明中保留。
