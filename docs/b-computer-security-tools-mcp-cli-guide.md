# SecMind 双机工具节点部署与接入指南

本文档供一台没有历史聊天记录的 B 电脑独立使用。它说明 SecMind 的设计方向，以及如何在 B 电脑安装网络安全 CLI、将 CLI 封装为 MCP Server，并让 A 电脑上的 SecMind 调用这些工具。

## 1. 项目和机器角色

主项目目录：

```text
C:\kaifa\tool\anquan2
```

推荐分工：

| 机器 | 角色 | 主要内容 |
| --- | --- | --- |
| A 电脑 | SecMind 控制平面 | 前端、GraphQL、Agent 网络、Prompt、PostgreSQL、LangGraph Checkpoint、Runtime Ledger、Qdrant、MCP Client |
| B 电脑 | 安全工具执行节点 | Nmap、Nuclei、Semgrep、Ghidra、pwntools 等 CLI，以及将它们暴露为 Tools 的 MCP Server |

```mermaid
flowchart LR
    User["用户 / 操作员"] --> UI["A: SecMind 工作台"]
    UI --> Agents["Prompt + 多智能体协作网络"]
    Agents --> Gateway["Unified Tool Gateway"]
    Gateway --> Native["A: Native Tools"]
    Gateway --> MCPClient["A: MCP Client Manager"]
    MCPClient -->|"Streamable HTTP / SSE"| MCPServer["B: MCP Server"]
    MCPServer --> CLI["B: 安全 CLI / 容器 / 桌面工具"]
    Gateway --> Ledger["PostgreSQL Runtime Ledger"]
    Agents --> Checkpoint["LangGraph Checkpoint"]
    Ledger --> GraphQL["GraphQL / WebSocket / Live Feed"]
```

B 电脑不是第二套 SecMind，也不负责保存主业务数据。它是可独立扩容、可替换的工具节点。

## 2. SecMind 的设计方向

### 2.1 Prompt 是可版本化资产

项目以 PentAGI 的 Prompt 和角色拆分为基础，把 Prompt 从代码常量提升为可导入、可修改、可启用版本的资产。每次 Agent 运行保留 Prompt 版本标识，便于复现结果。

### 2.2 多智能体负责决策和协作

系统不是把所有能力塞进一个 Agent。主 Agent 可以委派给不同角色，Agent 之间有实例、任务、消息链、委派关系、等待/恢复、停止和完成状态。Loop Guard 用于发现无效重复，独立 Verifier 用另一 Agent 实例复核关键结果。

### 2.3 Native 和 MCP 使用统一工具契约

工具无论来自 A 电脑本地实现还是 B 电脑 MCP Server，最终都转换为统一的：

- `UnifiedToolDefinition`：名称、说明、来源、输入 JSON Schema、输出 Schema。
- `UnifiedToolInvocation`：run、flow、Agent、tool ID、结构化参数。
- `UnifiedToolResult`：完成、失败、超时、取消或阻止，以及文本、结构化数据、Artifact、Evidence。

工具调用统一经过 Gateway，写入同一套事件和数据库，不为每种工具另造一条运行链。

### 2.4 持久化职责分离

| 存储 | 职责 |
| --- | --- |
| PostgreSQL | Flow、Agent、工具、Prompt、Evidence、事件等可查询业务事实 |
| Runtime Ledger | 按 `run_id + sequence` 排序的不可变审计事件 |
| LangGraph Checkpoint | 中断、审批和执行恢复，不作为审计事实源 |
| Qdrant | 可复用知识和向量检索，不替代业务数据库 |

### 2.5 时序化处理以事件为事实源

系统吸收了 Strix/XAllgorix 一类长任务和时序处理思路：决策、委派、工具开始、工具终态、验证、等待、恢复、报告都形成有顺序和因果关联的事件。前端断线后通过游标回放，不以消息到达时间代替业务顺序。

### 2.6 工具能力默认属于运行时

