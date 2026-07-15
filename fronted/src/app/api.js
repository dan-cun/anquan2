import { resolveApiBaseUrl, resolveWebSocketBaseUrl } from './transport.js'

export const API_BASE_URL = resolveApiBaseUrl(
  import.meta.env.VITE_API_BASE_URL,
  window.location,
)

export const WS_BASE_URL = resolveWebSocketBaseUrl(
  import.meta.env.VITE_WS_BASE_URL,
  API_BASE_URL,
  window.location,
)

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  })

  if (!response.ok) {
    const raw = await response.text()
    let detail = raw
    try {
      detail = JSON.parse(raw).detail || raw
    } catch {
      // Keep non-JSON error responses readable.
    }
    throw new Error(detail || `Request failed with ${response.status}`)
  }

  if (response.status === 204) {
    return null
  }

  return response.json()
}

export function getInfo() {
  return request('/api/v1/info')
}

export function listFlows() {
  return request('/api/v1/flows')
}

export function createFlow(payload) {
  return request('/api/v1/flows', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listLedgerEntries(flowId, { afterSequence = 0 } = {}) {
  const query = new URLSearchParams()
  if (afterSequence > 0) {
    query.set('after_sequence', String(afterSequence))
  }
  const suffix = query.size ? `?${query}` : ''
  return request(`/api/v1/ledger/${encodeURIComponent(flowId)}${suffix}`)
}

export function verifyLedger(flowId) {
  return request(`/api/v1/ledger/${encodeURIComponent(flowId)}/verify`)
}

export function listLedgerAnchors(flowId) {
  return request(`/api/v1/ledger/${encodeURIComponent(flowId)}/anchors`)
}

export function getModelConfig() {
  return request('/api/v1/model-config')
}

export function updateModelConfig(payload) {
  return request('/api/v1/model-config', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function testModelConfig(payload) {
  return request('/api/v1/model-config/test', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getModelUsage(period = 'month') {
  return request(`/api/v1/model-usage?period=${encodeURIComponent(period)}`)
}
