import { graphqlRequest } from '../../services/graphqlClient.js'

const SERVER_FIELDS = `
  serverId name transport enabled status protocolVersion errorMessage metadata
  capabilities { capabilityId serverId kind name description inputSchema metadata }
`

export async function loadMcpCatalog() {
  return graphqlRequest(`query MCPCatalog {
    mcpServers { ${SERVER_FIELDS} }
    tools { toolId name description origin serverId inputSchema outputSchema annotations }
  }`)
}

export async function registerMcpServer(input) {
  const data = await graphqlRequest(
    `mutation RegisterMCPServer($input: RegisterMCPServerInput!) {
      registerMCPServer(input: $input) { ${SERVER_FIELDS} }
    }`,
    { input },
  )
  return data.registerMCPServer
}

export async function updateMcpServer(serverId, input) {
  const data = await graphqlRequest(
    `mutation UpdateMCPServer($serverId: ID!, $input: UpdateMCPServerInput!) {
      updateMCPServer(serverId: $serverId, input: $input) { ${SERVER_FIELDS} }
    }`,
    { serverId, input },
  )
  return data.updateMCPServer
}

export async function refreshMcpCapabilities(serverId = null) {
  const data = await graphqlRequest(
    `mutation RefreshMCP($serverId: ID) {
      refreshMCPCapabilities(serverId: $serverId) { ${SERVER_FIELDS} }
    }`,
    { serverId },
  )
  return data.refreshMCPCapabilities
}

export async function removeMcpServer(serverId) {
  const data = await graphqlRequest(
    `mutation RemoveMCP($serverId: ID!) { removeMCPServer(serverId: $serverId) }`,
    { serverId },
  )
  return data.removeMCPServer
}
