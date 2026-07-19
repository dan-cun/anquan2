import { graphqlRequest } from '../../services/graphqlClient.js'

const PROMPT_FIELDS = `
  promptKey name category messageRole agentRole sourcePath variables activeVersionId metadata
  versions { versionId promptKey version content variables checksum status source createdAt activatedAt }
`

export async function listPrompts() {
  const data = await graphqlRequest(`query PromptCatalog { prompts { ${PROMPT_FIELDS} } }`)
  return data.prompts
}

export async function createPromptVersion(promptKey, content, source = 'workbench') {
  const data = await graphqlRequest(
    `mutation CreatePromptVersion($input: CreatePromptVersionInput!) {
      createPromptVersion(input: $input) {
        versionId promptKey version content variables checksum status source createdAt activatedAt
      }
    }`,
    { input: { promptKey, content, source } },
  )
  return data.createPromptVersion
}

export async function enablePromptVersion(promptKey, versionId) {
  const data = await graphqlRequest(
    `mutation EnablePromptVersion($promptKey: ID!, $versionId: ID!) {
      enablePromptVersion(promptKey: $promptKey, versionId: $versionId) { ${PROMPT_FIELDS} }
    }`,
    { promptKey, versionId },
  )
  return data.enablePromptVersion
}

export async function importPromptWorkbook(workbookRef = '/app/config/native-prompts.xlsx') {
  const data = await graphqlRequest(
    `mutation ImportPrompts($workbookRef: String!) {
      importPrompts(workbookRef: $workbookRef) { ${PROMPT_FIELDS} }
    }`,
    { workbookRef },
  )
  return data.importPrompts
}