MCP 和多智能体不是外挂页面，而是原生运行能力。管理页用于注册、观察和维护，Agent Runtime 与 GraphQL 共享同一个 MCP Manager 和 Unified Tool Gateway。

当前需要注意：MCP 的连接、发现、目录展示和调用网关已经实现，但动态 `tool_gateway.definitions()` 还需要完整注入每次模型上下文，才能让模型可靠地自主选择刚发现的陌生 Tool ID。B 电脑可以先完成工具和 MCP 部署，最终 Agent 自主调用验收应在该项完成后进行。

## 3. 接入方式选择

| 工具现状 | 推荐方式 | 原因 |
| --- | --- | --- |
| 已提供 Streamable HTTP MCP | A 直接连接 B 的 `/mcp` | 最适合双机、连接稳定、便于刷新能力 |
| 只提供旧 SSE MCP | A 连接 B 的 `/sse` | 兼容已有 Server，不建议新项目首选 |
| 只有 CLI | 在 B 用 Python/TypeScript MCP 包装 CLI | Agent 获得结构化 Schema 和结果 |
| MCP 只支持 stdio | 在 A 本机运行，或由 A 通过 SSH 启动 B 上的 stdio Server | stdio 本身没有网络监听 |
| 少量 A 本地固定命令 | 编写 SecMind Native Tool | 不需要独立 MCP 进程，但修改主程序 |
| 只有网页/API | 优先使用官方 API MCP；没有时再写轻量 MCP Adapter | 避免网页抓取代替稳定 API |

双机环境首选 **Streamable HTTP**。不要把一个普通 CLI 的 TCP 端口误认为 MCP；A 电脑需要连接的是实现 MCP `initialize`、`tools/list` 和 `tools/call` 的 Server。

## 4. B 电脑目录规范

Windows 示例：

```text
C:\security-tools\bin\              # 独立 CLI
C:\security-tools\packages\         # 解压的软件包
C:\security-mcp\servers\            # 自编或第三方 MCP Server
C:\security-mcp\venvs\              # Python 虚拟环境
C:\security-mcp\config\             # 非敏感配置
C:\security-mcp\logs\               # 运行日志
C:\security-workspaces\              # 每次任务的输入和输出
```

Linux 示例：

```text
/opt/security-tools/
/opt/security-mcp/servers/
/opt/security-mcp/venvs/
/etc/security-mcp/
/var/log/security-mcp/
/srv/security-workspaces/
```

原则：

1. 工具、MCP Server、任务输出和密钥分开存放。
2. 每个 Python MCP Server 使用独立虚拟环境；Node Server 固定 lockfile。
3. GUI 工具和 CLI 依赖不要复制进 SecMind 仓库。
4. 记录版本、来源、许可证和安装命令。
5. 密钥只放环境变量或 B 电脑的密钥服务，不写入 Git 和 MCP 返回值。

现有候选工具见 [公开安全工具与 MCP 目录](./public-security-tools-mcp-catalog.md)。不要一次安装全部工具，先按使用频率和依赖大小分批部署。

## 5. CLI 安装和登记流程

每个 CLI 按同一流程处理：

1. 从官方仓库、官方 Release、系统包管理器或可信镜像获取。
2. 校验发布者、版本和哈希；保存许可证信息。
3. 安装到固定目录或独立容器。
4. 执行 `--version`、`--help` 和一个无副作用样例。
5. 确认退出码、标准输出、标准错误和输出文件位置。
6. 确定调用超时、并发能力、输入类型和结果解析方式。
7. 决定直接使用已有 MCP，还是编写 CLI Wrapper。

建议为每个工具维护以下登记表：

| 字段 | 示例 |
| --- | --- |
| `tool_id` | `btools:nmap_service_scan` |
| 类别 | Web / 密码学 / Pwn / Misc / 逆向 / 取证 |
| 来源与版本 | 官方 URL、Git commit 或 Release tag |
| CLI 路径 | `C:\security-tools\bin\nmap.exe` |
| 版本检查 | `nmap --version` |
| MCP Server | `b-security-tools` |
| MCP Tool name | `nmap_service_scan` |
| 输入 Schema | target、ports、scan type、timeout |
| 输出 | JSON 摘要、原始文件 Artifact、Evidence 引用 |
| 超时 | 例如 300 秒 |
| 并发 | 可并发数量或必须串行 |
| 密钥 | 环境变量名称，不登记真实值 |
| 许可证 | 名称和再分发限制 |

