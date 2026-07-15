const NODE_MESSAGES = {
  confirmation_gate: '已处理前置确认',
  ingest: '已整理任务输入和附件',
  classify: '已识别安全任务类型',
  retrieve_context: '已检索可用知识上下文',
  plan: '模型已生成执行计划',
  validate_plan: '已完成计划安全校验',
  select_step: '已选择下一执行步骤',
  guardrail: '已完成风险策略检查',
  approval: '正在等待人工确认',
  record_denial: '已记录拒绝原因',
  execute: '已完成受控执行',
  observe: '已采集执行证据',
  analyze: '已分析安全证据',
  verify: '已验证发现与证据',
  reflect: '已调整执行策略',
  report: '模型已生成最终报告',
  memory_commit: '已完成审计记忆处理',
}

const STAGE_MESSAGES = {
  'runtime.started': '正在分析任务并准备执行计划',
}

function ledgerConversationItem(entry) {
  if (!entry) return null
  if (entry.event_type === 'flow.completed') {
    return {
      kind: 'assistant',
      label: 'SecMind',
      body: entry.payload?.result || '流程已完成。',
      report: entry.payload?.report || null,
    }
  }
  if (entry.event_type === 'flow.failed') {
    return {
      kind: 'error',
      label: '运行错误',
      body: entry.payload?.message || '流程执行失败。',
    }
  }
  return null
}

export function toConversationItem(event) {
  if (!event) return null
  if (event.type === 'client.user_message') {
    return { kind: 'user', label: '用户', body: event.payload?.content || '' }
  }
  if (event.type === 'server.status') {
    const node = event.payload?.node
    return {
      kind: 'status',
      label: '执行进度',
      body:
        NODE_MESSAGES[node] ||
        STAGE_MESSAGES[event.payload?.stage] ||
        event.payload?.message ||
        event.payload?.stage ||
        '任务正在执行',
    }
  }
  if (event.type === 'server.done') {
    return {
      kind: 'assistant',
      label: 'SecMind',
      body: event.payload?.result || '流程已完成。',
      report: event.payload?.report || null,
    }
  }
  if (event.type === 'server.error') {
    return {
      kind: 'error',
      label: '运行错误',
      body: event.payload?.message || '后端执行失败。',
    }
  }
  if (event.type === 'server.interrupt') {
    return {
      kind: 'status',
      label: '人工确认',
      body: event.payload?.message || '任务等待人工确认。',
    }
  }
  if (event.type === 'server.ledger_entry') {
    return ledgerConversationItem(event.payload?.entry || event.payload?.ledger_entry)
  }
  return null
}

export function flowStatusFromEvent(event) {
  if (event?.type === 'server.done') return 'finished'
  if (event?.type === 'server.interrupt') return 'waiting'
  if (event?.type === 'server.error') return 'failed'
  if (event?.type === 'server.status') return 'running'
  return null
}
