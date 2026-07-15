# 模型 Provider 扩展操作报告

日期：2026-07-15

## 完成内容

- 前端新增 Qwen、DeepSeek、OpenAI、Moonshot/Kimi、智谱 GLM、SiliconFlow 和自定义 OpenAI-compatible 选项。
- 选择具名厂商后自动填写推荐模型与 Base URL，自定义兼容接口保持手动输入。
- 后端模型配置 Schema 接受对应的具名 Provider。
- Provider 工厂继续复用 OpenAI-compatible 客户端，但账本和用量统计保留真实厂商名称。
- API Key 保持只写不读，不进入 localStorage、响应或配置审计事件。

## 构建问题与处理

- Docker Desktop 未配置 HTTPS 代理时无法访问 Docker Hub。
- `host.docker.internal:7897` 在当前主机不可达，改用 `127.0.0.1:7897` 后 Docker Hub 元数据读取成功。
- 后端 Dockerfile 将依赖安装拆成独立缓存层，并收紧 LangGraph 到已验证的 `1.2.x` 兼容范围。
- 移除不必要的 pip 自升级，依赖下载使用 120 秒超时和 5 次重试。

## 验证结果

```text
frontend tests: 8 passed
frontend production build: passed
backend tests: 62 passed, 1 skipped
backend Ruff: passed
model-focused backend tests: 16 passed
Docker Hub metadata: passed
backend image build: passed in 10.7 seconds with cached dependencies
frontend/backend/PostgreSQL/Qdrant: healthy
OpenAPI provider enum: qwen, dashscope, deepseek, openai, moonshot, zhipu,
  siliconflow, openai-compatible
deployed frontend bundle: contains all named provider presets
```

真实模型连接未在本次自动验收中执行，因为 API Key 由操作者在页面中填写。无密钥的 DeepSeek 更新请求已到达业务校验并返回 `A model API key is required`，证明新 Provider 已贯通前后端协议。
