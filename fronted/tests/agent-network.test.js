import assert from 'node:assert/strict'
import test from 'node:test'

import {
  collaborationState,
  nodeFromEvent,
  roleForNode,
} from '../src/app/agentNetwork.js'

test('maps runtime nodes to collaboration roles', () => {
  assert.equal(roleForNode('plan').id, 'planner')
  assert.equal(roleForNode('verify').id, 'reviewer')
  assert.equal(roleForNode('missing'), null)
})

test('derives live role status from websocket node events', () => {
  const state = collaborationState([
    { type: 'server.status', payload: { node: 'ingest' } },
    { type: 'server.status', payload: { node: 'plan' } },
  ])
  assert.equal(state.activeRole, 'planner')
  assert.equal(state.latestNode, 'plan')
  assert.equal(state.roles.find((item) => item.id === 'planner').status, 'active')
  assert.equal(state.roles.find((item) => item.id === 'orchestrator').status, 'completed')
})

test('maps mirrored ledger entries to graph nodes', () => {
  const event = {
    type: 'server.ledger_entry',
    payload: { entry: { event_type: 'runtime.verification.completed' } },
  }
  assert.equal(nodeFromEvent(event), 'verify')
})

test('marks the orchestrator waiting on an approval interrupt', () => {
  const state = collaborationState([
    { type: 'server.status', payload: { node: 'guardrail' } },
    { type: 'server.interrupt', payload: { approval_id: 'approval-1' } },
  ])
  assert.equal(state.roles.find((item) => item.id === 'orchestrator').status, 'waiting')
})

