# 操作报告 01：CI 安全门禁与报告输出

日期：2026-07-15

## 完成内容

- CI 固定安装 `agent-audit==0.19.2` 和 `pip-audit==2.10.1`，避免扫描器版本漂移。
- pytest、Bandit、pip-audit、agent-audit 分别输出 JUnit、JSON、JSON、SARIF 报告。
- 无论扫描成功或失败，使用 `actions/upload-artifact@v4` 保存后端报告 30 天。
- agent-audit SARIF 同时上传到 GitHub Code Scanning。
- `agent-audit --fail-on high` 保留非零退出码，高危或严重发现会阻断对应检查。
- 对扫描器在 HTTP client 工厂上的低置信度误报增加了文件级、规则级忽略，并保留审查理由；没有全局关闭 AGENT-026。

## 本地发现

首次运行 agent-audit 0.19.2 时发现 3 项：1 项 critical、1 项 high、1 项 low。通过 WebSocket 空闲超时、HTTPS/地址校验和打包排除配置消除了前两项的实际风险；剩余 HTTP client 工厂误报仅按文件和规则定向忽略。当前扫描应为 0 个未忽略发现；任何其他 high/critical 发现仍会失败。

## GitHub 上传后操作

1. 打开仓库 `Settings > Rules > Rulesets`，新建针对默认分支的 branch ruleset。
2. 启用 `Require a pull request before merging`。
3. 启用 `Require status checks to pass`，选择 workflow 首次运行后出现的必要检查。
4. 至少要求 `Backend lint, tests, and Python security`、`Secret scan`、`CodeQL analysis` 和 `Container build and vulnerability scan`。
5. 建议启用 `Require branches to be up to date`，并禁止绕过规则。
6. 创建一个含已知高危测试样例的临时 PR，确认检查失败且合并按钮被阻断；随后关闭该 PR。

## 验收标准

- Actions 运行结束后可下载 `backend-quality-and-security-reports` 制品。
- Security 页面可读取 `agent-audit` 和 Trivy SARIF。
- agent-audit 发现 high/critical 时后端检查失败。
- branch ruleset 启用后，必要检查失败时 PR 无法合并。

## 当前限制

本机未安装 GitHub CLI，因此没有在本地直接修改远端 branch protection。该设置也必须等 workflow 至少在 GitHub 运行一次，检查名称出现后才能可靠选择。
