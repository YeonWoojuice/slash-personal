interface EndClientSessionActions {
  revokeRefreshToken: () => Promise<void>
  removeUser: () => Promise<void>
  redirectToLogout: () => void
}

export const AUTH_LOGOUT_EVENT_KEY = 'slash.auth.logout'

/** 이전 localStorage 기반 oidc-client-ts User 항목만 정확히 찾아 제거한다. */
export function legacyOidcUserStorageKey(authority: string, clientId: string): string {
  return `oidc.user:${authority}:${clientId}`
}

/** 토큰 없이 로그아웃 사실만 같은 출처의 다른 탭에 알린다. */
export function signalClientLogout(
  storage: Pick<Storage, 'setItem'>,
  eventId?: string,
): void {
  try {
    storage.setItem(AUTH_LOGOUT_EVENT_KEY, eventId ?? crypto.randomUUID())
  } catch {
    // 저장소가 차단돼도 현재 탭의 로그아웃은 계속한다.
  }
}

export function isClientLogoutStorageEvent(
  event: Pick<StorageEvent, 'key' | 'newValue'>,
): boolean {
  return event.key === AUTH_LOGOUT_EVENT_KEY && Boolean(event.newValue)
}

/**
 * 재발급 수단을 먼저 폐기하고 로컬 세션을 지운다.
 * Cognito 폐기 요청이 실패해도 사용자를 현재 브라우저에 로그인된 채로 남기지 않는다.
 */
export async function endClientSession(actions: EndClientSessionActions): Promise<void> {
  try {
    await actions.revokeRefreshToken()
  } catch {
    // 네트워크 장애여도 로컬 세션 삭제와 Cognito 로그아웃 이동은 계속한다.
  }

  try {
    await actions.removeUser()
  } finally {
    actions.redirectToLogout()
  }
}
