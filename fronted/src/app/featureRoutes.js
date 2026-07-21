export const FEATURE_ROUTE_PATTERN = /^\/(workbench|audit|prompts|mcp|models|state)(?:\/|$)/

export function isFeatureRoute(pathname) {
  return FEATURE_ROUTE_PATTERN.test(pathname)
}
