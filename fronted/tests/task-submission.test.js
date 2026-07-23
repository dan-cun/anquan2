import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildTaskMetadata,
  mergeTaskFiles,
} from '../src/app/taskSubmission.js'

function file(name, size, lastModified) {
  return { name, size, lastModified }
}

test('keeps ZIP, PNG, and arbitrary binary inputs while removing exact duplicates', () => {
  const zip = file('evidence.zip', 120, 1)
  const png = file('screen.png', 240, 2)
  const binary = file('sample.bin', 360, 3)

  assert.deepEqual(
    mergeTaskFiles([zip], [zip, png, binary]),
    [zip, png, binary],
  )
})

test('builds runtime attachment metadata and preserves distinct duplicate names', () => {
  const metadata = buildTaskMetadata({
    uploads: [
      { ref: 'ref-zip', name: 'evidence.zip' },
      { ref: 'ref-png', name: 'screen.png' },
      { ref: 'ref-png-2', name: 'screen.png' },
    ],
    authorizationScope: '  authorized local workspace  ',
    constraints: 'read only\nno external targets\n',
    autonomyPolicy: 'automatic',
    submittedAt: '2026-07-22T00:00:00.000Z',
  })

  assert.deepEqual(metadata.attachments, [
    { ref: 'ref-zip', name: 'evidence.zip' },
    { ref: 'ref-png', name: 'screen.png' },
    { ref: 'ref-png-2', name: 'screen (2).png' },
  ])
  assert.deepEqual(metadata.target_scope, ['authorized local workspace'])
  assert.deepEqual(metadata.constraints, ['read only', 'no external targets'])
  assert.equal(metadata.autonomy_policy, 'automatic')
  assert.deepEqual(metadata.expected_outputs, [
    'security_report',
    'evidence',
    'reproduction_steps',
  ])
})
