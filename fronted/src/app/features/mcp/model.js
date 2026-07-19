export function mcpStatusColor(status) {
  return {
    CONNECTED: 'success',
    CONNECTING: 'processing',
    DEGRADED: 'warning',
    FAILED: 'error',
    DISCONNECTED: 'default',
  }[status] || 'default'
}

export function mcpCatalogSummary(servers = [], tools = []) {
  return {
    servers: servers.length,
    connected: servers.filter((server) => server.status === 'CONNECTED').length,
    capabilities: servers.reduce((total, server) => total + server.capabilities.length, 0),
    tools: tools.length,
  }
}

export function normalizeMcpServerInput(values) {
  const input = {
    serverId: values.serverId.trim(),
    name: values.name.trim(),
    transport: values.transport,
    enabled: values.enabled !== false,
  }
  if (values.transport === 'STDIO') {
    input.command = values.command.trim()
    input.args = String(values.args || '').split(/\s+/).filter(Boolean)
    if (values.cwd?.trim()) input.cwd = values.cwd.trim()
  } else {
    input.url = values.url.trim()
  }
  return input
}
