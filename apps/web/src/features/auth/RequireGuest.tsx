import { Navigate, Outlet } from 'react-router'
import { useAuth } from '../../hooks/authContext'

/**
 * `RequireAuth`의 반대편 — 로그인한 사용자에게는 의미가 없는 라우트(로그인 화면)를 감싼다.
 * 이미 로그인했으면 앱으로 돌려보내고, 아니면 자식 라우트를 그대로 그린다.
 *
 * replace를 쓰는 이유는 RequireAuth와 같다. 히스토리에 /login을 남기면 /new에서 뒤로 가기를
 * 눌렀을 때 다시 /login으로 갔다가 곧바로 튕겨나오는 왕복이 생긴다.
 */
export function RequireGuest() {
  const { status } = useAuth()
  if (status === 'checking') return null
  if (status === 'authenticated') return <Navigate to="/new" replace />
  return <Outlet />
}
