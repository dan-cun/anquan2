const CATEGORY_LABELS = {
  agent: '智能体',
  tool: '工具',
  mcp: 'MCP',
  decision: '决策',
  verification: '验证',
  approval: '审批',
  llm: '模型',
  model: '模型',
  plan: '规划',
  policy: '策略',
  context: '上下文',
  observation: '观察',
  evidence: '证据',
  finding: '发现',
  report: '报告',
  input: '输入',
  flow: '流程',
  run: '运行',
  step: '步骤',
  memory: '记忆',
  circuit: '熔断',
  loop: '防循环',
  system: '系统',
}

const EVENT_LABELS = {
  'flow.created': '创建流程',
  'flow.completed': '流程完成',
  'flow.failed': '流程失败',
  'input.user_message': '接收操作员任务',
  'input.ingested': '整理输入与附件',
  'run.queued': '运行已排队',
  'run.started': '运行已开始',
  'run.completed': '运行已完成',
  'run.failed': '运行失败',
  'scenario.classified': '识别安全场景',
  'context.retrieved': '检索任务上下文',
  'context.compressed': '压缩长期上下文',
  'plan.created': '生成执行计划',
  'plan.validated': '校验执行计划',
  'plan.revised': '修订执行计划',
  'decision.recorded': '记录操作决策',
  'step.selected': '选择下一步骤',
  'step.blocked': '步骤已阻止',
  'guardrail.evaluated': '评估执行边界',
  'guardrail.denied': '执行边界拒绝',
  'approval.requested': '请求人工审批',
  'approval.resolved': '审批已处理',
  'agent.created': '创建智能体',
  'agent.started': '智能体开始执行',
  'agent.delegated': '委派智能体任务',
  'agent.message': '智能体发送消息',
  'agent.waiting': '智能体等待中',
  'agent.stop_requested': '请求停止智能体',
  'agent.completed': '智能体完成任务',
  'agent.failed': '智能体执行失败',
  'agent.cancelled': '智能体已取消',
  'tool.started': '开始调用工具',
  'tool.completed': '工具调用完成',
  'tool.failed': '工具调用失败',
  'tool.timed_out': '工具调用超时',
  'tool.cancelled': '工具调用已取消',
  'tool.blocked': '工具调用被阻止',
  'mcp.connected': 'MCP Server 已连接',
  'mcp.disconnected': 'MCP Server 已断开',
  'mcp.call_started': '开始调用 MCP',
  'mcp.call_completed': 'MCP 调用完成',
  'mcp.call_failed': 'MCP 调用失败',
  'observation.recorded': '记录工具观察',
  'analysis.completed': '完成证据分析',
  'verification.started': '开始独立验证',
  'verification.completed': '完成独立验证',
  'reflection.completed': '完成策略反思',
  'finding.recorded': '记录安全发现',
  'evidence.recorded': '记录审计证据',
  'report.generated': '生成安全报告',
  'memory.candidate': '评估长期记忆',
  'memory.committed': '提交长期记忆',
  'loop.detected': '检测到重复操作',
  'strategy.changed': '切换执行策略',
  'circuit.opened': '工具熔断器已打开',
  'circuit.half_opened': '工具熔断器试探恢复',
  'circuit.closed': '工具熔断器已恢复',
  'llm.request': '发送模型请求',
  'llm.response': '收到模型响应',
  'llm.error': '模型调用失败',
}

const TERMINAL_FAILURES = ['failed', 'error', 'denied', 'blocked', 'timed_out', 'cancelled']
const TERMINAL_SUCCESSES = ['completed', 'resolved', 'connected', 'committed', 'generated']
const ACTIVE_SUFFIXES = ['started', 'queued', 'connecting', 'request']

function objectOrNull(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : null
}

function firstDefined(...values) {
  return values.find((value) => value !== undefined && value !== null)
}

function compactText(value, limit = 220) {
  if (typeof value !== 'string') return ''
  const normalized = value.replace(/\s+/g, ' ').trim()
  return normalized.length > limit ? `${normalized.slice(0, limit)}...` : normalized
}