## 6. 把 CLI 封装为 MCP Tool

下面是一个最小 Python 示例。它展示的是封装结构，不要求所有工具都放在同一个 Server 中。

### 6.1 创建环境

Windows PowerShell：

```powershell
py -3.11 -m venv C:\security-mcp\venvs\b-security-tools
C:\security-mcp\venvs\b-security-tools\Scripts\python.exe -m pip install --upgrade pip
C:\security-mcp\venvs\b-security-tools\Scripts\python.exe -m pip install "mcp[cli]>=1.12,<2"
```

Linux：

```bash
python3.11 -m venv /opt/security-mcp/venvs/b-security-tools
/opt/security-mcp/venvs/b-security-tools/bin/python -m pip install --upgrade pip
/opt/security-mcp/venvs/b-security-tools/bin/python -m pip install 'mcp[cli]>=1.12,<2'
```

### 6.2 Server 示例

文件：`b_security_tools.py`

```python
from __future__ import annotations

import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("B Security Tools", host="0.0.0.0", port=9000)
NMAP = os.environ.get("BTOOLS_NMAP", "nmap")
WORK_ROOT = Path(os.environ.get("BTOOLS_WORK_ROOT", "./workspaces")).resolve()


@mcp.tool()
def nmap_service_scan(target: str, ports: str = "1-1000", timeout_seconds: int = 300) -> dict:
    """Identify services on an explicitly supplied target and TCP port range."""
    task_dir = WORK_ROOT / "nmap"
    task_dir.mkdir(parents=True, exist_ok=True)
    output_file = task_dir / "latest.xml"
    command = [NMAP, "-sV", "-p", ports, "-oX", str(output_file), target]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(1, min(timeout_seconds, 1800)),
        check=False,
        shell=False,
    )
    parsed: list[dict] = []
    if output_file.exists():
        try:
            root = ET.parse(output_file).getroot()
            for host in root.findall("host"):
                address = host.find("address")
                host_ports = []
                for port in host.findall("./ports/port"):
                    state = port.find("state")
                    service = port.find("service")
                    host_ports.append({
                        "protocol": port.get("protocol"),
                        "port": int(port.get("portid", "0")),
                        "state": state.get("state") if state is not None else None,
                        "service": service.get("name") if service is not None else None,
                        "product": service.get("product") if service is not None else None,
                        "version": service.get("version") if service is not None else None,
                    })
                parsed.append({
                    "address": address.get("addr") if address is not None else None,
                    "ports": host_ports,
                })
        except (OSError, ET.ParseError, ValueError):
            parsed = []
    return {
        "ok": completed.returncode == 0,
        "exit_code": completed.returncode,
        "command": command,
        "stdout": completed.stdout[-20000:],
        "stderr": completed.stderr[-12000:],
        "data": parsed,
        "artifact_path": str(output_file) if output_file.exists() else None,
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

Nmap 使用 XML 输出，再由 XML Parser 转成结构化数据。不要用正则表达式解析复杂 XML/JSON，也不要通过 `shell=True` 拼接模型提供的字符串。

启动：

```powershell
$env:BTOOLS_NMAP='C:\security-tools\bin\nmap.exe'
$env:BTOOLS_WORK_ROOT='C:\security-workspaces'
C:\security-mcp\venvs\b-security-tools\Scripts\python.exe C:\security-mcp\servers\b_security_tools.py
```

正常情况下 Streamable HTTP 地址为：

```text
http://B电脑地址:9000/mcp
```

### 6.3 Wrapper 设计要求

- 一个 MCP Tool 对应一个清晰动作，不要暴露“任意 shell 命令”作为通用 Tool。
- 参数使用类型明确的 JSON Schema，不把全部参数塞进一个字符串。
- `subprocess.run` 使用参数数组和 `shell=False`。
- 返回退出码、结构化数据、截断后的 stdout/stderr 和 Artifact 路径。
- 长输出写文件，返回摘要和 Artifact，不把几十 MB 文本塞进模型上下文。
- B 电脑本地路径对 A 电脑不可直接读取。正式实现应返回经过认证的下载 URL、MCP Resource URI，或由独立 Artifact 服务传输文件；不要把 `C:\...` 或 `/srv/...` 字符串直接当成 A 端 Artifact。
- 超时后结束子进程，并返回明确的 timed-out 结果。
- 不把 token、cookie、Authorization Header 或私钥写进日志和返回值。
- 不同运行实例使用独立工作目录，避免覆盖 `latest.xml`；上例为最小演示，生产实现应以 invocation ID 建目录。

## 7. B 电脑对外提供 MCP

### 7.1 私网方式

推荐顺序：

1. 同一可信局域网，通过固定私网 IP 连接。
2. WireGuard/Tailscale 等组网，使用组网 IP。
3. 公网域名 + TLS 反向代理 + 身份验证。

不要直接把无认证的 `0.0.0.0:9000` 暴露到公网。若只在组网网络使用，B 防火墙只允许 A 电脑的 IP 访问该端口。

### 7.2 公网方式

公网部署建议让 MCP Server 只监听 `127.0.0.1:9000`，由 Nginx、Caddy、Traefik 或 Cloudflare Access 提供 TLS 和认证。A 电脑可通过静态 Header 传递访问凭证：

```json
"header_refs": {
  "Authorization": "SECMIND_B_MCP_AUTHORIZATION"
}
```

A 电脑进程环境中设置：

```powershell
$env:SECMIND_B_MCP_AUTHORIZATION='Bearer replace-with-real-token'
```

`header_refs` 的右侧是环境变量名，不是真实 token。SecMind 在连接时解析，数据库只保存引用关系。

### 7.3 A 电脑网络检查

```powershell
Test-NetConnection B电脑IP -Port 9000
curl.exe -i http://B电脑IP:9000/mcp
```

`GET` 可能返回 `405 Method Not Allowed`，这仍能证明 TCP、HTTP 和路由可达；最终以 MCP Client 能完成 `initialize` 和 `tools/list` 为准。

### 7.4 把 B 端 MCP 配置为持久服务

开发阶段可以在终端前台运行，稳定后应交给操作系统服务管理器，确保自动启动、失败重启和日志归档。

Linux `systemd` 示例：

```ini
[Unit]
Description=B Security Tools MCP Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=security-mcp
Group=security-mcp
WorkingDirectory=/opt/security-mcp/servers
EnvironmentFile=/etc/security-mcp/b-security-tools.env
ExecStart=/opt/security-mcp/venvs/b-security-tools/bin/python /opt/security-mcp/servers/b_security_tools.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

