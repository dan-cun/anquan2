function trimTrailingSlash(value) {
  return value.replace(/\/+$/, '')
}

export function resolveApiBaseUrl(configuredBaseUrl, location) {
  const configured = configuredBaseUrl?.trim()
  const url = new URL(configured || location.origin, location.origin)
  return trimTrailingSlash(url.href)
}

export function resolveWebSocketBaseUrl(configuredBaseUrl, apiBaseUrl, location) {
  const configured = configuredBaseUrl?.trim()
  const url = new URL(configured || apiBaseUrl, location.origin)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return trimTrailingSlash(url.href)
}

export function buildFlowWebSocketUrl(baseUrl, flowId, afterSequence = 0) {
  const url = new URL(`${trimTrailingSlash(baseUrl)}/ws/flows/${encodeURIComponent(flowId)}`)
  url.searchParams.set('after_sequence', String(Math.max(0, afterSequence)))
  return url.href
}

function positiveSequence(...values) {
  for (const value of values) {
    const sequence = Number(value)
    if (Number.isInteger(sequence) && sequence > 0) return sequence
  }
  return null
}

export function getEventIdentity(event, fallbackRunId) {
  const entry = event?.payload?.entry || event?.payload?.ledger_entry
  const runId =
    event?.run_id ||
    event?.flow_id ||
    event?.payload?.run_id ||
    entry?.run_id ||
    entry?.flow_id ||
    fallbackRunId
  const sequence = positiveSequence(
    event?.sequence,
    event?.payload?.sequence,
    entry?.sequence,
    entry?.seq,
  )

  if (runId && sequence) {
    return { key: `${runId}:${sequence}`, runId, sequence }
  }
  if (event?.request_id) {
    return { key: `${runId || 'unknown'}:request:${event.request_id}`, runId, sequence: null }
  }
  return { key: null, runId, sequence: null }
}

export class EventCursor {
  constructor() {
    this.seenKeys = new Set()
    this.lastSequences = new Map()
  }

  accept(event, fallbackRunId) {
    const identity = getEventIdentity(event, fallbackRunId)
    if (identity.key && this.seenKeys.has(identity.key)) return false
    if (identity.key) this.seenKeys.add(identity.key)
    if (identity.runId && identity.sequence) {
      const current = this.lastSequences.get(identity.runId) || 0
      this.lastSequences.set(identity.runId, Math.max(current, identity.sequence))
    }
    return true
  }

  afterSequence(runId) {
    return this.lastSequences.get(runId) || 0
  }

  resetRun(runId) {
    this.lastSequences.delete(runId)
    const prefix = `${runId}:`
    for (const key of this.seenKeys) {
      if (key.startsWith(prefix)) this.seenKeys.delete(key)
    }
  }
}

export function ledgerEntryToSocketEvent(entry) {
  const runId = entry.run_id || entry.flow_id
  const sequence = entry.sequence || entry.seq
  return {
    type: 'server.ledger_entry',
    run_id: runId,
    flow_id: entry.flow_id || runId,
    sequence,
    request_id: `ledger-${runId}-${sequence}`,
    timestamp: entry.timestamp || entry.created_at,
    payload: { entry },
  }
}

export function unresolvedApprovalPayloads(entries) {
  const resolvedIds = new Set(
    entries
      .filter((entry) => entry.event_type === 'input.approval_response')
      .map((entry) => entry.payload?.approval_id)
      .filter(Boolean),
  )
  return entries
    .filter((entry) => entry.event_type?.startsWith('interrupt.'))
    .map((entry) => entry.payload)
    .filter((payload) => payload?.approval_id && !resolvedIds.has(payload.approval_id))
}