function eventStatus(eventType, payload) {
  if (eventType === 'approval.requested' || eventType.endsWith('.waiting')) return 'waiting'
  if (TERMINAL_FAILURES.some((suffix) => eventType.includes(suffix))) return 'error'
  if (TERMINAL_SUCCESSES.some((suffix) => eventType.endsWith(suffix))) return 'success'
  if (ACTIVE_SUFFIXES.some((suffix) => eventType.endsWith(suffix))) return 'running'
  if (payload?.status && TERMINAL_FAILURES.includes(String(payload.status).toLowerCase())) {
    return 'error'
  }
  return 'neutral'
}

function normalizeCategory(value, eventType) {
  const explicit = String(value || '').toLowerCase()
  if (explicit) return explicit
  const prefix = eventType.split('.')[0]
  return CATEGORY_LABELS[prefix] ? prefix : 'system'
}

function eventLabel(eventType) {
  if (EVENT_LABELS[eventType]) return EVENT_LABELS[eventType]
  return eventType
    .split('.')
    .map((part) => part.replaceAll('_', ' '))
    .join(' / ')
}

function eventSummary(eventType, payload, decision) {
  if (decision?.rationale_summary || decision?.rationaleSummary) {
    return compactText(decision.rationale_summary || decision.rationaleSummary)
  }
  const direct = firstDefined(
    payload?.summary,
    payload?.message,
    payload?.reason,
    payload?.description,
    typeof payload?.result === 'string' ? payload.result : null,
    typeof payload?.content === 'string' ? payload.content : null,
  )
  if (direct) return compactText(direct)
  if (eventType === 'tool.started' || eventType === 'mcp.call_started') {
    return `调用 ${payload?.tool_name || payload?.tool_id || payload?.tool || payload?.name || '工具'}`
  }
  if (eventType === 'agent.delegated') {
    return `由 ${payload?.from_role || payload?.from_agent_instance_id || '上级智能体'} 委派给 ${payload?.to_role || '目标智能体'}`
  }
  if (payload?.finding_count !== undefined || payload?.evidence_count !== undefined) {
    return `发现 ${payload.finding_count || 0} 项，证据 ${payload.evidence_count || 0} 项`
  }
  return EVENT_LABELS[eventType] || '已记录结构化运行事件'
}

function extractParameters(eventType, payload) {
  if (eventType === 'llm.request' || eventType.startsWith('model.')) {
    return {
      parameters: payload?.parameters || {},
      messageCount: Array.isArray(payload?.messages) ? payload.messages.length : 0,
    }
  }
  return firstDefined(
    payload?.arguments,
    payload?.parameters,
    payload?.input,
    payload?.inputs,
    payload?.request,
  )
}

function publicPayload(eventType, payload) {
  if (eventType !== 'llm.request' && !eventType.startsWith('model.')) return payload
  const { messages, ...publicFields } = payload
  return {
    ...publicFields,
    message_count: Array.isArray(messages) ? messages.length : 0,
  }
}

function extractResult(eventType, payload) {
  if (eventType === 'llm.response' || (
    eventType.startsWith('model.') && eventType.endsWith('.response')
  )) {
    return {
      content: payload?.content,
      provider: payload?.provider,
      model: payload?.model,
      usage: payload?.raw?.usage,
    }
  }
  return firstDefined(
    payload?.result,
    payload?.output,
    payload?.data,
    payload?.text,
    payload?.response,
  )
}

function runtimeEnvelope(entry) {
  const outerType = entry?.event_type || entry?.eventType || ''
  const payload = objectOrNull(entry?.payload)
  if (outerType.startsWith('runtime.') && payload?.event_type) return payload
  if (outerType.startsWith('runtime.') && payload?.eventType) return payload
  return entry
}

