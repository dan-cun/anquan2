import { graphqlRequest } from '../../services/graphqlClient.js'

const AGENT_INSTANCE_FIELDS = `
  instanceId runId flowId role status taskId parentInstanceId
  modelProfile startedAt updatedAt completedAt metadata
`

export async function createAgent(input) {
  const data = await graphqlRequest(
    `mutation CreateAgent($input: CreateAgentInput!) {
      createAgent(input: $input) { ${AGENT_INSTANCE_FIELDS} }
    }`,
    { input },
  )
  return data.createAgent
}

export async function sendAgentMessage(input) {
  const data = await graphqlRequest(
    `mutation SendAgentMessage($input: SendAgentMessageInput!) {
      sendAgentMessage(input: $input) {
        messageId runId flowId fromAgentInstanceId toAgentInstanceId
        toRole kind summary payloadRef sequence timestamp metadata
      }
    }`,
    { input },
  )
  return data.sendAgentMessage
}

export async function waitAgent(agentInstanceId, timeoutSeconds = 30) {
  const data = await graphqlRequest(
    `mutation WaitAgent($agentInstanceId: ID!, $timeoutSeconds: Int!) {
      waitAgent(agentInstanceId: $agentInstanceId, timeoutSeconds: $timeoutSeconds) {
        ${AGENT_INSTANCE_FIELDS}
      }
    }`,
    { agentInstanceId, timeoutSeconds },
  )
  return data.waitAgent
}

export async function stopAgent(agentInstanceId, reason) {
  const data = await graphqlRequest(
    `mutation StopAgent($agentInstanceId: ID!, $reason: String!) {
      stopAgent(agentInstanceId: $agentInstanceId, reason: $reason) {
        ${AGENT_INSTANCE_FIELDS}
      }
    }`,
    { agentInstanceId, reason },
  )
  return data.stopAgent
}
