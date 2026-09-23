// 방식 1 (딥링크) — 이슈 #6. 결과를 앱 안에 렌더하지 않고 새 탭으로 넘기는 명령들.
//
// 앱 안(iframe)에 띄우는 건 검증해봤고 안 된다. 2026-07-30 실제 프레이밍 결과:
// - `search.naver.com`(통합검색, 데스크톱/모바일 모두) — `X-Frame-Options: DENY` +
//   `frame-ancestors 'none'`. 브라우저가 거부하고 빈 프레임만 남는다.
// - `map.naver.com` — `X-Frame-Options: DENY`.
// - `google.com/search` — `X-Frame-Options: SAMEORIGIN`. 문서화되지 않은 `igu=1`을 붙이면 헤더가
//   빠지긴 하지만, 구글이 "비정상적인 트래픽" reCAPTCHA 페이지를 내려준다. 쓰지 않는다.
// (네이버 사전/지식iN/블로그는 프레이밍 헤더가 없어 실제로 임베드되지만, 보장된 게 아니라 헤더가
//  없을 뿐이고 cross-origin이라 내용도 읽을 수 없다 — DESIGN.md §9 참고.)
//
// URL 스킴은 headless Chrome으로 렌더 결과를 확인한 것 (SPA라서 HTTP 상태 코드는 없는 경로에도
// 200이라 의미 없음):
// - `search.naver.com/search.naver?query={검색어}` — 통합검색. `where`/`sm`/`fbm`/`ie`/`ackey`는
//   유입 경로 추적용이라 빼도 결과가 같다.
// - `map.naver.com/p/search/{검색어}` — 통합 장소 검색. 구 경로 `/v5/search/…`는 여기로 302.
// - `google.com/search?q={검색어}` — 다른 파라미터 없이 이것만으로 충분하다.
//
// `/네이버` 통합검색은 원래 백엔드 경유(방식 2)로 정해뒀지만, 백엔드가 붙기 전까지는 `/구글`과
// 같은 딥링크로 동작한다 — 결과가 앱 밖으로 나가므로 스레드/히스토리에는 남지 않는다.
// `/네이버/길찾기`는 여전히 여기 없다: 이름만으로는 네이버가 경로를 계산해주지 않는다(§9).

import type { ChainedCommand } from './mockCommands'

/** 새 탭 딥링크로 처리하는 명령의 URL. 해당 없으면 null. */
export function buildDeepLink(chain: ChainedCommand): string | null {
  const query = chain.query.trim()
  if (!query) return null

  if (chain.namespace === '네이버' && !chain.action) {
    return `https://search.naver.com/search.naver?query=${encodeURIComponent(query)}`
  }
  if (chain.namespace === '네이버' && chain.action === '지도') {
    return `https://map.naver.com/p/search/${encodeURIComponent(query)}`
  }
  if (chain.namespace === '구글' && !chain.action) {
    return `https://www.google.com/search?q=${encodeURIComponent(query)}`
  }
  return null
}

/** 딥링크 명령의 안내 문구 — 결과가 앱 밖에서 열린다는 걸 미리 알려준다. */
export function deepLinkHint(chain: ChainedCommand): string | null {
  if (chain.namespace === '네이버' && !chain.action) {
    return '새 탭에서 네이버 검색으로 열려요.'
  }
  if (chain.namespace === '네이버' && chain.action === '지도') {
    return '새 탭에서 네이버 지도 검색으로 열려요.'
  }
  if (chain.namespace === '구글' && !chain.action) {
    return '새 탭에서 구글 검색으로 열려요.'
  }
  return null
}