启用：

```bash
sudo install -m 0644 b-security-tools.service /etc/systemd/system/b-security-tools.service
sudo systemctl daemon-reload
sudo systemctl enable --now b-security-tools
sudo systemctl status b-security-tools
sudo journalctl -u b-security-tools -f
```

`/etc/security-mcp/b-security-tools.env` 由管理员创建并设为 `0600`，不要提交 Git。

Windows 推荐使用任务计划程序、WinSW 或已经部署的服务管理平台启动 Python/Node 进程。服务账户必须能够读取 CLI、工作目录和所需环境变量，但不应使用日常管理员账户。配置恢复策略，并将 stdout/stderr 写入 `C:\security-mcp\logs`。

## 8. 在 SecMind 注册远程 MCP

SecMind 支持：

- `stdio`
- `streamable_http`
- `sse`

### 8.1 通过前端注册

1. 在 A 电脑打开 SecMind。
2. 进入 `/mcp`。
3. 点击“注册 Server”。
4. 填写唯一 `Server ID`，例如 `b-security-tools`。
5. 选择 `Streamable HTTP`。
6. URL 填写 `http://B电脑IP:9000/mcp` 或正式 HTTPS 地址。
7. 启用“立即连接”并提交。
8. 确认状态为 `CONNECTED`，随后刷新能力。
9. 检查统一工具目录中出现 `MCP` 来源的 Tool。

