export function activePromptVersion(prompt) {
  return prompt?.versions?.find((version) => version.versionId === prompt.activeVersionId) || null
}

export function promptCatalogSummary(prompts = []) {
  return {
    total: prompts.length,
    active: prompts.filter((prompt) => activePromptVersion(prompt)).length,
    agent: prompts.filter((prompt) => prompt.agentRole).length,
    workbook: prompts.filter((prompt) => activePromptVersion(prompt)?.source?.startsWith('workbook:')).length,
  }
}

export function promptStatusColor(status) {
  return { ACTIVE: 'success', DRAFT: 'default', ARCHIVED: 'warning' }[status] || 'default'
}
