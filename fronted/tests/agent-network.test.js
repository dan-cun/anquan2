import assert from 'node:assert/strict'
import test from 'node:test'

import {
  collaborationState,
  nativeCollaborationState,
  nodeFromEvent,
  roleForNode,
} from '../src/app/agentNetwork.js'

test('maps runtime nodes to collaboration roles', () => {
  assert.equal(roleForNode('plan').id, 'planner')
  assert.equal(roleForNode('verify').id, 'reviewer')
  assert.equal(roleForNode('missing'), null)
})

test('builds roles and delegation edges from native GraphQL records', () => {
  const state = nativeCollaborationState({
    agentDescriptors: [
      { role: 'ASSISTANT', displayName: 'Assistant', description: '', enabled: true },
      { role: 'SEARCHER', displayName: 'Searcher', description: '', enabled: true },
    ],
    agentInstances: [
      {
        instanceId: 'agent-1',
        role: 'ASSISTANT',
        status: 'COMPLETED',
        updatedAt: '2026-07-19T10:00:00Z',
      },
      {
        instanceId: 'agent-2',
        role: 'SEARCHER',
        status: 'RUNNING',
        updatedAt: '2026-07-19T10:00:01Z',
      },
    ],
    agentDelegations: [
      {
        delegationId: 'delegation-1',
        fromAgentInstanceId: 'agent-1',
        toAgentInstanceId: 'agent-2',
        toRole: 'SEARCHER',
        status: 'RUNNING',
      },
    ],
  })

  assert.equal(state.native, true)
  assert.equal(state.activeRole, 'searcher')
  assert.deepEqual(state.edges[0], {
    id: 'delegation-1',
    from: 'assistant',
    to: 'searcher',
    status: 'active',
  })
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
