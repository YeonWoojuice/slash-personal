import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { getMe, type MeResponse } from '../lib/me'
import { useAuth } from './authContext'

type CurrentUser = {
  loading: boolean
  /** displayName이 없으면(계약서 §2: Cognito 토큰에 name/given_name 클레임이 없으면 응답에서
   *  아예 빠진다) 이메일 앞부분으로 대신한다. 그마저 없으면 null — 아직 못 가져왔거나 로그인 전. */
  displayName: string | null
  email: string | null
}

const CurrentUserContext = createContext<CurrentUser | null>(null)

/** 로그인한 사용자 정보(GET /api/v1/me)를 앱 전체가 하나의 값으로 공유한다 — 홈 화면 인사말과
 *  사이드바 프로필 행이 같은 이름을 보여줘야 하므로 각자 따로 부르지 않는다. */
export function CurrentUserProvider({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  const [me, setMe] = useState<MeResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (status !== 'authenticated') {
      setMe(null)
      setLoading(status === 'checking')
      return
    }

    let cancelled = false
    setLoading(true)
    getMe()
      .then((res) => {
        if (!cancelled) setMe(res)
      })
      .catch(() => {
        if (!cancelled) setMe(null)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [status])

  const value: CurrentUser = {
    loading,
    displayName: me?.displayName ?? (me?.email ? me.email.split('@')[0] : null),
    email: me?.email ?? null,
  }

  return <CurrentUserContext.Provider value={value}>{children}</CurrentUserContext.Provider>
}

export function useCurrentUser(): CurrentUser {
  const value = useContext(CurrentUserContext)
  if (!value) throw new Error('useCurrentUser는 CurrentUserProvider 안에서만 쓸 수 있어요.')
  return value
}
