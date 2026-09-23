// Mock slash-command chaining (`/네임스페이스[/액션] 쿼리`) for frontend-only UX testing.
// `파일` (backend FILE_SEARCH task, SearchBar) and `모델/검색` (SearchBar's model chip/picker)
// are real — this file only covers commands with no backend/API yet. Don't ship this data as real.

export type ChainedCommand = { namespace: string; action: string; query: string }

/**
 * Parses `/네임스페이스 쿼리` or `/네임스페이스/액션 쿼리` — the middle action segment is optional
 * since bare namespaces (e.g. `/네이버`, `/파일`) are themselves valid "default action" commands now.
 * `action` is `''` for the bare form. Returns null if the input doesn't match either shape.
 */
export function parseCommandChain(input: string): ChainedCommand | null {
  const match = input.match(/^\/([^\s/]+)(?:\/([^\s/]+))?\s+(.+)/)
  if (!match) return null
  const [, namespace, action = '', query] = match
  return { namespace, action, query }
}

/** Chains with a real implementation elsewhere (SearchBar checks these before falling back to this file). */
const REAL_CHAINS = new Set(['파일', '모델/검색', '네이버', '네이버/지도', '구글', '날씨', '요약', '코드'])

/** Placeholder message for any registered chain that isn't in REAL_CHAINS yet. */
export function mockPlaceholderMessage(chain: ChainedCommand): string | null {
  const key = chain.action ? `${chain.namespace}/${chain.action}` : chain.namespace
  return REAL_CHAINS.has(key) ? null : '이 기능은 아직 준비 중이에요.'
}
