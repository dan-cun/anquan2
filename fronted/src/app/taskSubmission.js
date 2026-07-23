const DEFAULT_EXPECTED_OUTPUTS = [
  'security_report',
  'evidence',
  'reproduction_steps',
]

function fileKey(file) {
  return [file.name, file.size, file.lastModified].join('\u0000')
}

export function mergeTaskFiles(current = [], incoming = []) {
  const merged = [...current]
  const known = new Set(current.map(fileKey))
  for (const file of incoming) {
    const key = fileKey(file)
    if (!known.has(key)) {
      known.add(key)
      merged.push(file)
    }
  }
  return merged
}

function uniqueAttachmentName(name, usedNames) {
  const normalized = String(name || 'upload.bin').trim() || 'upload.bin'
  if (!usedNames.has(normalized)) {
    usedNames.add(normalized)
    return normalized
  }
  const dot = normalized.lastIndexOf('.')
  const base = dot > 0 ? normalized.slice(0, dot) : normalized
  const extension = dot > 0 ? normalized.slice(dot) : ''
  let index = 2
  let candidate = `${base} (${index})${extension}`
  while (usedNames.has(candidate)) {
    index += 1
    candidate = `${base} (${index})${extension}`
  }
  usedNames.add(candidate)
  return candidate
}

export function buildTaskMetadata({
  uploads = [],
  authorizationScope = '',
  constraints = '',
  autonomyPolicy = 'graded',
  submittedAt = new Date().toISOString(),
} = {}) {
  const usedNames = new Set()
  return {
    source: 'fronted.workbench.task_form',
    submitted_at: submittedAt,
    attachments: uploads.map((upload) => ({
      ref: upload.ref,
      name: uniqueAttachmentName(upload.name, usedNames),
    })),
    target_scope: authorizationScope.trim() ? [authorizationScope.trim()] : [],
    constraints: constraints
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean),
    expected_outputs: DEFAULT_EXPECTED_OUTPUTS,
    autonomy_policy: autonomyPolicy,
  }
}
