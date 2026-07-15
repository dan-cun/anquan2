# 操作报告 04：最终验证

日期：2026-07-15

## 后端

- Ruff：通过。
- compileall：通过。
- pytest：`21 passed, 1 warning`。
- Bandit：退出码 0，0 个发现。
- agent-audit 0.19.2：退出码 0，0 个未忽略发现，1 个经审查的定向忽略。
- pip-audit 2.10.1：退出码 0，0 个已知漏洞。
- GitHub Actions workflow：YAML 解析通过。

## 前端

- `fronted`：Vite 生产构建通过。
- `frontend`：TypeScript 和 Vite 生产构建通过。
- `fronted` 存在 Ant Design `use client` 和大于 500 kB chunk 的非阻断警告，可在后续性能优化阶段进行路由级拆包。

## 未执行的远端操作

- 没有提交或推送代码。
- 没有配置 GitHub branch protection/ruleset。
- 原因：该步骤应在 workflow 上传并至少运行一次、GitHub 生成检查名称后执行；本机也未安装 GitHub CLI。

## 上传后的验收顺序

1. 推送分支并创建 PR。
2. 确认 `Security Gates` workflow 完整运行。
3. 下载并检查 `backend-quality-and-security-reports`。
4. 在仓库 ruleset 中将必要检查设为 required。
5. 用临时高危样例 PR 验证门禁确实阻止合并。
