import { Navigate, Outlet } from 'react-router'
import { useAuth } from '../../hooks/authContext'

/**
 * 로그인해야 볼 수 있는 라우트를 감싸는 레이아웃 라우트.
 * 자식 라우트는 `<Outlet />` 자리에 그려지고, 로그인 상태가 아니면 대신 /login으로 보낸다.
 *
 * replace를 쓰는 이유 — 막힌 주소를 히스토리에 남기면 로그인 화면에서 뒤로 가기를 눌렀을 때
 * 다시 그 주소로 갔다가 또 튕겨나오는 왕복이 생긴다.
 *
 * 'checking' 동안은 아무것도 안 그린다 — oidc-client-ts가 sessionStorage에서 세션을 비동기로
 * 읽어오는 짧은 순간이라, 그 사이에 로그인 화면으로 잘못 튕기는 걸 막는다.
 */
export function RequireAuth() {
  const { status } = useAuth()
  if (status === 'checking') return null
  if (status === 'anonymous') return <Navigate to="/login" replace />
  return <Outlet />
}
