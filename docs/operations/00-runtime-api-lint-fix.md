# 操作报告 00：Runtime API 测试 Lint 修复

日期：2026-07-15

## 问题

`tests/test_runtime_api.py` 的上传样例单行超过 Ruff 配置的 100 字符上限，触发 E501，导致 CI 在安全扫描前停止。

## 处理

- 将 Python 上传样例提取为局部变量 `source`。
- 测试语义和请求内容保持不变。

## 验证

- `python -m ruff check .`：通过。
- 首次修复后 `python -m pytest -q`：`12 passed, 1 warning`。
- 完整开发结束后回归：`17 passed, 1 warning`。

唯一警告来自 FastAPI TestClient 依赖链中的 Starlette/httpx 弃用提示，不影响本次结果。
