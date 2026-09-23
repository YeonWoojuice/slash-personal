// slash-api 연동 규약(frontend-api-contract.md §5) 기준 설정.
//   - Authorization Code + PKCE만 쓴다 (Implicit 금지)
//   - scope에 email이 반드시 있어야 한다 — 없으면 서버가 최초 로그인 때 사용자 레코드를
//     못 만들어서 실패한다
import { UserManager, WebStorageStateStore } from 'oidc-client-ts'
import { legacyOidcUserStorageKey } from './authSession'

const region = import.meta.env.VITE_COGNITO_REGION
const userPoolId = import.meta.env.VITE_COGNITO_USER_POOL_ID
const authority = `https://cognito-idp.${region}.amazonaws.com/${userPoolId}`
const clientId = import.meta.env.VITE_COGNITO_CLIENT_ID
const sessionStore = new WebStorageStateStore({ store: window.sessionStorage })

// 예전 배포본이 localStorage에 남긴 access/id/refresh token을 새 저장소로 복사하지 않는다.
// 정확한 이 앱의 OIDC User 키만 지우고 한 번 다시 로그인하게 한다.
window.localStorage.removeItem(legacyOidcUserStorageKey(authority, clientId))

export const userManager = new UserManager({
  authority,
  client_id: clientId,
  redirect_uri: `${window.location.origin}/callback`,
  post_logout_redirect_uri: window.location.origin,
  response_type: 'code',
  scope: 'openid email profile',
  userStore: sessionStore,
  stateStore: sessionStore,
  // Cognito revoke endpoint는 refresh token 폐기를 지원한다. 수동 logout에서 이 값만 요청한다.
  revokeTokenTypes: ['refresh_token'],
  // revoke/metadata/token endpoint가 응답하지 않아도 로그아웃을 무기한 막지 않는다.
  requestTimeoutInSeconds: 10,
  // 만료 5분 전 선제 갱신(계약서 §5). 리프레시 토큰이 있으면 iframe 없이 그 토큰으로
  // 조용히 갱신한다.
  automaticSilentRenew: true,
  accessTokenExpiringNotificationTimeInSeconds: 5 * 60,
  // 이메일은 서버가 Cognito userInfo로 직접 조회하는 게 계약(§5) — 프론트가 중복으로
  // userinfo 엔드포인트를 호출할 필요가 없다.
  loadUserInfo: false,
})

/**
 * Cognito는 표준 OIDC 로그아웃(`end_session_endpoint`에 `id_token_hint`)을 지원하지 않는다 —
 * 실제로 붙여보면 `/login` 페이지로 잘못 튕겨서 멈춘다(2026-08-05 확인). `userManager.signoutRedirect()`
 * 대신 Cognito 고유 방식(`client_id`+`logout_uri`)으로 직접 URL을 만들어야 한다.
 */
export function cognitoSignOutUrl(): string {
  const domain = import.meta.env.VITE_COGNITO_DOMAIN
  const clientId = import.meta.env.VITE_COGNITO_CLIENT_ID
  const logoutUri = encodeURIComponent(window.location.origin)
  return `${domain}/logout?client_id=${clientId}&logout_uri=${logoutUri}`
}
