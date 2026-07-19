import assert from 'node:assert/strict'
import test from 'node:test'

import {
  mcpCatalogSummary,
  normalizeMcpServerInput,
} from '../src/app/features/mcp/model.js'
import {
  activePromptVersion,
  promptCatalogSummary,
} from '../src/app/features/prompts/model.js'
import { isFeatureRoute } from '../src/app/featureRoutes.js'

test('routes all operational pages through the feature application', () => {
  for (const route of ['/workbench', '/audit/run-1', '/prompts', '/mcp', '/models']) {
    assert.equal(isFeatureRoute(route), true)
  }
  assert.equal(isFeatureRoute('/'), false)
})

test('derives Prompt state from the explicit active version id', () => {
  const prompt = {
    activeVersionId: 'v1',
    agentRole: 'ASSISTANT',
    versions: [
      { versionId: 'v2', version: 2, source: 'graphql' },
      { versionId: 'v1', version: 1, source: 'workbook:prompts.xlsx' },
    ],
  }

  assert.equal(activePromptVersion(prompt).version, 1)
  assert.deepEqual(promptCatalogSummary([prompt]), {
    total: 1,
    active: 1,
    agent: 1,
    workbook: 1,
  })
})

test('normalizes stdio and HTTP MCP registration inputs', () => {
  assert.deepEqual(normalizeMcpServerInput({
    serverId: ' local ',
    name: ' Tools ',
    transport: 'STDIO',
    command: ' python ',
    args: '-m server',
    cwd: ' C:/work ',
    enabled: true,
  }), {
    serverId: 'local',
    name: 'Tools',
    transport: 'STDIO',
    command: 'python',
    args: ['-m', 'server'],
    cwd: 'C:/work',
    enabled: true,
  })

  assert.equal(normalizeMcpServerInput({
    serverId: 'remote',
    name: 'Remote',
    transport: 'STREAMABLE_HTTP',
    url: ' http://localhost:9000/mcp ',
  }).url, 'http://localhost:9000/mcp')
})

test('summarizes MCP servers, capabilities, and unified tools', () => {
  const servers = [
    { status: 'CONNECTED', capabilities: [{}, {}] },
    { status: 'FAILED', capabilities: [{}] },
  ]
  assert.deepEqual(mcpCatalogSummary(servers, [{}, {}]), {
    servers: 2,
    connected: 1,
    capabilities: 3,
    tools: 2,
  })
})
