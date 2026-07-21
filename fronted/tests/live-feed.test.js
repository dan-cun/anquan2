import assert from 'node:assert/strict'
import test from 'node:test'

import {
  filterLiveFeed,
  liveFeedCategoryOptions,
  projectLiveFeed,
  projectLiveFeedEvent,
} from '../src/app/liveFeed.js'

test('projects nested runtime tool events without altering parameters or results', () => {
  const row = projectLiveFeedEvent({
    flow_id: 'flow-1',
    seq: 18,
    event_type: 'runtime.tool.completed',
    actor: 'tool_gateway',
    created_at: '2026-07-20T01:02:03Z',
    payload: {
      schema_version: '1.1',
      event_id: 'event-18',
      run_id: 'run-1',
      sequence: 12,
      event_type: 'tool.completed',
      actor: 'tool_gateway',
      context: {
        correlation_id: 'operation-1',
        decision_id: 'decision-1',
        tool_invocation_id: 'invocation-1',
        visibility: 'public',
      },
      payload: {
        tool_id: 'mcp:scanner:scan',
        arguments: { target: 'authorized.example', ports: [80, 443] },
        result: { open_ports: [443], raw_ref: 'artifact://scan-1' },
      },
    },
  })

  assert.equal(row.id, 'event-18')
  assert.equal(row.sequence, 12)
  assert.equal(row.ledgerSequence, 18)
  assert.equal(row.category, 'tool')
  assert.equal(row.status, 'success')
  assert.equal(row.toolId, 'invocation-1')
  assert.deepEqual(row.parameters, { target: 'authorized.example', ports: [80, 443] })
  assert.deepEqual(row.result, { open_ports: [443], raw_ref: 'artifact://scan-1' })
})

test('projects public decisions and typed verification verdicts', () => {
  const rows = projectLiveFeed([
    {
      eventId: 'decision-event',
      runId: 'run-1',
      sequence: 4,
      eventType: 'decision.recorded',
      category: 'DECISION',
      actor: 'primary_agent',
      timestamp: '2026-07-20T01:00:00Z',
      context: { decisionId: 'decision-1' },
      decision: {
        decisionId: 'decision-1',
        kind: 'TOOL',
        decision: '调用扫描工具',
        rationaleSummary: '当前证据缺少端口状态。',
        confidence: 0.9,
      },
      payload: {},
    },
    {
      event_id: 'verify-event',
      run_id: 'run-1',
      sequence: 8,
      event_type: 'verification.completed',
      actor: 'verifier',
      payload: { verdict: 'inconclusive', evidence_ids: ['evidence-1'] },
    },
  ])

  assert.equal(rows[0].category, 'decision')
  assert.equal(rows[0].summary, '当前证据缺少端口状态。')
  assert.equal(rows[0].decisionId, 'decision-1')
  assert.equal(rows[1].verificationVerdict, 'inconclusive')
})

test('filters by category, status, and searchable tool identity', () => {
  const rows = projectLiveFeed([
    { sequence: 1, event_type: 'agent.started', actor: 'coder', payload: {} },
    {
      sequence: 2,
      event_type: 'tool.failed',
      actor: 'tool_gateway',
      payload: { tool_id: 'mcp:scanner:scan', error: 'connection refused' },
    },
  ])

  assert.deepEqual(filterLiveFeed(rows, { category: 'agent' }).map((row) => row.sequence), [1])
  assert.deepEqual(filterLiveFeed(rows, { status: 'error' }).map((row) => row.sequence), [2])
  assert.deepEqual(filterLiveFeed(rows, { query: 'scanner' }).map((row) => row.sequence), [2])
  assert.deepEqual(liveFeedCategoryOptions(rows), [
    { value: 'all', label: '全部类别' },
    { value: 'agent', label: '智能体' },
    { value: 'tool', label: '工具' },
  ])
})

test('does not expose model prompt messages in expandable public payload', () => {
  const row = projectLiveFeedEvent({
    sequence: 3,
    event_type: 'llm.request',
    actor: 'llm_provider',
    payload: {
      messages: [{ role: 'system', content: 'private system instruction' }],
      parameters: { temperature: 0.2 },
      provider: 'qwen',
    },
  })

  assert.equal(row.payload.messages, undefined)
  assert.equal(row.payload.message_count, 1)
  assert.deepEqual(row.parameters, {
    parameters: { temperature: 0.2 },
    messageCount: 1,
  })
})