当前前端表单适合无认证 URL。需要 `headerRefs` 时使用 GraphQL 或启动 JSON 配置。

### 8.2 通过 GraphQL 注册

无认证内网示例：

```graphql
mutation {
  registerMCPServer(input: {
    serverId: "b-security-tools"
    name: "B Security Tools"
    transport: STREAMABLE_HTTP
    url: "http://10.0.0.20:9000/mcp"
    enabled: true
    metadata: { node: "B", environment: "private-network" }
  }) {
    serverId
    status
    protocolVersion
    capabilities { kind name }
  }
}
```

带认证的公网示例：

```graphql
mutation {
  registerMCPServer(input: {
    serverId: "b-security-tools"
    name: "B Security Tools"
    transport: STREAMABLE_HTTP
    url: "https://security-tools.example.com/mcp"
    headerRefs: { Authorization: "SECMIND_B_MCP_AUTHORIZATION" }
    enabled: true
  }) {
    serverId
    status
    capabilities { kind name }
  }
}
```

PowerShell 调用示例：

```powershell
$query = @'
mutation {
  registerMCPServer(input: {
    serverId: "b-security-tools"
    name: "B Security Tools"
    transport: STREAMABLE_HTTP
    url: "http://10.0.0.20:9000/mcp"
    enabled: true
  }) { serverId status protocolVersion capabilities { kind name } }
}
'@
$body = @{ query = $query } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/graphql -ContentType 'application/json' -Body $body
```

如果 SecMind 启用了 `SECMIND_API_KEY`，还要按部署的 API 鉴权约定附加对应 Header。

### 8.3 通过启动 JSON 配置

创建 UTF-8 文件，例如：

```text
C:\kaifa\tool\anquan2\config\mcp-servers.json
```

内容：

```json
{
  "servers": [
    {
      "schema_version": "1.0",
      "server_id": "b-security-tools",
      "name": "B Security Tools",
      "transport": "streamable_http",
      "url": "https://security-tools.example.com/mcp",
      "header_refs": {
        "Authorization": "SECMIND_B_MCP_AUTHORIZATION"
      },
      "enabled": true,
      "connect_timeout_seconds": 30,
      "call_timeout_seconds": 600,
      "metadata": {
        "node": "B",
        "owner": "security-tools"
      }
    }
  ]
}
```

原生加载器当前读取 **JSON，不读取 TOML**。`.toml` 可以放到 GitHub 作为你自己的工具清单，但不能直接作为 `SECMIND_MCP_CONFIG_FILE`。

非 Docker 启动：

```powershell
$env:SECMIND_MCP_CONFIG_FILE='C:\kaifa\tool\anquan2\config\mcp-servers.json'
```

Docker Compose 需要在 `x-backend-environment` 中传递：

```yaml
SECMIND_MCP_CONFIG_FILE: ${SECMIND_MCP_CONFIG_FILE:-/app/config/mcp-servers.json}
SECMIND_B_MCP_AUTHORIZATION: ${SECMIND_B_MCP_AUTHORIZATION:-}
```

并给 `backend` 增加只读挂载：

```yaml
volumes:
  - ./config/mcp-servers.json:/app/config/mcp-servers.json:ro
```

然后在根 `.env` 设置真实环境变量，重新构建或重启后端：

```powershell
docker compose config --quiet
docker compose up -d --build backend
docker compose logs --tail 200 backend
```

## 9. stdio 和 SSH 方式

### 9.1 A 本机 stdio

如果 MCP Server 安装在 A 电脑，可配置：

