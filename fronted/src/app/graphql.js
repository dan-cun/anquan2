import { graphqlRequest } from './services/graphqlClient.js'

export function loadNativeNetwork(flowId) {
  return graphqlRequest(
    `query NativeNetwork($flowId: ID!) {
      agentDescriptors { role displayName description capabilities enabled }
      agentInstances(flowId: $flowId) {
        instanceId runId flowId role status taskId parentInstanceId modelProfile updatedAt completedAt
      }
      agentDelegations(flowId: $flowId) {
        delegationId fromAgentInstanceId toRole toAgentInstanceId status resultSummary createdAt completedAt
      }
      mcpServers { serverId name transport status capabilities { capabilityId kind name } }
      tools { toolId name origin serverId description }
    }`,
    { flowId },
  )
}

export { graphqlRequest }
