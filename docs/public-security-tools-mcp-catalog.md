# 公开安全工具与 MCP 接入目录

更新日期：2026-07-19

本目录结合联网检索结果与本地 `C:\wangan\gongju` 工具目录整理，覆盖 Web、密码学、Pwn、逆向、Misc/取证、OSINT/网络和代码安全方向。实际使用前仍需检查目标项目的最新许可证、版本、认证方式和服务条款。

MCP 接入标记说明：

- **直接 MCP**：项目自身提供 MCP Server，可以优先试接 `anquan2`。
- **插件桥接**：需要在桌面工具中安装插件，并启动配套 MCP Server。
- **MCP 聚合**：一个 MCP Server 已经封装多个底层安全工具。
- **CLI 封装**：工具提供稳定命令行，可使用 Python MCP SDK/FastMCP 封装。
- **API 封装**：工具或平台提供 HTTP API，需要申请账号或 API Key 后封装。

| 方向 | 名称 | 介绍 | MCP 接入 | 网址 |
|---|---|---|---|---|
| Web | PortSwigger Burp Suite MCP | PortSwigger 官方 MCP Server，可向 Agent 暴露 Burp 站点地图、扫描发现和代理数据。 | 直接 MCP/插件桥接 | [GitHub](https://github.com/PortSwigger/mcp-server) |
| Web | ZAP-MCP | 面向 OWASP ZAP 的社区 MCP 集成，可驱动 Web 代理、扫描与部分 SQLMap 工作流。 | 直接 MCP/插件桥接 | [GitHub](https://github.com/ajtazer/ZAP-MCP) |
| Web | Playwright MCP | Microsoft 官方浏览器自动化 MCP，适合页面访问、表单、截图和 Web 流程验证。 | 直接 MCP | [GitHub](https://github.com/microsoft/playwright-mcp) |
| Web | Chrome DevTools MCP | Chrome 官方 DevTools MCP，可操作真实浏览器并读取控制台、网络和性能信息。 | 直接 MCP | [GitHub](https://github.com/ChromeDevTools/chrome-devtools-mcp) |
| Web | mcp-for-security | 集成 SQLMap、FFUF、Nmap、Masscan 等安全 CLI 的 MCP 工具集合。 | MCP 聚合 | [GitHub](https://github.com/cyproxio/mcp-for-security) |
| Web | Nuclei | ProjectDiscovery 模板化漏洞扫描器，生态活跃，适合以 CLI 方式封装为 MCP。 | CLI 封装 | [GitHub](https://github.com/projectdiscovery/nuclei) |
| Web | sqlmap | 自动化 SQL 注入检测与利用工具，本地参考目录已有副本。 | CLI 封装 | [GitHub](https://github.com/sqlmapproject/sqlmap) |
| Web | ffuf | 高性能 Web Fuzzer，可用于目录、参数、虚拟主机和 API 路径发现。 | CLI 封装 | [GitHub](https://github.com/ffuf/ffuf) |
| Web | feroxbuster | Rust 编写的递归内容发现工具，适合大规模目录枚举。 | CLI 封装 | [GitHub](https://github.com/epi052/feroxbuster) |
| Web | dirsearch | Python Web 路径扫描器，与本地 dirmap/yjdirscan 方向相近。 | CLI 封装 | [GitHub](https://github.com/maurosoria/dirsearch) |
| Web | Katana | ProjectDiscovery 的下一代爬虫，可输出端点、参数和 JavaScript 资源。 | CLI 封装 | [GitHub](https://github.com/projectdiscovery/katana) |
| Web | httpx | 批量探测 HTTP 服务、标题、状态码和技术栈的命令行工具。 | CLI 封装 | [GitHub](https://github.com/projectdiscovery/httpx) |
| Web | Naabu | ProjectDiscovery 的快速端口扫描器，适合资产探测链路。 | CLI 封装 | [GitHub](https://github.com/projectdiscovery/naabu) |
| Web | DalFox | 面向 XSS 的参数分析和自动验证工具。 | CLI 封装 | [GitHub](https://github.com/hahwul/dalfox) |
| Web | Arjun | HTTP 参数发现工具，可寻找隐藏 GET/POST 参数。 | CLI 封装 | [GitHub](https://github.com/s0md3v/Arjun) |
| Web | mitmproxy | 可脚本化的交互式 HTTPS 代理，适合通过 Python API 或 CLI 封装。 | CLI/API 封装 | [官网](https://mitmproxy.org/) |
| Web | Nikto | 经典 Web Server 配置和已知风险扫描器。 | CLI 封装 | [GitHub](https://github.com/sullo/nikto) |
| Web | testssl.sh | 检查 TLS/SSL 协议、密码套件和常见配置问题。 | CLI 封装 | [GitHub](https://github.com/testssl/testssl.sh) |
| 密码学 | CyberChef API MCP | 通过 CyberChef Server API 暴露编码、解码、加密和数据转换能力。 | 直接 MCP/API | [GitHub](https://github.com/slouchd/cyberchef-api-mcp-server) |
| 密码学 | MCP Bytesmith | 本地字节处理 MCP，支持 Hex、Base64、哈希、CRC、随机令牌和部分 EVM 编码。 | 直接 MCP | [GitHub](https://github.com/laszlopere/mcp-bytesmith) |
| 密码学 | Enigma Python MCP | 将 Enigma 历史密码机模拟器封装为 MCP 工具。 | 直接 MCP | [GitHub](https://github.com/denismaggior8/enigma-python-mcp) |
| 密码学 | CyberChef | GCHQ 开源的编码、压缩、加密和取证数据处理工作台。 | API/CLI 封装 | [GitHub](https://github.com/gchq/CyberChef) |
| 密码学 | Hashcat | GPU 加速密码哈希恢复工具，支持大量哈希算法。 | CLI 封装 | [官网](https://hashcat.net/hashcat/) |
| 密码学 | John the Ripper Jumbo | 通用密码审计与哈希恢复套件，插件格式丰富。 | CLI 封装 | [GitHub](https://github.com/openwall/john) |
| 密码学 | SageMath | 数论、有限域、格密码和 CTF 密码分析常用数学系统。 | Python/CLI 封装 | [官网](https://www.sagemath.org/) |
| 密码学 | RsaCtfTool | 自动化分析常见 RSA CTF 弱点和攻击方法。 | CLI 封装 | [GitHub](https://github.com/RsaCtfTool/RsaCtfTool) |
| 密码学 | Ciphey | 自动识别并尝试解码常见古典密码、编码和简单加密。 | CLI 封装 | [GitHub](https://github.com/bee-san/Ciphey) |
| 密码学 | jwt_tool | JWT 测试、解析、签名检查和常见配置风险验证工具。 | CLI 封装 | [GitHub](https://github.com/ticarpi/jwt_tool) |
| 密码学 | hashID | 根据摘要特征识别可能的哈希算法。 | CLI 封装 | [GitHub](https://github.com/psypanda/hashID) |
| 密码学 | YAFU | 整数分解工具，可用于 RSA 相关数论任务。 | CLI 封装 | [GitHub](https://github.com/bbuhrow/yafu) |
| 密码学 | FactorDB | 公共整数分解数据库，可查询已知因子。 | API 封装 | [官网](http://factordb.com/) |
| Pwn | pwntools | CTF Pwn 和漏洞利用开发的 Python 框架，包含通信、ELF、ROP 和 Shellcode API。 | Python 原生封装 | [GitHub](https://github.com/Gallopsled/pwntools) |
| Pwn | pwndbg | 面向漏洞利用和逆向的 GDB 插件，提供堆、寄存器、反汇编和内存辅助。 | CLI 封装 | [GitHub](https://github.com/pwndbg/pwndbg) |
| Pwn | GEF | 多架构 GDB 增强插件，适合漏洞研究和调试。 | CLI 封装 | [GitHub](https://github.com/hugsy/gef) |
| Pwn | GNU GDB | Linux 用户态调试器，可通过 MI、Python API 或现有 GDB MCP 社区实现接入。 | CLI/Python 封装 | [官网](https://sourceware.org/gdb/) |
| Pwn | ROPgadget | 从 ELF、PE、Mach-O 等二进制中搜索 ROP/JOP Gadget。 | CLI/Python 封装 | [GitHub](https://github.com/JonathanSalwan/ROPgadget) |
| Pwn | ropper | Gadget 搜索、语义过滤和 ROP 链辅助工具。 | CLI/Python 封装 | [GitHub](https://github.com/sashs/Ropper) |
| Pwn | one_gadget | 从 libc 中寻找满足约束的一步执行 Gadget。 | CLI 封装 | [GitHub](https://github.com/david942j/one_gadget) |
| Pwn | angr | 二进制符号执行与程序分析框架，适合路径探索和约束求解。 | Python 原生封装 | [GitHub](https://github.com/angr/angr) |
| Pwn | patchelf | 修改 ELF Interpreter、RPATH 和动态依赖。 | CLI 封装 | [GitHub](https://github.com/NixOS/patchelf) |
| Pwn | seccomp-tools | 分析、汇编和反汇编 Linux Seccomp BPF 规则。 | CLI 封装 | [GitHub](https://github.com/david942j/seccomp-tools) |
| Pwn | checksec | 检查 ELF/PE 等文件的 PIE、NX、RELRO、Canary 等保护。 | CLI 封装 | [GitHub](https://github.com/slimm609/checksec.sh) |
| Pwn | AFL++ | 成熟的覆盖率引导模糊测试框架。 | CLI 封装 | [GitHub](https://github.com/AFLplusplus/AFLplusplus) |
| Pwn | honggfuzz | 支持软硬件反馈的安全导向 Fuzzer。 | CLI 封装 | [GitHub](https://github.com/google/honggfuzz) |
| Pwn | libFuzzer | LLVM 内置的进程内覆盖率引导 Fuzzer。 | CLI 封装 | [LLVM 文档](https://llvm.org/docs/LibFuzzer.html) |
| Pwn | QEMU | 多架构模拟与虚拟化平台，常用于跨架构漏洞分析和固件调试。 | CLI/API 封装 | [官网](https://www.qemu.org/) |
| 逆向 | GhidraMCP | 将 Ghidra 反编译、交叉引用、符号和注释能力暴露给 Agent。 | 直接 MCP/插件桥接 | [GitHub](https://github.com/LaurieWired/GhidraMCP) |
| 逆向 | IDA Pro MCP | 成熟的 IDA MCP 实现，提供函数、反编译、重命名和数据查询工具。 | 直接 MCP/插件桥接 | [GitHub](https://github.com/mrexodia/ida-pro-mcp) |
| 逆向 | IDA MCP Server | Python 实现的另一套 IDA MCP，可作为替代方案评估。 | 直接 MCP/插件桥接 | [GitHub](https://github.com/MxIris-Reverse-Engineering/ida-mcp-server) |
| 逆向 | Radare2 MCP | Radare2 官方组织维护的 MCP Server，提供反汇编和二进制分析工具。 | 直接 MCP | [GitHub](https://github.com/radareorg/radare2-mcp) |
| 逆向 | x64dbgMCP | 向 MCP Client 暴露 x64dbg SDK 调试能力。 | 直接 MCP/插件桥接 | [GitHub](https://github.com/Wasdubya/x64dbgMCP) |
| 逆向 | CutterMCP | 面向 Cutter/Rizin GUI 的 MCP 集成。 | 直接 MCP/插件桥接 | [GitHub](https://github.com/ap425q/CutterMCP) |
| 逆向 | Binary Ninja MCP | 为 Binary Ninja 提供函数、反编译和二进制视图访问。 | 直接 MCP/插件桥接 | [GitHub](https://github.com/fosdickio/binary_ninja_mcp) |
| 逆向 | Frida MCP | 将进程枚举、脚本注入和动态插桩能力接入 MCP。 | 直接 MCP | [GitHub](https://github.com/dnakov/frida-mcp) |
| 逆向 | JADX AI MCP | Android JADX 反编译器插件和 MCP Server。 | 直接 MCP/插件桥接 | [GitHub](https://github.com/zinja-coder/jadx-ai-mcp) |
| 逆向 | APKTool MCP Server | 将 APK 解包、资源处理和重打包能力封装为 MCP。 | 直接 MCP | [GitHub](https://github.com/zinja-coder/apktool-mcp-server) |
| 逆向 | Ghidra | NSA 开源的软件逆向工程套件。 | 插件或 CLI 封装 | [GitHub](https://github.com/NationalSecurityAgency/ghidra) |
| 逆向 | IDA Free | Hex-Rays 提供的免费 IDA 版本，适合基础反汇编与调试。 | 使用 IDA MCP 插件 | [官网](https://hex-rays.com/ida-free) |
| 逆向 | Binary Ninja Free | Binary Ninja 的免费版本，提供现代中间语言和分析界面。 | 使用 Binary Ninja MCP | [官网](https://binary.ninja/free/) |
| 逆向 | radare2 | 跨平台逆向工程框架，具备 CLI、脚本和多格式支持。 | 官方组织 MCP | [GitHub](https://github.com/radareorg/radare2) |
| 逆向 | Rizin | 从 radare2 分支发展的逆向框架，强调稳定 API。 | CLI/API 封装 | [GitHub](https://github.com/rizinorg/rizin) |
| 逆向 | Cutter | 基于 Rizin 的图形化逆向分析平台。 | 使用 CutterMCP | [GitHub](https://github.com/rizinorg/cutter) |
| 逆向 | x64dbg | Windows 用户态开源调试器，适用于 PE 分析。 | 使用 x64dbgMCP | [GitHub](https://github.com/x64dbg/x64dbg) |
| 逆向 | MobSF | 移动应用静态和动态安全分析平台，支持 Android/iOS。 | REST API 封装 | [GitHub](https://github.com/MobSF/Mobile-Security-Framework-MobSF) |
| 逆向 | RetDec | 开源机器码反编译器，可用于多格式静态分析。 | CLI/API 封装 | [GitHub](https://github.com/avast/retdec) |
| 逆向 | capa | Mandiant 的可执行文件能力识别工具，可根据规则判断恶意行为能力。 | CLI/Python 封装 | [GitHub](https://github.com/mandiant/capa) |
| 逆向 | FLOSS | 自动提取和解码恶意软件中的混淆字符串。 | CLI/Python 封装 | [GitHub](https://github.com/mandiant/flare-floss) |
| 逆向 | dnSpyEx | 面向 .NET 程序的反编译、调试和程序集编辑工具。 | CLI/插件封装 | [GitHub](https://github.com/dnSpyEx/dnSpy) |
| 逆向 | ILSpy | 开源 .NET 程序集浏览与反编译器。 | CLI/API 封装 | [GitHub](https://github.com/icsharpcode/ILSpy) |
| 逆向 | pycdc | Python 字节码反编译工具，本地参考目录已有副本。 | CLI 封装 | [GitHub](https://github.com/zrax/pycdc) |
| 逆向 | ImHex | 现代开源十六进制编辑器，支持模式语言和数据可视化。 | CLI/插件封装 | [GitHub](https://github.com/WerWolv/ImHex) |
| 逆向 | Binwalk | 固件签名扫描、熵分析和嵌入文件提取工具。 | CLI/Python 封装 | [GitHub](https://github.com/ReFirmLabs/binwalk) |
| Misc/取证 | WireMCP | 面向 Wireshark/数据包分析的 MCP Server，提供过滤和威胁检测能力。 | 直接 MCP | [GitHub](https://github.com/0xKoda/WireMCP) |
| Misc/取证 | Wireshark | 图形化网络协议分析器，本地参考目录已有安装。 | 使用 WireMCP/CLI 封装 | [官网](https://www.wireshark.org/) |
| Misc/取证 | YaraFlux | 以 YARA 规则扫描和恶意软件检测为核心的 MCP Server。 | 直接 MCP | [GitHub](https://github.com/ThreatFlux/YaraFlux) |
| Misc/取证 | Volatility 3 | 内存取证框架，支持 Windows、Linux 和 macOS 内存镜像。 | CLI/Python 封装 | [GitHub](https://github.com/volatilityfoundation/volatility3) |
| Misc/取证 | Autopsy | 基于 Sleuth Kit 的数字取证图形平台。 | Java/API 封装 | [官网](https://www.autopsy.com/) |
| Misc/取证 | The Sleuth Kit | 文件系统和磁盘镜像分析工具集。 | CLI 封装 | [GitHub](https://github.com/sleuthkit/sleuthkit) |
| Misc/取证 | ExifTool | 读取和写入大量文件格式元数据的成熟工具。 | CLI 封装 | [官网](https://exiftool.org/) |
| Misc/取证 | Foremost | 基于文件头和文件尾进行文件恢复和雕刻。 | CLI 封装 | [官网](https://foremost.sourceforge.net/) |
| Misc/取证 | bulk_extractor | 从磁盘镜像和文件中批量提取邮箱、URL、信用卡号等特征。 | CLI 封装 | [GitHub](https://github.com/simsong/bulk_extractor) |
| Misc/取证 | Suricata | IDS/IPS 和网络安全监控引擎，可输出结构化 EVE JSON。 | CLI/Socket/API 封装 | [官网](https://suricata.io/) |
| Misc/取证 | Zeek | 面向网络行为分析和协议日志生成的平台。 | CLI/日志 API 封装 | [官网](https://zeek.org/) |
| Misc/取证 | zsteg | PNG/BMP 隐写检测工具，常用于 CTF Misc。 | CLI 封装 | [GitHub](https://github.com/zed-0xff/zsteg) |
| Misc/取证 | stegseek | 针对 steghide 的高速口令恢复和隐写内容提取工具。 | CLI 封装 | [GitHub](https://github.com/RickdeJager/stegseek) |
| Misc/取证 | steghide | 在图像和音频文件中嵌入或提取隐藏数据。 | CLI 封装 | [官网](https://steghide.sourceforge.net/) |
| Misc/取证 | Aperi'Solve | 在线图像隐写和取证分析平台，本地参考目录保存了相关入口。 | Web/API 封装 | [官网](https://www.aperisolve.com/) |
| Misc/取证 | oletools | 分析 Microsoft Office OLE、宏、RTF 和恶意文档的 Python 工具集。 | CLI/Python 封装 | [GitHub](https://github.com/decalage2/oletools) |
| Misc/取证 | Didier Stevens Suite | 包含 pdf-parser、oledump 等文档和恶意样本分析脚本。 | CLI/Python 封装 | [GitHub](https://github.com/DidierStevens/DidierStevensSuite) |
| OSINT/网络 | Nmap | 网络发现、端口扫描、服务识别和 NSE 脚本平台，本地已有 Zenmap。 | mcp-for-security/CLI 封装 | [官网](https://nmap.org/) |
| OSINT/网络 | Masscan | 高速互联网规模 TCP 端口扫描器。 | mcp-for-security/CLI 封装 | [GitHub](https://github.com/robertdavidgraham/masscan) |
| OSINT/网络 | RustScan | 快速端口扫描器，可将结果传递给 Nmap。 | CLI 封装 | [GitHub](https://github.com/RustScan/RustScan) |
| OSINT/网络 | OWASP Amass | 资产发现、DNS 枚举和攻击面映射平台。 | CLI/API 封装 | [GitHub](https://github.com/owasp-amass/amass) |
| OSINT/网络 | Subfinder | 被动子域名发现工具，支持多种情报源。 | CLI 封装 | [GitHub](https://github.com/projectdiscovery/subfinder) |
| OSINT/网络 | Shodan | 互联网设备和服务搜索平台，提供官方 API，需要申请 API Key。 | API 封装 | [开发者平台](https://developer.shodan.io/) |
| OSINT/网络 | Censys | 互联网资产、证书和服务搜索平台，提供 REST API。 | API 封装 | [开发者文档](https://docs.censys.com/) |
| OSINT/网络 | GitHub MCP Server | GitHub 官方 MCP，可搜索代码、读取仓库、管理 Issue 和 Pull Request。 | 直接 MCP | [GitHub](https://github.com/github/github-mcp-server) |
| OSINT/网络 | git-dumper | 从错误暴露的 `.git` 目录恢复仓库，本地参考目录已有副本。 | CLI 封装 | [GitHub](https://github.com/arthaud/git-dumper) |
| OSINT/网络 | dvcs-ripper | 恢复暴露的 Git、SVN、Mercurial、Bazaar 和 CVS 仓库，本地已有副本。 | CLI 封装 | [GitHub](https://github.com/kost/dvcs-ripper) |
| OSINT/网络 | TruffleHog | 扫描 Git、文件系统和云环境中的密钥与凭据。 | CLI/API 封装 | [GitHub](https://github.com/trufflesecurity/trufflehog) |
| OSINT/网络 | Gitleaks | Git 仓库和文件系统 Secret 扫描器。 | CLI 封装 | [GitHub](https://github.com/gitleaks/gitleaks) |
| 代码安全 | Semgrep MCP | Semgrep 官方 MCP，可让 Agent 对代码执行静态安全扫描。 | 直接 MCP | [GitHub](https://github.com/semgrep/mcp) |
| 代码安全 | SonarQube MCP Server | SonarSource 官方 MCP，用于查询项目、质量门和安全问题。 | 直接 MCP/API | [GitHub](https://github.com/SonarSource/sonarqube-mcp-server) |
| 代码安全 | Snyk Studio MCP | Snyk 官方 MCP，将依赖、代码和容器安全能力接入 Agent。 | 直接 MCP/API | [GitHub](https://github.com/snyk/studio-mcp) |
| 代码安全 | Trivy MCP | Aqua Security 维护的 Trivy MCP，可扫描镜像、文件系统、配置和依赖。 | 直接 MCP | [GitHub](https://github.com/aquasecurity/trivy-mcp) |
| 代码安全 | OSV MCP | 通过 OSV 数据库查询开源组件漏洞。 | 直接 MCP/API | [GitHub](https://github.com/StacklokLabs/osv-mcp) |
| 代码安全 | Google Security MCP | Google 提供的安全工具 MCP 集合，适合评估威胁情报和安全服务连接。 | 直接 MCP/API | [GitHub](https://github.com/google/mcp-security) |
| 代码安全 | SAST MCP Server | 聚合 Bandit、Semgrep、Trivy、CodeQL、Checkov、Gitleaks、ZAP 等扫描器。 | MCP 聚合 | [GitHub](https://github.com/Skyrxin/sast-mcp-server) |
| 代码安全 | SecOps MCP | 将多种开源测试与威胁狩猎工具放在统一 MCP 接口后。 | MCP 聚合 | [GitHub](https://github.com/securityfortech/secops-mcp) |
| 平台/接入 | Elasticsearch MCP Server | Elastic 官方 MCP，可查询索引、映射和集群数据，适合日志与安全分析。 | 直接 MCP/API | [GitHub](https://github.com/elastic/mcp-server-elasticsearch) |
| 平台/接入 | Cloudflare MCP Server | Cloudflare 官方 MCP，可访问账户、Workers、日志和部分安全能力。 | 直接 MCP/API | [GitHub](https://github.com/cloudflare/mcp-server-cloudflare) |
| 平台/接入 | Docker MCP Gateway | Docker 官方 MCP Gateway，用于发现、运行和聚合容器化 MCP Server。 | 直接 MCP/网关 | [GitHub](https://github.com/docker/mcp-gateway) |
| 平台/接入 | ToolHive | Stacklok 的 MCP 运行与管理工具，可隔离运行第三方 MCP Server。 | MCP 运行平台 | [GitHub](https://github.com/stacklok/toolhive) |
| 平台/接入 | Official MCP Servers | MCP 官方参考 Server 集合，包含 Filesystem、Git、Fetch 等基础能力。 | 直接 MCP | [GitHub](https://github.com/modelcontextprotocol/servers) |
| 移动/自动化 | Mobile MCP | 面向 Android/iOS 设备和模拟器的移动自动化 MCP。 | 直接 MCP | [GitHub](https://github.com/mobile-next/mobile-mcp) |

## 建议的首批申请与接入顺序

1. **零账号本地验证**：MCP Bytesmith、Playwright MCP、Chrome DevTools MCP、Official MCP Servers。
2. **现有本地工具复用**：PortSwigger MCP、WireMCP、Nuclei、sqlmap、Nmap、Wireshark。
3. **代码与供应链安全**：Semgrep MCP、Trivy MCP、OSV MCP、SonarQube MCP、Snyk Studio MCP。
4. **逆向专项**：GhidraMCP、Radare2 MCP、JADX AI MCP；IDA/Binary Ninja MCP 需要对应桌面软件。
5. **需要申请 API Key**：Shodan、Censys、Snyk、Cloudflare、Elasticsearch 云服务。

接入 `anquan2` 时优先选择支持 **Streamable HTTP** 的 Server；只有本地桌面插件或纯 CLI 工具再使用 `stdio`。对标记为“CLI 封装”的项目，建议每个 MCP Tool 只映射一个稳定命令，并将参数定义为严格 JSON Schema，同时返回结构化结果而不是未经解析的终端长文本。