```json
{
  "server_id": "local-security-tools",
  "name": "Local Security Tools",
  "transport": "stdio",
  "command": "C:/security-mcp/venvs/tools/Scripts/python.exe",
  "args": ["C:/security-mcp/servers/tools.py"],
  "cwd": "C:/security-mcp/servers",
  "env_refs": {
    "UPSTREAM_API_KEY": "SECMIND_UPSTREAM_API_KEY"
  }
}
```

在 Docker Backend 中，`stdio` 命令运行在容器内部，不能直接看到 Windows 主机路径。要么把 Server 和 CLI 安装进 Backend 镜像，要么挂载文件并保证容器内依赖完整。双机工具不建议使用这种方式。

### 9.2 SSH 转发 stdio

没有开放 HTTP 端口时，可以让 A 使用 SSH 启动 B 上的 stdio MCP Server：

```json
{
  "server_id": "b-tools-over-ssh",
  "name": "B Tools over SSH",
  "transport": "stdio",
  "command": "ssh",
  "args": [
    "-T",
    "mcp@10.0.0.20",
    "/opt/security-mcp/venvs/b-security-tools/bin/python",
    "/opt/security-mcp/servers/b_security_tools_stdio.py"
  ]
}
```

要求：

- A 到 B 使用密钥认证，不出现密码交互。
- SSH 登录不得向 stdout 输出 Banner、欢迎语或 shell profile 文本。
- MCP 协议只走 stdout，日志写 stderr。
- B Server 使用 `mcp.run(transport="stdio")`。
- 如果 A Backend 在 Docker 中，容器内还必须有 SSH Client、密钥和 known_hosts。

综合维护成本仍高于 Streamable HTTP。

## 10. 普通 CLI 如何接入

SecMind 目前没有“填写一个 CLI 路径，Agent 就自动理解所有参数”的通用功能。普通 CLI 有三种接入路线：

1. **首选：B 电脑 MCP Wrapper**。适合双机和大量工具。
2. **Native Tool**。适合少量、稳定、需要深度融入主程序的工具。
3. **隔离执行服务**。适合大型工具链或需要独立容器、GPU、桌面环境的工具，再由 MCP 调用该服务。

CLI 可以上传到 GitHub，但应上传源码、Wrapper、安装脚本、lockfile、Dockerfile 和非敏感配置。不要未经许可提交第三方二进制、大型字典、商业软件、漏洞样本、真实凭证或许可证不允许再分发的文件。

推荐仓库结构：

```text
security-tools-node/
  README.md
  LICENSE
  pyproject.toml
  uv.lock
  servers/
    web_tools.py
    reverse_tools.py
    forensics_tools.py
  wrappers/
    nmap.py
    nuclei.py
    semgrep.py
  schemas/
  tests/
  config/
    tools.example.json
  docker/
  scripts/
```

## 11. 分批部署建议

### 第一批：验证完整链路

- 一个自写 `echo` 或系统信息 MCP Tool。
- Nmap 或 Nuclei 中的一个只读、输出稳定的动作。
- Semgrep 或 Bandit 中的一个代码审计动作。

目标是验证连接、能力发现、调用、结果、Artifact 和事件，而不是追求工具数量。

### 第二批：常用自动化

- Web：Nuclei、sqlmap、Nikto、ffuf、httpx。
- 网络：Nmap、Masscan、Wireshark/tshark。
- 代码与供应链：Semgrep、Trivy、OSV-Scanner、Gitleaks。
- 情报：Shodan、Censys、VirusTotal 等 API 工具。

### 第三批：重型或交互式工具

- 逆向：Ghidra、radare2、JADX、Binary Ninja/IDA 插件。
- Pwn：pwntools、GDB/GEF/Pwndbg、ROPgadget。
- 取证：Volatility、binwalk、ExifTool、Autopsy 相关工具。
- 密码学：Hashcat、John the Ripper、SageMath 等。

重型工具优先独立容器或专用 Server，不要和轻量 Web 工具共用一个易崩溃的大进程。

## 12. 验收步骤

### 12.1 B 电脑本地验收

