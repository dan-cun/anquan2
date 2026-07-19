# SecMind 前端架构

## 1. 目标

前端是原生 Agent、Prompt、MCP、模型和审计能力的操作台。GraphQL 是业务读写主通道；Flow WebSocket 继续承担有序运行事件、审批和断线补放，旧 REST 仅保留尚未迁移的运行与模型接口。

## 2. 分层

```mermaid
flowchart LR
    UI[pages / components] --> FM[features/*/model]
    UI --> FA[features/*/api]
    FA --> GQL[services/graphqlClient]
    UI --> REST[api.js]
    UI --> WS[transport.js]
    GQL --> BFF[/graphql]
    REST --> API[/api/v1]
    WS --> RUN[/ws/flows/:id]
```

| 层 | 路径 | 责任 | 禁止事项 |
|---|---|---|---|
| 组合层 | `src/app/App.jsx` | 应用壳、导航、路由、全局在线状态 | 不实现领域数据转换 |
| 页面层 | `src/app/pages/` | 工作流、审计、Prompt、MCP、模型的操作界面 | 不手写 GraphQL HTTP 细节 |
| 领域层 | `src/app/features/<domain>/` | 领域 Query/Mutation、纯数据派生与输入归一化 | 不依赖 DOM |
| 服务层 | `src/app/services/` | GraphQL 传输、统一错误码 | 不包含页面状态 |
| 运行兼容层 | `api.js`, `transport.js` | REST、Flow WebSocket、游标、重连和审批 | 不包含 React 组件 |
| 展示层 | `app.css` | 统一布局、状态色、响应式约束 | 不通过样式表达业务状态机 |

## 3. 页面与数据所有权

| 页面 | 主数据源 | 实时更新 | 页面状态 |
|---|---|---|---|
| 协作工作台 | GraphQL Agent 网络、REST Flow | Flow WebSocket；GraphQL 轮询回退 | 当前 Flow、草稿、事件游标 |
| 审计回放 | REST Ledger | 手动刷新 | 当前 Flow、选中事件 |
| Prompt 目录 | GraphQL Prompt Query/Mutation | 操作后失效重取 | 当前 Prompt、版本草稿 |
| MCP 与工具 | GraphQL MCP/Tool Query/Mutation | 能力刷新后失效重取 | 注册表单、连接操作 |
| 模型与用量 | REST Model Config/Usage | 手动刷新 | 提供商表单、统计周期 |

服务端持久数据不得复制为前端长期真相。Mutation 成功后重新查询对应目录；Flow 事件以 `run_id + sequence` 去重，WebSocket 重连时用 ledger 游标补放。

## 4. 契约规则

- GraphQL 字段使用 camelCase，错误读取 `errors[0].extensions.code`。
- Prompt 的活动版本由 `activeVersionId` 决定，前端不得自行推断最大版本为活动版本。
- MCP Server 状态使用服务端枚举；本地工具与 MCP 工具都展示在统一工具目录中。
- 所有 URL 从浏览器 origin 和构建环境解析，生产环境默认同源。
- 页面组件只传公开业务数据，不读取密钥、浏览器存储或服务端文件内容。

## 5. 扩展方式

新增业务域时创建 `features/<domain>/api.js` 和 `model.js`，再在 `pages/` 增加页面并由 `App.jsx` 注册路由。共享 transport、错误处理或缓存策略只能进入 `services/`；跨页面的可视组件再提升到 `components/`，避免为了单次复用提前抽象。
