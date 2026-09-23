// 브라우저 JS API로만 얻을 수 있는 클라이언트 정보. 표시 전용이다 — 백엔드가 이 값에 따라 실제
// 동작(로케일 콘텐츠, 지역 제한 등)을 바꿔야 한다면, 조작 가능한 이 값을 신뢰하지 말고 요청 헤더
// (Accept-Language, User-Agent)나 서버 계산으로 별도로 얻어야 한다.

interface UserAgentData {
  platform?: string
  brands?: { brand: string; version: string }[]
}

function detectOS(): string {
  const uaData = (navigator as Navigator & { userAgentData?: UserAgentData }).userAgentData
  if (uaData?.platform) return uaData.platform

  const ua = navigator.userAgent
  if (/Mac OS X/.test(ua)) return 'macOS'
  if (/Windows/.test(ua)) return 'Windows'
  if (/Android/.test(ua)) return 'Android'
  if (/iPhone|iPad|iPod/.test(ua)) return 'iOS'
  if (/Linux/.test(ua)) return 'Linux'
  return '알 수 없음'
}

// userAgentData.brands는 Chromium 계열 한정이라, 그 외 브라우저는 userAgent 문자열을 파싱한다.
function detectBrowser(): string {
  const uaData = (navigator as Navigator & { userAgentData?: UserAgentData }).userAgentData
  const brand = uaData?.brands?.find((b) => !/Not.*A.*Brand/i.test(b.brand))
  if (brand) return `${brand.brand} ${brand.version}`

  const ua = navigator.userAgent
  const patterns: [RegExp, string][] = [
    [/Edg\/([\d.]+)/, 'Edge'],
    [/Chrome\/([\d.]+)/, 'Chrome'],
    [/Firefox\/([\d.]+)/, 'Firefox'],
    [/Version\/([\d.]+).*Safari/, 'Safari'],
  ]
  for (const [pattern, name] of patterns) {
    const match = ua.match(pattern)
    if (match) return `${name} ${match[1]}`
  }
  return '알 수 없음'
}

export interface ClientInfo {
  timeZone: string
  os: string
  browser: string
  language: string
  resolution: string
}

export function getClientInfo(): ClientInfo {
  return {
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    os: detectOS(),
    browser: detectBrowser(),
    language: navigator.language,
    resolution: `${screen.width}×${screen.height}`,
  }
}
