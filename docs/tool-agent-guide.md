# SecMind Agent Tool 调用指南

> 本文档由 7 个本地 MCP Server 的实时 `tools/list` 自动生成。Tool 名称、字段名和 JSON Schema 保持原文。

- Tool 数量：78
- 指南 SHA256：`51a8cea6e6a2f9ffd320b0336d1998de14012f6c8f79d8760efe26cb1b84519e`

## Local HTTP Fetch

来源：[https://github.com/modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)
协议：`2025-11-25`；Tool：1 个。

### `fetch`

- **这是什么**：Local HTTP Fetch 提供的 `fetch` MCP Tool。
- **有什么作用**：抓取指定 HTTP/HTTPS 地址并提取可读内容。
- **什么时候调用**：需要读取公开网页、文档或接口响应作为上下文和证据时。
- **输入什么数据**：`url`（string，必填，URL to fetch）；`max_length`（integer，可选，Maximum number of characters to return.）；`start_index`（integer，可选，On return output starting at this character index, useful if a previous fetch was truncated and more context is required.）；`raw`（boolean，可选，Get the actual HTML content of the requested page, without simplification.）。
- **返回什么数据**：返回抓取后的文本、元数据或失败信息。

## Local Chrome DevTools

来源：[https://github.com/ChromeDevTools/chrome-devtools-mcp](https://github.com/ChromeDevTools/chrome-devtools-mcp)
协议：`2025-11-25`；Tool：29 个。

### `click`

- **这是什么**：Local Chrome DevTools 提供的 `click` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 点击页面元素。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`uid`（string，必填，The uid of an element on the page from the page content snapshot）；`dblClick`（boolean，可选，Set to true for double clicks. Default is false.）；`includeSnapshot`（boolean，可选，Whether to include a snapshot in the response. Default is false.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `close_page`

- **这是什么**：Local Chrome DevTools 提供的 `close_page` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 关闭页面。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`pageId`（number，必填，The ID of the page to close. Call list_pages to list pages.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `drag`

- **这是什么**：Local Chrome DevTools 提供的 `drag` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 拖动页面元素。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`from_uid`（string，必填，The uid of the element to drag）；`to_uid`（string，必填，The uid of the element to drop into）；`includeSnapshot`（boolean，可选，Whether to include a snapshot in the response. Default is false.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `emulate`

- **这是什么**：Local Chrome DevTools 提供的 `emulate` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 模拟设备、网络或环境。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`networkConditions`（string，可选，Throttle network. Omit to disable throttling.）；`cpuThrottlingRate`（number，可选，Represents the CPU slowdown factor. Omit or set the rate to 1 to disable throttling）；`geolocation`（string，可选，Geolocation (`<latitude>,<longitude>`) to emulate. Latitude between -90 and 90. Longitude between -180 and 180. Omit to clear the geolocation override.）；`userAgent`（string，可选，User agent to emulate. Set to empty string to clear the user agent override.）；`colorScheme`（string，可选，Emulate the dark or the light mode. Set to "auto" to reset to the default.）；`viewport`（string，可选，Emulate device viewports '<width>x<height>x<devicePixelRatio>[,mobile][,touch][,landscape]'. 'touch' and 'mobile' to emulate mobile devices. 'landscape' to emulate landscape mode.）；`extraHttpHeaders`（string，可选，Extra HTTP headers as a JSON string object, e.g. {"X-Custom": "value", "Authorization": "Bearer token"}. Headers are included into every HTTP request originating from the page and persist across navigations until cleared. Pass an empty string to clear all extra headers.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `evaluate_script`

- **这是什么**：Local Chrome DevTools 提供的 `evaluate_script` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 在页面上下文读取或计算数据。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`function`（string，必填，A JavaScript function declaration to be executed by the tool in the currently selected page. Example without arguments: `() => document.title` or `async () => await fetch("example.com")`. Example with arguments: `(el) => el.innerText`）；`args`（array，可选，An optional list of arguments to pass to the function.）；`filePath`（string，可选，The absolute or relative path to a file to save the script output to. If omitted, the output is returned inline.）；`dialogAction`（string，可选，Handle dialogs while execution. "accept", "dismiss", or string for response of window.prompt. Defaults to accept.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `fill`

- **这是什么**：Local Chrome DevTools 提供的 `fill` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 填写单个表单控件。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`uid`（string，必填，The uid of an element on the page from the page content snapshot）；`value`（string，必填，The value to fill in. "true" or "false" for checkboxes and toggles, "true" for radio buttons.）；`includeSnapshot`（boolean，可选，Whether to include a snapshot in the response. Default is false.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `fill_form`

- **这是什么**：Local Chrome DevTools 提供的 `fill_form` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 批量填写表单。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`elements`（array，必填，Elements from snapshot to fill out.）；`includeSnapshot`（boolean，可选，Whether to include a snapshot in the response. Default is false.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `get_console_message`

- **这是什么**：Local Chrome DevTools 提供的 `get_console_message` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 读取指定 Console 消息。
- **什么时候调用**：需要观察当前浏览器状态并收集可复核证据时。
- **输入什么数据**：`msgid`（number，必填，The msgid of a console message on the page from the listed console messages）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `get_network_request`

- **这是什么**：Local Chrome DevTools 提供的 `get_network_request` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 读取指定 Network 请求。
- **什么时候调用**：需要观察当前浏览器状态并收集可复核证据时。
- **输入什么数据**：`reqid`（number，可选，The reqid of the network request. If omitted returns the currently selected request in the DevTools Network panel.）；`requestFilePath`（string，可选，The absolute or relative path to a .network-request file to save the request body to. If omitted, the body is returned inline.）；`responseFilePath`（string，可选，The absolute or relative path to a .network-response file to save the response body to. If omitted, the body is returned inline.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `handle_dialog`

- **这是什么**：Local Chrome DevTools 提供的 `handle_dialog` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 处理浏览器对话框。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`action`（string，必填，Whether to dismiss or accept the dialog）；`promptText`（string，可选，Optional prompt text to enter into the dialog.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `hover`

- **这是什么**：Local Chrome DevTools 提供的 `hover` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 悬停页面元素。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`uid`（string，必填，The uid of an element on the page from the page content snapshot）；`includeSnapshot`（boolean，可选，Whether to include a snapshot in the response. Default is false.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `lighthouse_audit`

- **这是什么**：Local Chrome DevTools 提供的 `lighthouse_audit` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 执行 Lighthouse 质量审计。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`mode`（string，可选，"navigation" reloads & audits. "snapshot" analyzes current state.）；`device`（string，可选，Device to emulate.）；`outputDirPath`（string，可选，Directory for reports. If omitted, uses temporary files.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `list_console_messages`

- **这是什么**：Local Chrome DevTools 提供的 `list_console_messages` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 列出 Console 消息。
- **什么时候调用**：需要观察当前浏览器状态并收集可复核证据时。
- **输入什么数据**：`pageSize`（integer，可选，Maximum number of messages to return. When omitted, returns all messages.）；`pageIdx`（integer，可选，Page number to return (0-based). When omitted, returns the first page.）；`types`（array，可选，Filter messages to only return messages of the specified resource types. When omitted or empty, returns all messages.）；`includePreservedMessages`（boolean，可选，Set to true to return the preserved messages over the last 3 navigations.）；`serviceWorkerId`（string，可选，Filter messages to only return messages of the specified service worker.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `list_network_requests`

- **这是什么**：Local Chrome DevTools 提供的 `list_network_requests` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 列出 Network 请求。
- **什么时候调用**：需要观察当前浏览器状态并收集可复核证据时。
- **输入什么数据**：`pageSize`（integer，可选，Maximum number of requests to return. When omitted, returns all requests.）；`pageIdx`（integer，可选，Page number to return (0-based). When omitted, returns the first page.）；`resourceTypes`（array，可选，Filter requests to only return requests of the specified resource types. When omitted or empty, returns all requests.）；`includePreservedRequests`（boolean，可选，Set to true to return the preserved requests over the last 3 navigations.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `list_pages`

- **这是什么**：Local Chrome DevTools 提供的 `list_pages` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 列出浏览器页面。
- **什么时候调用**：需要观察当前浏览器状态并收集可复核证据时。
- **输入什么数据**：无参数。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `navigate_page`

- **这是什么**：Local Chrome DevTools 提供的 `navigate_page` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 导航当前页面。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`type`（string，可选，Navigate the page by URL, back or forward in history, or reload.）；`url`（string，可选，Target URL (only type=url)）；`ignoreCache`（boolean，可选，Whether to ignore cache on reload.）；`handleBeforeUnload`（string，可选，Whether to auto accept or beforeunload dialogs triggered by this navigation. Default is accept.）；`initScript`（string，可选，A JavaScript script to be executed on each new document before any other scripts for the next navigation.）；`timeout`（integer，可选，Maximum wait time in milliseconds. If set to 0, the default timeout will be used.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `new_page`

- **这是什么**：Local Chrome DevTools 提供的 `new_page` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 打开新页面。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`url`（string，必填，URL to load in a new page.）；`background`（boolean，可选，Whether to open the page in the background without bringing it to the front. Default is false (foreground).）；`isolatedContext`（string，可选，If specified, the page is created in an isolated browser context with the given name. Pages in the same browser context share cookies and storage. Pages in different browser contexts are fully isolated.）；`timeout`（integer，可选，Maximum wait time in milliseconds. If set to 0, the default timeout will be used.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `performance_analyze_insight`

- **这是什么**：Local Chrome DevTools 提供的 `performance_analyze_insight` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 分析性能 Trace 洞察。
- **什么时候调用**：需要观察当前浏览器状态并收集可复核证据时。
- **输入什么数据**：`insightSetId`（string，必填，The id for the specific insight set. Only use the ids given in the "Available insight sets" list.）；`insightName`（string，必填，The name of the Insight you want more information on. For example: "DocumentLatency" or "LCPBreakdown"）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `performance_start_trace`

- **这是什么**：Local Chrome DevTools 提供的 `performance_start_trace` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 开始性能 Trace。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`reload`（boolean，可选，Determines if, once tracing has started, the current selected page should be automatically reloaded. Navigate the page to the right URL using the navigate_page tool BEFORE starting the trace if reload or autoStop is set to true.）；`autoStop`（boolean，可选，Determines if the trace recording should be automatically stopped.）；`filePath`（string，可选，The absolute file path, or a file path relative to the current working directory, to save the raw trace data. For example, trace.json.gz (compressed) or trace.json (uncompressed).）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `performance_stop_trace`

- **这是什么**：Local Chrome DevTools 提供的 `performance_stop_trace` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 停止并汇总性能 Trace。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`filePath`（string，可选，The absolute file path, or a file path relative to the current working directory, to save the raw trace data. For example, trace.json.gz (compressed) or trace.json (uncompressed).）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `press_key`

- **这是什么**：Local Chrome DevTools 提供的 `press_key` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 发送键盘按键。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`key`（string，必填，A key or a combination (e.g., "Enter", "Control+A", "Control++", "Control+Shift+R"). Modifiers: Control, Shift, Alt, Meta）；`includeSnapshot`（boolean，可选，Whether to include a snapshot in the response. Default is false.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `resize_page`

- **这是什么**：Local Chrome DevTools 提供的 `resize_page` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 调整页面视口。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`width`（number，必填，Page width）；`height`（number，必填，Page height）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `select_page`

- **这是什么**：Local Chrome DevTools 提供的 `select_page` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 选择活动页面。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`pageId`（number，必填，The ID of the page to select. Call list_pages to get available pages.）；`bringToFront`（boolean，可选，Whether to focus the page and bring it to the top.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `take_heapsnapshot`

- **这是什么**：Local Chrome DevTools 提供的 `take_heapsnapshot` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 生成 JavaScript Heap Snapshot。
- **什么时候调用**：需要观察当前浏览器状态并收集可复核证据时。
- **输入什么数据**：`filePath`（string，必填，A path to a .heapsnapshot file to save the heapsnapshot to.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `take_screenshot`

- **这是什么**：Local Chrome DevTools 提供的 `take_screenshot` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 截取页面图像。
- **什么时候调用**：需要观察当前浏览器状态并收集可复核证据时。
- **输入什么数据**：`format`（string，可选，Type of format to save the screenshot as. Default is "webp"）；`quality`（number，可选，Compression quality for JPEG and WebP formats (0-100). Higher values mean better quality but larger file sizes. Ignored for PNG format.）；`uid`（string，可选，The uid of an element on the page from the page content snapshot. If omitted, takes a page screenshot.）；`fullPage`（boolean，可选，If set to true takes a screenshot of the full page instead of the currently visible viewport. Incompatible with uid.）；`filePath`（string，可选，The absolute path, or a path relative to the current working directory, to save the screenshot to instead of attaching it to the response.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `take_snapshot`

- **这是什么**：Local Chrome DevTools 提供的 `take_snapshot` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 读取页面可访问性/DOM 快照。
- **什么时候调用**：需要观察当前浏览器状态并收集可复核证据时。
- **输入什么数据**：`verbose`（boolean，可选，Whether to include all possible information available in the full a11y tree. Default is false.）；`filePath`（string，可选，The absolute path, or a path relative to the current working directory, to save the snapshot to instead of attaching it to the response.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `type_text`

- **这是什么**：Local Chrome DevTools 提供的 `type_text` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 向当前控件输入文本。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`text`（string，必填，The text to type）；`submitKey`（string，可选，Optional key to press after typing. E.g., "Enter", "Tab", "Escape"）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `upload_file`

- **这是什么**：Local Chrome DevTools 提供的 `upload_file` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 向页面文件控件提供本地文件。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`uid`（string，必填，The uid of the file input element or an element that will open file chooser on the page from the page content snapshot）；`filePath`（string，必填，The local path of the file to upload）；`includeSnapshot`（boolean，可选，Whether to include a snapshot in the response. Default is false.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

### `wait_for`

- **这是什么**：Local Chrome DevTools 提供的 `wait_for` MCP Tool。
- **有什么作用**：通过 Chrome DevTools 等待页面文本或状态出现。
- **什么时候调用**：已确认目标页面和操作对象，需要推进授权的浏览器工作流时。
- **输入什么数据**：`text`（array，必填，Non-empty list of texts. Resolves when any value appears on the page.）；`timeout`（integer，可选，Maximum wait time in milliseconds. If set to 0, the default timeout will be used.）。
- **返回什么数据**：返回浏览器操作结果、页面状态、快照、日志、网络记录或性能数据；失败时返回明确错误。

## Local Web Security Tools

来源：[https://github.com/dan-cun/anquan2](https://github.com/dan-cun/anquan2)
协议：`2025-11-25`；Tool：10 个。

### `tool_versions`

- **这是什么**：Local Web Security Tools 提供的 `tool_versions` MCP Tool。
- **有什么作用**：列出 Web Security Server 使用的固定工具路径。
- **什么时候调用**：执行安全任务前确认工具安装位置和运行版本时。
- **输入什么数据**：无参数。
- **返回什么数据**：返回 Nmap、Katana、ffuf、Nikto、sqlmap、Nuclei、httpx、Gitleaks、ExifTool 路径。

### `nmap_service_scan`

- **这是什么**：Local Web Security Tools 提供的 `nmap_service_scan` MCP Tool。
- **有什么作用**：扫描授权目标的 TCP 端口并识别服务。
- **什么时候调用**：需要确认主机存活、开放端口、服务产品和版本时。
- **输入什么数据**：`target`（string，必填）；`ports`（string，可选）；`top_ports`（integer，可选）；`service_detection`（boolean，可选）；`skip_host_discovery`（boolean，可选）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回退出状态、耗时、解析后的主机/端口/服务列表和 XML 结果路径。

### `katana_crawl`

- **这是什么**：Local Web Security Tools 提供的 `katana_crawl` MCP Tool。
- **有什么作用**：爬取授权 Web 目标并发现 URL、端点和 JavaScript 资源。
- **什么时候调用**：漏洞扫描前需要建立 Web 攻击面和端点清单时。
- **输入什么数据**：`url`（string，必填）；`depth`（integer，可选）；`javascript_crawl`（boolean，可选）；`technology_detection`（boolean，可选）；`rate_limit`（integer，可选）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回端点记录、记录数量、命令输出和 JSONL 结果路径。

### `ffuf_discover`

- **这是什么**：Local Web Security Tools 提供的 `ffuf_discover` MCP Tool。
- **有什么作用**：对 URL 中的 FUZZ 标记执行受限字典发现。
- **什么时候调用**：需要枚举目录、文件、API 路径或虚拟资源时。
- **输入什么数据**：`url_template`（string，必填）；`words`（value，可选）；`extensions`（string，可选）；`match_codes`（string，可选）；`threads`（integer，可选）；`rate_limit`（integer，可选）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回匹配项、状态码等字段、匹配数量和 JSON 结果路径。

### `nikto_scan`

- **这是什么**：Local Web Security Tools 提供的 `nikto_scan` MCP Tool。
- **有什么作用**：使用 Nikto 检查授权 Web Server 的已知风险和错误配置。
- **什么时候调用**：需要快速检查服务器配置、危险文件和常见已知问题时。
- **输入什么数据**：`url`（string，必填）；`tuning`（string，可选）；`follow_redirects`（boolean，可选）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回扫描状态、结构化发现和结果文件路径。

### `sqlmap_check`

- **这是什么**：Local Web Security Tools 提供的 `sqlmap_check` MCP Tool。
- **有什么作用**：使用受限 sqlmap 参数检查指定 URL 参数的 SQL 注入迹象。
- **什么时候调用**：已有授权 URL 和疑似参数，需要自动化验证 SQL 注入时。
- **输入什么数据**：`url`（string，必填）；`parameter`（string，可选）；`level`（integer，可选）；`risk`（integer，可选）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回命令状态、是否报告注入、日志和输出目录。

### `httpx_probe`

- **这是什么**：Local Web Security Tools 提供的 `httpx_probe` MCP Tool。
- **有什么作用**：批量探测 HTTP 服务的状态、标题和技术栈。
- **什么时候调用**：资产发现后需要筛选可访问 Web 服务并补充指纹时。
- **输入什么数据**：`urls`（array，必填）；`follow_redirects`（boolean，可选）；`threads`（integer，可选）；`rate_limit`（integer，可选）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回每个 URL 的 JSON 记录、记录数量和结果路径。

### `nuclei_scan`

- **这是什么**：Local Web Security Tools 提供的 `nuclei_scan` MCP Tool。
- **有什么作用**：使用签名 Nuclei 模板扫描授权 HTTP 目标。
- **什么时候调用**：已有目标列表，需要按严重性、标签或模板 ID 检查已知漏洞时。
- **输入什么数据**：`urls`（array，必填）；`severities`（string，可选）；`tags`（string，可选）；`template_ids`（string，可选）；`interactsh`（boolean，可选）；`rate_limit`（integer，可选）；`concurrency`（integer，可选）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回结构化发现、发现数量和 JSONL 结果路径。

### `gitleaks_detect`

- **这是什么**：Local Web Security Tools 提供的 `gitleaks_detect` MCP Tool。
- **有什么作用**：扫描授权目录中的 Secret，并对结果完全脱敏。
- **什么时候调用**：代码仓库、配置或构建产物需要凭据泄漏检查时。
- **输入什么数据**：`path`（string，必填）；`max_target_megabytes`（integer，可选）；`max_archive_depth`（integer，可选）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回脱敏发现、发现数量、执行状态和 JSON 结果路径。

### `exiftool_metadata`

- **这是什么**：Local Web Security Tools 提供的 `exiftool_metadata` MCP Tool。
- **有什么作用**：提取授权文件或目录中的结构化元数据。
- **什么时候调用**：取证、文件溯源或隐私分析需要时间、设备、作者等元数据时。
- **输入什么数据**：`path`（string，必填）。
- **返回什么数据**：返回 JSON 元数据和命令执行状态。

## Local CyberChef

来源：[https://github.com/slouchd/cyberchef-api-mcp-server](https://github.com/slouchd/cyberchef-api-mcp-server)
协议：`2025-11-25`；Tool：3 个。

### `bake_recipe`

- **这是什么**：Local CyberChef 提供的 `bake_recipe` MCP Tool。
- **有什么作用**：对一份输入执行指定 CyberChef Recipe。
- **什么时候调用**：已明确需要的解码、编码、哈希、解压或数据转换步骤时。
- **输入什么数据**：`input_data`（string，必填）；`recipe`（array，必填）。
- **返回什么数据**：返回转换结果、Recipe 执行信息或错误。

### `batch_bake_recipe`

- **这是什么**：Local CyberChef 提供的 `batch_bake_recipe` MCP Tool。
- **有什么作用**：对多份输入批量执行同一 CyberChef Recipe。
- **什么时候调用**：多个样本需要一致的数据转换流程时。
- **输入什么数据**：`batch_input_data`（array，必填）；`recipe`（array，必填）。
- **返回什么数据**：返回每份输入对应的转换结果和错误。

### `perform_magic_operation`

- **这是什么**：Local CyberChef 提供的 `perform_magic_operation` MCP Tool。
- **有什么作用**：使用 CyberChef Magic 推测可能的解码或转换操作。
- **什么时候调用**：输入格式未知，需要先识别编码或转换路径时。
- **输入什么数据**：`input_data`（string，必填）；`depth`（integer，可选）；`intensive_mode`（boolean，可选）；`extensive_language_support`（boolean，可选）；`crib_str`（string，可选）。
- **返回什么数据**：返回候选操作、推测结果和置信信息。

## Local Semgrep

来源：[https://github.com/semgrep/semgrep](https://github.com/semgrep/semgrep)
协议：`2025-11-25`；Tool：7 个。

### `semgrep_rule_schema`

- **这是什么**：Local Semgrep 提供的 `semgrep_rule_schema` MCP Tool。
- **有什么作用**：返回 Semgrep 自定义规则的 Schema 与编写约束。
- **什么时候调用**：准备生成或校验自定义 Semgrep 规则前。
- **输入什么数据**：无参数。
- **返回什么数据**：返回规则字段、类型和约束说明。

### `get_supported_languages`

- **这是什么**：Local Semgrep 提供的 `get_supported_languages` MCP Tool。
- **有什么作用**：列出当前 Semgrep 支持的编程语言。
- **什么时候调用**：选择扫描语言或构造自定义规则前。
- **输入什么数据**：无参数。
- **返回什么数据**：返回支持的语言标识列表。

### `semgrep_findings`

- **这是什么**：Local Semgrep 提供的 `semgrep_findings` MCP Tool。
- **有什么作用**：读取并筛选 Semgrep 已产生的发现。
- **什么时候调用**：扫描完成后需要按严重性、文件或规则整理证据时。
- **输入什么数据**：`issue_type`（string，可选，Type of issue to filter by.）；`repos`（array，可选，List of repository names to filter by. Include the owner and repository name, e.g. 'owner/repository'）；`status`（string，可选，Status of the issue to filter by.）；`severities`（value，可选，Severities of the issues to filter by.）；`confidence`（value，可选，Confidences of the issues to filter by.）；`autotriage_verdict`（value，可选，Autotriage verdict of the issues to filter by. If not provided, findings with any verdict (including unrated) are returned.）；`refs`（array，可选，List of git refs (branch names) to filter findings by. If not provided, only findings on the primary branch are returned.）；`limit`（integer，可选，Maximum number of findings to return）。
- **返回什么数据**：返回匹配发现及其位置、规则和消息。

### `semgrep_scan_with_custom_rule`

- **这是什么**：Local Semgrep 提供的 `semgrep_scan_with_custom_rule` MCP Tool。
- **有什么作用**：使用调用方提供的自定义规则扫描代码。
- **什么时候调用**：现有规则集无法表达待验证的项目特定缺陷时。
- **输入什么数据**：`code_files`（array，必填，List of dictionaries with 'path' and 'content' keys）；`rule`（string，必填，Semgrep YAML rule string）。
- **返回什么数据**：返回自定义规则匹配、位置、错误和扫描摘要。

### `semgrep_scan`

- **这是什么**：Local Semgrep 提供的 `semgrep_scan` MCP Tool。
- **有什么作用**：使用 Semgrep 规则集执行静态代码安全扫描。
- **什么时候调用**：需要发现源码中的漏洞模式、危险 API 或安全反模式时。
- **输入什么数据**：`code_files`（array，必填，List of dictionaries with 'path' pointing to the absolute path of the code file）。
- **返回什么数据**：返回规则匹配、文件位置、严重性、错误和扫描摘要。

### `get_abstract_syntax_tree`

- **这是什么**：Local Semgrep 提供的 `get_abstract_syntax_tree` MCP Tool。
- **有什么作用**：解析代码并返回抽象语法树信息。
- **什么时候调用**：需要理解语法结构或为规则设计定位节点时。
- **输入什么数据**：`code`（string，必填，The code to get the AST for）；`language`（string，必填，The programming language of the code）。
- **返回什么数据**：返回指定语言代码的 AST 表示或解析错误。

### `semgrep_scan_supply_chain`

- **这是什么**：Local Semgrep 提供的 `semgrep_scan_supply_chain` MCP Tool。
- **有什么作用**：检查项目依赖与供应链风险。
- **什么时候调用**：存在依赖清单或锁文件，需要识别已知易受攻击组件时。
- **输入什么数据**：无参数。
- **返回什么数据**：返回依赖发现、漏洞信息、位置和扫描摘要。

## Local WireMCP

来源：[https://github.com/0xKoda/WireMCP](https://github.com/0xKoda/WireMCP)
协议：`2025-11-25`；Tool：7 个。

### `capture_packets`

- **这是什么**：Local WireMCP 提供的 `capture_packets` MCP Tool。
- **有什么作用**：使用 TShark 捕获指定接口上的网络数据包。
- **什么时候调用**：仅在已授权接口上需要采集短时流量样本时。
- **输入什么数据**：`interface`（string，可选，Network interface to capture from (e.g., eth0, en0)）；`duration`（number，可选，Capture duration in seconds）。
- **返回什么数据**：返回捕获状态、PCAP 路径、包数量或错误。

### `get_summary_stats`

- **这是什么**：Local WireMCP 提供的 `get_summary_stats` MCP Tool。
- **有什么作用**：汇总 PCAP 的包数、协议和时间范围。
- **什么时候调用**：开始深度取证前需要快速了解流量样本时。
- **输入什么数据**：`interface`（string，可选，Network interface to capture from (e.g., eth0, en0)）；`duration`（number，可选，Capture duration in seconds）。
- **返回什么数据**：返回协议分布、包数、字节数和时间统计。

### `get_conversations`

- **这是什么**：Local WireMCP 提供的 `get_conversations` MCP Tool。
- **有什么作用**：提取 PCAP 中的主机与端口会话。
- **什么时候调用**：需要识别主要通信双方、连接方向和流量规模时。
- **输入什么数据**：`interface`（string，可选，Network interface to capture from (e.g., eth0, en0)）；`duration`（number，可选，Capture duration in seconds）。
- **返回什么数据**：返回会话端点、包数、字节数和持续时间。

### `check_threats`

- **这是什么**：Local WireMCP 提供的 `check_threats` MCP Tool。
- **有什么作用**：用规则检查 PCAP 中的可疑网络行为。
- **什么时候调用**：需要初筛扫描、异常协议或可疑通信模式时。
- **输入什么数据**：`interface`（string，可选，Network interface to capture from (e.g., eth0, en0)）；`duration`（number，可选，Capture duration in seconds）。
- **返回什么数据**：返回威胁匹配、证据字段和风险摘要。

### `check_ip_threats`

- **这是什么**：Local WireMCP 提供的 `check_ip_threats` MCP Tool。
- **有什么作用**：检查指定 IP 在 PCAP 中的相关活动。
- **什么时候调用**：已有可疑 IP，需要回溯其通信和行为时。
- **输入什么数据**：`ip`（string，必填，IP address to check (e.g., 192.168.1.1)）。
- **返回什么数据**：返回相关会话、包和威胁判断。

### `analyze_pcap`

- **这是什么**：Local WireMCP 提供的 `analyze_pcap` MCP Tool。
- **有什么作用**：对已有 PCAP 执行综合协议与安全分析。
- **什么时候调用**：需要对捕获文件形成整体取证摘要时。
- **输入什么数据**：`pcapPath`（string，必填，Path to the PCAP file to analyze (e.g., ./demo.pcap)）。
- **返回什么数据**：返回协议、端点、会话、异常和分析摘要。

### `extract_credentials`

- **这是什么**：Local WireMCP 提供的 `extract_credentials` MCP Tool。
- **有什么作用**：从授权 PCAP 中识别明文凭据迹象。
- **什么时候调用**：调查弱协议或凭据泄漏风险时。
- **输入什么数据**：`pcapPath`（string，必填，Path to the PCAP file to analyze (e.g., ./demo.pcap)）。
- **返回什么数据**：返回协议、位置和脱敏后的凭据证据；不得返回可复用秘密。

## Local Security Extended

来源：[https://github.com/dan-cun/anquan2](https://github.com/dan-cun/anquan2)
协议：`2025-11-25`；Tool：21 个。

### `extended_tool_versions`

- **这是什么**：Local Security Extended 提供的 `extended_tool_versions` MCP Tool。
- **有什么作用**：检查第一、第二批扩展安全工具的固定版本、路径和安装状态。
- **什么时候调用**：Agent 选择扩展 Tool 前，或诊断工具不可用、版本不匹配时。
- **输入什么数据**：无参数。
- **返回什么数据**：返回每个组件的 `version`、`path` 和 `installed`。

### `trivy_scan`

- **这是什么**：Local Security Extended 提供的 `trivy_scan` MCP Tool。
- **有什么作用**：扫描文件系统中的依赖漏洞、错误配置和泄密内容。
- **什么时候调用**：需要审计源码、构建目录、基础设施配置或依赖清单时。
- **输入什么数据**：`path`（string，必填）；`scanners`（string，可选）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回执行状态、Trivy JSON 发现和原始结果文件路径。

### `osv_scan`

- **这是什么**：Local Security Extended 提供的 `osv_scan` MCP Tool。
- **有什么作用**：依据 OSV 数据库检查源码目录或锁文件中的开源依赖漏洞。
- **什么时候调用**：项目包含包管理器清单或锁文件，需要补充供应链漏洞证据时。
- **输入什么数据**：`path`（string，必填）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回执行状态、OSV JSON 漏洞结果和结果文件路径。

### `yara_scan`

- **这是什么**：Local Security Extended 提供的 `yara_scan` MCP Tool。
- **有什么作用**：使用调用方提供的 YARA 规则匹配本地文件或目录。
- **什么时候调用**：已有可信检测规则，需要对样本、解包目录或取证文件做签名检查时。
- **输入什么数据**：`rules_path`（string，必填）；`target_path`（string，必填）；`recursive`（boolean，可选）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回退出状态、规则匹配证据行、stdout 和 stderr。

### `volatility_plugins`

- **这是什么**：Local Security Extended 提供的 `volatility_plugins` MCP Tool。
- **有什么作用**：列出并筛选 Volatility 3 内存取证插件。
- **什么时候调用**：分析内存镜像前，需要为操作系统和证据目标选择正确插件时。
- **输入什么数据**：`filter_text`（string，可选）。
- **返回什么数据**：返回插件名称和帮助文本。

### `volatility_analyze`

- **这是什么**：Local Security Extended 提供的 `volatility_analyze` MCP Tool。
- **有什么作用**：对内存镜像运行指定 Volatility 3 插件。
- **什么时候调用**：已确认镜像路径和插件名称，需要提取进程、网络、模块等内存证据时。
- **输入什么数据**：`image_path`（string，必填）；`plugin`（string，必填）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回插件 JSON 结果、退出状态和诊断文本。

### `ghidra_headless_analyze`

- **这是什么**：Local Security Extended 提供的 `ghidra_headless_analyze` MCP Tool。
- **有什么作用**：用 Ghidra Headless 导入并自动分析一个本地二进制文件。
- **什么时候调用**：需要建立反汇编、函数和引用分析基础，且不依赖 GUI 会话时。
- **输入什么数据**：`binary_path`（string，必填）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回分析日志、退出状态、耗时和隔离工程目录。

### `gdb_inspect`

- **这是什么**：Local Security Extended 提供的 `gdb_inspect` MCP Tool。
- **有什么作用**：用 GNU GDB batch 模式静态查看二进制文件、节区、函数或 main 反汇编。
- **什么时候调用**：需要快速核对二进制布局和符号，且不需要运行目标进程时。
- **输入什么数据**：`binary_path`（string，必填）；`mode`（string，可选）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回 GDB stdout、stderr、退出状态和耗时。

### `mitmproxy_flow_summary`

- **这是什么**：Local Security Extended 提供的 `mitmproxy_flow_summary` MCP Tool。
- **有什么作用**：离线读取 mitmproxy flow 文件并汇总 HTTP 会话。
- **什么时候调用**：已有授权采集的 flow 文件，需要检查方法、主机、状态码和请求响应元数据时。
- **输入什么数据**：`flow_path`（string，必填）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回脱敏后的 flow 摘要、最多 1000 条会话和 JSON Artifact。

### `subfinder_discover`

- **这是什么**：Local Security Extended 提供的 `subfinder_discover` MCP Tool。
- **有什么作用**：对授权域名执行被动子域发现。
- **什么时候调用**：资产盘点需要利用公开情报源扩展域名范围时。
- **输入什么数据**：`domain`（string，必填）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回 Subfinder JSONL 记录、执行状态和结果文件路径。

### `dnsx_resolve`

- **这是什么**：Local Security Extended 提供的 `dnsx_resolve` MCP Tool。
- **有什么作用**：批量解析主机名并收集 DNS 记录。
- **什么时候调用**：已有主机名列表，需要确认可解析资产和地址映射时。
- **输入什么数据**：`hosts`（array，必填）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回 dnsx JSONL 记录、执行状态和结果文件路径。

### `naabu_scan`

- **这是什么**：Local Security Extended 提供的 `naabu_scan` MCP Tool。
- **有什么作用**：对授权主机或 CIDR 执行 TCP 端口发现。
- **什么时候调用**：资产发现阶段需要快速确定开放端口，再交给 Nmap 深入识别时。
- **输入什么数据**：`target`（string，必填）；`ports`（string，可选）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回端口 JSONL 记录、执行状态和结果文件路径。

### `zap_baseline_scan`

- **这是什么**：Local Security Extended 提供的 `zap_baseline_scan` MCP Tool。
- **有什么作用**：用 OWASP ZAP Quick Scan 执行 Web 基线扫描。
- **什么时候调用**：授权 Web 目标需要动态检查常见风险并生成可审阅报告时。
- **输入什么数据**：`target_url`（string，必填）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回执行状态、进度日志和 HTML 报告路径。

### `binwalk_scan`

- **这是什么**：Local Security Extended 提供的 `binwalk_scan` MCP Tool。
- **有什么作用**：识别固件或二进制中的嵌入文件签名，可选计算熵。
- **什么时候调用**：固件、磁盘片段或未知二进制需要识别压缩包、文件系统和高熵区域时。
- **输入什么数据**：`file_path`（string，必填）；`entropy`（boolean，可选）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回 Binwalk 匹配、偏移、诊断信息和执行状态。

### `capa_analyze`

- **这是什么**：Local Security Extended 提供的 `capa_analyze` MCP Tool。
- **有什么作用**：用 capa 规则识别可执行文件表现出的程序能力。
- **什么时候调用**：恶意代码或未知程序需要快速形成行为能力假设时。
- **输入什么数据**：`file_path`（string，必填）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回 capa JSON 规则匹配、元数据、执行状态和结果路径。

### `floss_extract`

- **这是什么**：Local Security Extended 提供的 `floss_extract` MCP Tool。
- **有什么作用**：从可执行文件提取和解码静态、栈、紧凑及混淆字符串。
- **什么时候调用**：普通 strings 无法充分揭示恶意样本配置、URL 或命令文本时。
- **输入什么数据**：`file_path`（string，必填）；`minimum_length`（integer，可选）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回 FLOSS JSON 字符串分类、执行状态和结果路径。

### `oletools_analyze`

- **这是什么**：Local Security Extended 提供的 `oletools_analyze` MCP Tool。
- **有什么作用**：使用 oleid、olevba 或 rtfobj 分析 Office/OLE/RTF 文件。
- **什么时候调用**：文档样本需要检查宏、嵌入对象、格式异常和可疑指标时。
- **输入什么数据**：`file_path`（string，必填）；`analyzer`（string，可选）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回分析器输出、退出状态；olevba 同时返回解析后的 JSON。

### `checksec_binary`

- **这是什么**：Local Security Extended 提供的 `checksec_binary` MCP Tool。
- **有什么作用**：检查 ELF 的 RELRO、Canary、NX、PIE 等编译保护。
- **什么时候调用**：Pwn 或二进制审计开始时，需要确定利用约束和保护基线时。
- **输入什么数据**：`file_path`（string，必填）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回 checksec JSON、执行状态和诊断文本。

### `ropgadget_scan`

- **这是什么**：Local Security Extended 提供的 `ropgadget_scan` MCP Tool。
- **有什么作用**：从二进制中搜索 ROP、JOP 或系统调用 gadgets。
- **什么时候调用**：已获授权的漏洞利用研究需要构造控制流链并核对可用指令片段时。
- **输入什么数据**：`file_path`（string，必填）；`gadget_type`（string，可选）；`depth`（integer，可选）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回 gadget 地址与指令、唯一数量、执行状态和诊断文本。

### `pwntools_elf_summary`

- **这是什么**：Local Security Extended 提供的 `pwntools_elf_summary` MCP Tool。
- **有什么作用**：用 pwntools 解析 ELF 架构、入口点、保护、节区和符号。
- **什么时候调用**：Pwn 任务需要在编写交互或利用脚本前建立结构化二进制概况时。
- **输入什么数据**：`file_path`（string，必填）；`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回 ELF JSON 摘要、checksec 结果、节区和最多 500 个符号。

### `pwndbg_check`

- **这是什么**：Local Security Extended 提供的 `pwndbg_check` MCP Tool。
- **有什么作用**：检查独立 Ubuntu 中 Pwndbg 能否被 GDB 正常加载。
- **什么时候调用**：动态调试任务开始前确认 Pwndbg 运行环境，或诊断插件加载问题时。
- **输入什么数据**：`timeout_seconds`（integer，可选）。
- **返回什么数据**：返回 GDB/Pwndbg 加载输出、退出状态和耗时。
