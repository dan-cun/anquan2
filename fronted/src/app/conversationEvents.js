import { NODE_LABELS, roleForNode } from './agentNetwork.js'

const STAGE_MESSAGES = {
  'runtime.started': '运行内核已启动，正在建立任务上下文',
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
    return { kind: 'user', label: '操作员', body: event.payload?.content || '' }
  }
  if (event.type === 'server.status') {
    const node = event.payload?.node
    const role = roleForNode(node)
    return {
      kind: 'status',
      label: role?.name || '运行状态',
      body:
        NODE_LABELS[node] ||
        STAGE_MESSAGES[event.payload?.stage] ||
        event.payload?.message ||
        event.payload?.stage ||
        '任务正在执行',
    }
  }
  if (event.type === 'server.done') {
    return {
      kind: 'assistant',
      label: '报告智能体',
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
      label: '人工审批',
      body: event.payload?.message || '任务正在等待操作员确认。',
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
