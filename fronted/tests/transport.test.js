import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildFlowWebSocketUrl,
  EventCursor,
  getEventIdentity,
  ledgerEntryToSocketEvent,
  resolveApiBaseUrl,
  resolveWebSocketBaseUrl,
  unresolvedApprovalPayloads,
} from '../src/app/transport.js'
import {
  getModelProviderPreset,
  modelProviderOptions,
} from '../src/app/modelProviders.js'
import {
  flowStatusFromEvent,
  toConversationItem,
} from '../src/app/conversationEvents.js'

const location = {
  origin: 'https://secmind.example',
  protocol: 'https:',
  host: 'secmind.example',
}

test('uses the browser origin for same-origin HTTP and WebSocket traffic', () => {
  const apiBaseUrl = resolveApiBaseUrl(undefined, location)
  const websocketBaseUrl = resolveWebSocketBaseUrl(undefined, apiBaseUrl, location)

  assert.equal(apiBaseUrl, 'https://secmind.example')
  assert.equal(websocketBaseUrl, 'wss://secmind.example')
})

test('resolves Compose root-path configuration to valid absolute URLs', () => {
  const apiBaseUrl = resolveApiBaseUrl('/', location)
  const websocketBaseUrl = resolveWebSocketBaseUrl('/', apiBaseUrl, location)
  const flowWebSocketUrl = new URL(buildFlowWebSocketUrl(websocketBaseUrl, 'flow-1'))

  assert.equal(apiBaseUrl, 'https://secmind.example')
  assert.equal(websocketBaseUrl, 'wss://secmind.example')
  assert.equal(flowWebSocketUrl.href, 'wss://secmind.example/ws/flows/flow-1?after_sequence=0')
})

test('keeps explicit development endpoints configurable', () => {
  const apiBaseUrl = resolveApiBaseUrl('http://localhost:9000/', location)
  const websocketBaseUrl = resolveWebSocketBaseUrl('ws://localhost:9001/', apiBaseUrl, location)

  assert.equal(apiBaseUrl, 'http://localhost:9000')
  assert.equal(websocketBaseUrl, 'ws://localhost:9001')
})

test('adds the reconnect cursor to the flow WebSocket URL', () => {
  const url = new URL(buildFlowWebSocketUrl('wss://secmind.example', 'run/one', 17))

  assert.equal(url.pathname, '/ws/flows/run%2Fone')
  assert.equal(url.searchParams.get('after_sequence'), '17')
})

test('deduplicates events by run_id and sequence', () => {
  const cursor = new EventCursor()
  const first = { run_id: 'run-1', sequence: 4, request_id: 'request-a' }
  const duplicate = { run_id: 'run-1', sequence: 4, request_id: 'request-b' }
  const anotherRun = { run_id: 'run-2', sequence: 4, request_id: 'request-c' }

  assert.equal(cursor.accept(first), true)
  assert.equal(cursor.accept(duplicate), false)
  assert.equal(cursor.accept(anotherRun), true)
  assert.equal(cursor.afterSequence('run-1'), 4)
  assert.equal(cursor.afterSequence('run-2'), 4)
})

test('recognizes sequence fields nested in ledger messages', () => {
  const event = ledgerEntryToSocketEvent({
    flow_id: 'flow-1',
    seq: 9,
    event_type: 'interrupt.approval_required',
    payload: { approval_id: 'approval-1' },
    created_at: '2026-07-15T00:00:00Z',
  })

  assert.deepEqual(getEventIdentity(event), {
    key: 'flow-1:9',
    runId: 'flow-1',
    sequence: 9,
  })
  assert.equal(event.payload.entry.payload.approval_id, 'approval-1')
})

test('restores only approvals that have no later response', () => {
  const pending = { approval_id: 'approval-pending', message: 'review pending action' }
  const resolved = { approval_id: 'approval-resolved', message: 'review resolved action' }
  const entries = [
    { event_type: 'interrupt.approval_required', payload: pending },
    { event_type: 'interrupt.approval_required', payload: resolved },
    {
      event_type: 'input.approval_response',
      payload: { approval_id: 'approval-resolved', approved: false },
    },
  ]

  assert.deepEqual(unresolvedApprovalPayloads(entries), [pending])
})

test('provides named presets for supported OpenAI-compatible vendors', () => {
  const options = modelProviderOptions()
  const deepseek = getModelProviderPreset('deepseek')

  assert.ok(options.some((item) => item.value === 'deepseek'))
  assert.ok(options.some((item) => item.value === 'openai-compatible'))
  assert.deepEqual(deepseek, {
    value: 'deepseek',
    label: 'DeepSeek',
    model: 'deepseek-chat',
    baseUrl: 'https://api.deepseek.com',
  })
})

test('turns runtime envelopes into readable conversation output', () => {
  assert.deepEqual(
    toConversationItem({
      type: 'server.status',
      payload: { stage: 'langgraph.node.completed', node: 'report' },
    }),
    { kind: 'status', label: '报告智能体', body: '生成最终报告' },
  )
  assert.equal(
    toConversationItem({
      type: 'server.status',
      payload: { stage: 'runtime.started', message: 'Runtime audit started.' },
    }).body,
    '运行内核已启动，正在建立任务上下文',
  )
  assert.deepEqual(
    toConversationItem({
      type: 'server.done',
      payload: { result: '真实模型报告', report: { limitations: [] } },
    }),
    {
      kind: 'assistant',
      label: '报告智能体',
      body: '真实模型报告',
      report: { limitations: [] },
    },
  )
  assert.equal(
    toConversationItem({
      type: 'server.ledger_entry',
      payload: { entry: { event_type: 'runtime.plan.created', payload: {} } },
    }),
    null,
  )
  assert.equal(flowStatusFromEvent({ type: 'server.status' }), 'running')
  assert.equal(flowStatusFromEvent({ type: 'server.done' }), 'finished')
  assert.equal(flowStatusFromEvent({ type: 'server.error' }), 'failed')
})
