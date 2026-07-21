import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import { nativeCollaborationState } from '../src/app/agentNetwork.js'

test('projects cancelled native Agents as stopped rather than failed', () => {
  const state = nativeCollaborationState({
    agentDescriptors: [
      { role: 'SEARCHER', displayName: 'Searcher', description: '', enabled: true },
    ],
    agentInstances: [
      {
        instanceId: 'agent-stopped',
        role: 'SEARCHER',
        status: 'CANCELLED',
        updatedAt: '2026-07-20T00:00:00Z',
      },
    ],
    agentDelegations: [],
  })

  assert.equal(state.roles[0].status, 'cancelled')
  assert.equal(state.activeRole, null)
})

test('ships all four Agent Graph controls through GraphQL', () => {
  const api = readFileSync(
    new URL('../src/app/features/agentGraph/api.js', import.meta.url),
    'utf8',
  )
  const component = readFileSync(
    new URL('../src/app/features/agentGraph/AgentGraphControls.jsx', import.meta.url),
    'utf8',
  )
  const app = readFileSync(new URL('../src/app/App.jsx', import.meta.url), 'utf8')

  for (const operation of ['createAgent', 'sendAgentMessage', 'waitAgent', 'stopAgent']) {
    assert.match(api, new RegExp(operation))
  }
  for (const tab of ["key: 'create'", "key: 'message'", "key: 'wait'", "key: 'stop'"]) {
    assert.match(component, new RegExp(tab))
  }
  assert.match(app, /<AgentGraphControls/)
})