1. CLI `--version` 成功。
2. MCP Server 能启动且没有 Python/Node 导入错误。
3. MCP Inspector 或测试 Client 可以完成 `initialize`。
4. `tools/list` 能列出 Tool 和输入 Schema。
5. `tools/call` 返回结构化结果。
6. 失败、无效参数和超时返回明确错误，不让 Server 进程退出。

### 12.2 A 到 B 网络验收

1. A 能解析 B 的 IP 或域名。
2. `Test-NetConnection` 成功。
3. TLS 证书链和主机名正确。
4. 认证 Header 能通过代理验证。
5. 未授权请求被拒绝。

### 12.3 SecMind 验收

GraphQL 查询：

```graphql
query {
  mcpServers {
    serverId
    name
    transport
    status
    protocolVersion
    errorMessage
    capabilities { kind name description }
  }
  tools {
    toolId
    name
    origin
    serverId
    inputSchema
  }
}
```

通过条件：

1. Server 状态为 `CONNECTED`。
2. `capabilities` 至少有一个 `TOOL`。
3. `tools` 中出现 `origin: MCP` 且 `serverId` 正确。
4. 调用后数据库出现 ToolCall。
5. Live Feed 出现 `decision.recorded`、`tool.started` 和唯一终态事件。
6. MCP 协议事件与 Agent 工具事件能通过同一 run ID 关联。
7. 工具输出形成结构化数据或 Artifact/Evidence。
8. 重启 A 后 MCP 配置和能力记录仍可恢复。

### 12.4 最终 Agent 验收

在动态工具目录注入完成后，使用模型从自然语言目标自主选择 B 电脑 Tool，完成：

```text
Prompt -> Agent 规划 -> 选择 MCP Tool -> B 执行 CLI -> 返回结果
       -> 独立验证 -> Runtime Ledger -> GraphQL/前端回放 -> 报告
```

只有这条链真实通过，才算工具已经“接入程序”，而不是仅仅“安装在 B 电脑”。

## 13. 常见故障

| 现象 | 检查方向 |
| --- | --- |
| `DISCONNECTED` | Server 未启动、URL 错误、配置为 disabled |
| `FAILED` | 查看 `errorMessage`、B Server 日志、TLS 和认证 |
| 端口通但不能连接 | URL 路径不是 `/mcp`、服务不是 MCP、代理不支持流式响应 |
| `Missing environment references` | `header_refs`/`env_refs` 引用的环境变量没有传给 Backend |
| 前端能看到 Server 但没有工具 | `tools/list` 为空、Server 只提供 Resource/Prompt、刷新失败 |
| stdio 立即退出 | Python/Node 路径错误、依赖缺失、stdout 被普通日志污染 |
| Docker 中找不到 Windows CLI | Backend 容器无法直接使用主机路径；改用远程 HTTP MCP |
| 调用超时 | 调大 Server/Client timeout，并让长任务写 Artifact 或异步化 |
| 输出太大 | Wrapper 应解析并摘要，原始结果写文件或对象存储 |
| Agent 不会主动选择新工具 | 当前动态 Tool Definition 尚未完整进入模型上下文 |
| 注册后重启丢失 | 使用 GraphQL 持久化注册或配置 `SECMIND_MCP_CONFIG_FILE` 和挂载 |

## 14. B 电脑需要交付给 A 电脑的信息

B 电脑完成一批工具后，只需提供以下非敏感资料：

```text
节点名称：
私网 IP / 域名：
MCP transport：streamable_http / sse / stdio-over-ssh
MCP URL：
认证 Header 名称：
A 端应设置的环境变量名称：
Server ID：
工具列表及版本：
每个 Tool 的输入 Schema：
默认和最大超时：
并发限制：
Artifact 保存和下载方式：
Server 启动/停止命令：
日志位置：
健康检查方式：
许可证和来源记录：
```

不要通过文档或聊天传递真实 token、私钥、cookie 和数据库密码。真实值由 A、B 两端各自写入环境变量或密钥管理系统。
