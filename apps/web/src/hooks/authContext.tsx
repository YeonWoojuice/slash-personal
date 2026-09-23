import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import type { User } from 'oidc-client-ts'
import {
  endClientSession,
  isClientLogoutStorageEvent,
  signalClientLogout,
} from '../lib/authSession'
import { cognitoSignOutUrl, userManager } from '../lib/oidc'

type AuthStatus = 'checking' | 'authenticated' | 'anonymous'

type Auth = {
  status: AuthStatus
  /** slash-api Authorization 헤더에 실을 값. ID Token 아님 — 계약서 §5, 서버가 token_use로 거부한다. */
  accessToken: string | null
  login: () => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<Auth | null>(null)

/**
 * oidc-client-ts의 UserManager를 앱 상태로 감싼다. **라우터 바깥에서 감싸야 한다** —
 * RequireAuth/RequireGuest가 라우팅 중에 이 값을 읽는다.
 *
 * 세션 확인이 oidc-client-ts에서는 비동기(sessionStorage를 스토리지 인터페이스 뒤에 감춰서)라
 * 'checking' 상태가 필요하다 — 예전 로컬 플래그 시절엔 동기라 필요 없었다(lib/auth.ts 참고).
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('checking')
  const [user, setUser] = useState<User | null>(null)

  useEffect(() => {
    let cancelled = false

    userManager.getUser().then((u) => {
      if (cancelled) return
      const valid = u && !u.expired ? u : null
      setUser(valid)
      setStatus(valid ? 'authenticated' : 'anonymous')
    })

    const onLoaded = (u: User) => {
      setUser(u)
      setStatus('authenticated')
    }
    const onUnloaded = () => {
      setUser(null)
      setStatus('anonymous')
    }
    // 자동 갱신(만료 5분 전) 실패 시 — 리프레시 토큰도 만료된 경우다. 로그인 화면으로 보낸다.
    const onSilentRenewError = () => {
      setUser(null)
      setStatus('anonymous')
    }
    const onLogoutStorage = (event: StorageEvent) => {
      if (!isClientLogoutStorageEvent(event)) return
      void userManager.removeUser().finally(() => {
        setUser(null)
        setStatus('anonymous')
      })
    }

    userManager.events.addUserLoaded(onLoaded)
    userManager.events.addUserUnloaded(onUnloaded)
    userManager.events.addSilentRenewError(onSilentRenewError)
    window.addEventListener('storage', onLogoutStorage)
    return () => {
      cancelled = true
      userManager.events.removeUserLoaded(onLoaded)
      userManager.events.removeUserUnloaded(onUnloaded)
      userManager.events.removeSilentRenewError(onSilentRenewError)
      window.removeEventListener('storage', onLogoutStorage)
    }
  }, [])

  const auth: Auth = {
    status,
    accessToken: user?.access_token ?? null,
    login: () => userManager.signinRedirect(),
    logout: () => {
      // signoutRedirect()는 표준 OIDC 로그아웃을 시도하는데 Cognito가 이걸 지원하지 않는다 —
      // refresh token을 먼저 폐기한 뒤 Cognito 고유 로그아웃 URL로 직접 이동한다.
      return endClientSession({
        revokeRefreshToken: () => userManager.revokeTokens(['refresh_token']),
        removeUser: () => userManager.removeUser(),
        redirectToLogout: () => {
          try {
            signalClientLogout(window.localStorage)
          } finally {
            window.location.href = cognitoSignOutUrl()
          }
        },
      })
    },
  }

  return <AuthContext.Provider value={auth}>{children}</AuthContext.Provider>
}

export function useAuth(): Auth {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth는 AuthProvider 안에서만 쓸 수 있어요.')
  return value
}

/** 워드마크(로고+Slash)를 눌렀을 때 갈 곳. 로그인했으면 앱으로, 아니면 로그인 화면으로. */
export function useHomePath(): string {
  const { status } = useAuth()
  return status === 'authenticated' ? '/new' : '/login'
}
