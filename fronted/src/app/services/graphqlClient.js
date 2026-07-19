import { API_BASE_URL } from '../api.js'

export async function graphqlRequest(query, variables = {}) {
  const response = await fetch(`${API_BASE_URL}/graphql`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, variables }),
  })
  const body = await response.json()
  if (!response.ok || body.errors?.length) {
    const error = new Error(body.errors?.[0]?.message || `GraphQL request failed (${response.status})`)
    error.code = body.errors?.[0]?.extensions?.code || 'GRAPHQL_REQUEST_FAILED'
    throw error
  }
  return body.data
}
