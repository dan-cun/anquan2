import { graphqlRequest } from '../../services/graphqlClient.js'

const SKILL_FIELDS = `skillId name description version content checksum tags compatibleRoles source enabled metadata createdAt updatedAt`
const TODO_FIELDS = `todoId runId flowId taskId agentInstanceId title description status priority position dependsOn evidenceIds createdAt updatedAt completedAt`
const NOTE_FIELDS = `noteId runId flowId agentInstanceId kind content status evidenceIds tags createdAt updatedAt`
const SNAPSHOT_FIELDS = `snapshotId runId flowId agentInstanceId sourceFromSequence sourceToSequence estimatedTokensBefore estimatedTokensAfter narrativeSummary structured createdAt`

export async function listSkills() {
  const data = await graphqlRequest(`query Skills { skills { ${SKILL_FIELDS} } }`)
  return data.skills
}

export async function registerSkill(input) {
  const data = await graphqlRequest(
    `mutation RegisterSkill($input: RegisterSkillInput!) { registerSkill(input: $input) { ${SKILL_FIELDS} } }`,
    { input },
  )
  return data.registerSkill
}

export async function loadRunState(runId) {
  const data = await graphqlRequest(
    `query LongTermState($runId: ID!) {
      skillLoads(runId: $runId) { loadId skillId runId flowId agentInstanceId reason loadedAt unloadedAt }
      todos(runId: $runId) { ${TODO_FIELDS} }
      notes(runId: $runId, activeOnly: false) { ${NOTE_FIELDS} }
      contextSnapshots(runId: $runId) { ${SNAPSHOT_FIELDS} }
    }`,
    { runId },
  )
  return data
}

export async function loadSkill(input) {
  const data = await graphqlRequest(
    `mutation LoadSkill($input: LoadSkillInput!) { loadSkill(input: $input) { loadId skillId runId flowId agentInstanceId reason loadedAt unloadedAt } }`,
    { input },
  )
  return data.loadSkill
}

export async function createTodo(input) {
  const data = await graphqlRequest(
    `mutation CreateTodo($input: CreateTodoInput!) { createTodo(input: $input) { ${TODO_FIELDS} } }`,
    { input },
  )
  return data.createTodo
}

export async function updateTodo(todoId, input) {
  const data = await graphqlRequest(
    `mutation UpdateTodo($todoId: ID!, $input: UpdateTodoInput!) { updateTodo(todoId: $todoId, input: $input) { ${TODO_FIELDS} } }`,
    { todoId, input },
  )
  return data.updateTodo
}

export async function recordNote(input) {
  const data = await graphqlRequest(
    `mutation RecordNote($input: RecordNoteInput!) { recordNote(input: $input) { ${NOTE_FIELDS} } }`,
    { input },
  )
  return data.recordNote
}

export async function compressContext(runId, flowId) {
  const data = await graphqlRequest(
    `mutation CompressContext($runId: ID!, $flowId: ID!) { compressContext(runId: $runId, flowId: $flowId) { ${SNAPSHOT_FIELDS} } }`,
    { runId, flowId },
  )
  return data.compressContext
}