export function projectLiveFeedEvent(input, index = 0) {
  const socketEntry = input?.payload?.entry || input?.payload?.ledger_entry
  const outer = socketEntry || input || {}
  const envelope = runtimeEnvelope(outer) || {}
  const eventType = envelope.event_type || envelope.eventType || outer.event_type || outer.eventType || 'system.unknown'
  const payload = objectOrNull(envelope.payload) || {}
  const context = objectOrNull(envelope.context) || {}
  const decision = objectOrNull(envelope.decision) || objectOrNull(payload.decision)
  const outerSequence = outer.seq || outer.sequence
  const sequence = envelope.sequence || outerSequence || index + 1
  const runId = envelope.run_id || envelope.runId || outer.run_id || outer.flow_id || input?.flow_id
  const eventId = envelope.event_id || envelope.eventId || `${runId || 'unknown'}:${sequence}:${eventType}`
  const category = normalizeCategory(envelope.category, eventType)
  const toolId = firstDefined(
    context.tool_invocation_id,
    context.toolInvocationId,
    payload.invocation_id,
    payload.invocationId,
    payload.tool_id,
    payload.toolId,
    payload.tool_name,
    payload.tool,
  )
  const agentId = firstDefined(
    context.agent_instance_id,
    context.agentInstanceId,
    payload.agent_instance_id,
    payload.agentInstanceId,
    payload.role,
  )
  const error = firstDefined(payload.error, payload.error_message, payload.errorMessage)

  return {
    id: String(eventId),
    runId,
    sequence,
    ledgerSequence: outerSequence,
    runtimeSequence: outer !== envelope ? envelope.sequence : null,
    eventType,
    transportEventType: outer.event_type || outer.eventType || eventType,
    category,
    categoryLabel: CATEGORY_LABELS[category] || CATEGORY_LABELS.system,
    status: eventStatus(eventType, payload),
    title: eventLabel(eventType),
    summary: eventSummary(eventType, payload, decision),
    actor: envelope.actor || outer.actor || 'system',
    timestamp: envelope.timestamp || outer.created_at || outer.timestamp || input?.timestamp,
    schemaVersion: envelope.schema_version || envelope.schemaVersion || '1.0',
    visibility: context.visibility || envelope.visibility || 'public',
    correlationId: context.correlation_id || context.correlationId || envelope.correlation_id || envelope.correlationId,
    decisionId: context.decision_id || context.decisionId || envelope.decision_id || envelope.decisionId || decision?.decision_id || decision?.decisionId,
    agentId,
    toolId,
    verificationVerdict: envelope.verification_verdict || envelope.verificationVerdict || payload.verdict,
    parameters: extractParameters(eventType, payload),
    result: extractResult(eventType, payload),
    error,
    decision,
    payload: publicPayload(eventType, payload),
    context,
    source: outer,
  }
}

export function projectLiveFeed(entries = []) {
  return entries.map(projectLiveFeedEvent)
}

export function filterLiveFeed(rows, { query = '', category = 'all', status = 'all' } = {}) {
  const normalizedQuery = query.trim().toLowerCase()
  return rows.filter((row) => {
    if (category !== 'all' && row.category !== category) return false
    if (status !== 'all' && row.status !== status) return false
    if (!normalizedQuery) return true
    const searchable = [
      row.title,
      row.summary,
      row.eventType,
      row.actor,
      row.agentId,
      row.toolId,
      row.correlationId,
      row.decisionId,
    ].filter(Boolean).join(' ').toLowerCase()
    return searchable.includes(normalizedQuery)
  })
}

export function liveFeedCategoryOptions(rows = []) {
  const categories = [...new Set(rows.map((row) => row.category))]
  return [
    { value: 'all', label: '全部类别' },
    ...categories.map((value) => ({ value, label: CATEGORY_LABELS[value] || value })),
  ]
}

export const LIVE_FEED_STATUS_OPTIONS = [
  { value: 'all', label: '全部状态' },
  { value: 'running', label: '执行中' },
  { value: 'success', label: '已完成' },
  { value: 'waiting', label: '等待中' },
  { value: 'error', label: '异常' },
  { value: 'neutral', label: '信息' },
]
