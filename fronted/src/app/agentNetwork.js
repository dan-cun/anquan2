export const AGENT_ROLES = [
  {
    id: 'orchestrator',
    name: '主控智能体',
    shortName: '主控',
    description: '接收目标、维护运行状态并调度各角色',
    nodes: ['confirmation_gate', 'ingest', 'classify', 'select_step', 'approval', 'record_denial'],
  },
  {
    id: 'planner',
    name: '规划智能体',
    shortName: '规划',
    description: '检索上下文、拆解任务并校验执行计划',
    nodes: ['retrieve_context', 'plan', 'validate_plan'],
  },
  {
    id: 'executor',
    name: '执行智能体',
    shortName: '执行',
    description: '在受控环境中调用安全工具并采集结果',
    nodes: ['guardrail', 'execute', 'observe'],
  },
  {
    id: 'reviewer',
    name: '审查智能体',
    shortName: '审查',
    description: '分析证据、验证结论并触发有限重试',
    nodes: ['analyze', 'verify', 'reflect'],
  },
  {
    id: 'reporter',
    name: '报告智能体',
    shortName: '报告',
    description: '汇总结论并提交已验证的长期记忆',
    nodes: ['report', 'memory_commit'],
  },
]

export const AGENT_EDGES = [
  ['orchestrator', 'planner'],
  ['planner', 'orchestrator'],
  ['orchestrator', 'executor'],
  ['executor', 'reviewer'],
  ['reviewer', 'orchestrator'],
  ['reviewer', 'reporter'],
]

export const NODE_LABELS = {
  confirmation_gate: '前置授权确认',
  ingest: '整理任务与附件',
  classify: '识别安全场景',
  retrieve_context: '检索知识上下文',
  plan: '生成执行计划',
  validate_plan: '校验计划边界',
  select_step: '选择下一步骤',
  guardrail: '执行风险策略',
  approval: '等待人工审批',
  record_denial: '记录拒绝结果',
  execute: '调用受控工具',
  observe: '采集工具证据',
  analyze: '归一化分析结果',
  verify: '验证发现与证据',
  reflect: '反思并调整策略',
  report: '生成最终报告',
  memory_commit: '提交验证记忆',
}

const roleByNode = new Map(
  AGENT_ROLES.flatMap((role) => role.nodes.map((node) => [node, role])),
)

export function roleForNode(node) {
  return roleByNode.get(node) || null
}

export function nodeFromEvent(event) {
  if (event?.type === 'server.status' && event.payload?.node) return event.payload.node
  const entry = event?.payload?.entry || event?.payload?.ledger_entry
  if (!entry?.event_type?.startsWith('runtime.')) return null
  const runtimeType = entry.event_type.slice('runtime.'.length)
  const runtimeNode = {
    'input.ingested': 'ingest',
    'scenario.classified': 'classify',
    'context.retrieved': 'retrieve_context',
    'plan.created': 'plan',
    'plan.validated': 'validate_plan',
    'step.selected': 'select_step',
    'guardrail.evaluated': 'guardrail',
    'approval.requested': 'approval',
    'step.denied': 'record_denial',
    'tool.completed': 'execute',
    'observation.recorded': 'observe',
    'analysis.completed': 'analyze',
    'verification.completed': 'verify',
    'reflection.completed': 'reflect',
    'report.generated': 'report',
    'memory.committed': 'memory_commit',
    'memory.candidate': 'memory_commit',
  }
  return runtimeNode[runtimeType] || null
}

export function collaborationState(events = []) {
  const completedNodes = []
  const seenNodes = new Set()
  for (const event of events) {
    const node = nodeFromEvent(event)
    if (node && !seenNodes.has(node)) {
      seenNodes.add(node)
      completedNodes.push(node)
    }
  }

  const latestNode = [...events].reverse().map(nodeFromEvent).find(Boolean) || null
  const activeRole = roleForNode(latestNode)?.id || null
  const terminal = [...events].reverse().find((event) =>
    ['server.done', 'server.error', 'server.interrupt'].includes(event?.type),
  )

  const roles = AGENT_ROLES.map((role) => {
    const completedCount = role.nodes.filter((node) => seenNodes.has(node)).length
    let status = completedCount ? 'completed' : 'idle'
    if (role.id === activeRole) status = 'active'
    if (terminal?.type === 'server.interrupt' && role.id === 'orchestrator') status = 'waiting'
    if (terminal?.type === 'server.error' && role.id === activeRole) status = 'failed'
    return { ...role, status, completedCount }
  })

  return { roles, latestNode, activeRole, completedNodes }
}

