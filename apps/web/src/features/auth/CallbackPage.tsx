import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { userManager } from '../../lib/oidc'

/**
 * Cognito Managed Login이 Authorization Code를 들고 돌아오는 곳(계약서 §5).
 * signinRedirectCallback()이 code를 토큰으로 교환한 뒤 /new로 보낸다.
 *
 * ranRef로 한 번만 실행되게 막는다 — StrictMode(main.tsx)가 개발 모드에서 effect를 두 번
 * 실행하는데, code는 1회용이라 두 번째 호출은 항상 실패한다.
 */
export function CallbackPage() {
  const navigate = useNavigate()
  const ranRef = useRef(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (ranRef.current) return
    ranRef.current = true

    userManager
      .signinRedirectCallback()
      .then(() => navigate('/new', { replace: true }))
      .catch((err) => {
        setError(err instanceof Error ? err.message : '로그인 처리 중 오류가 발생했습니다.')
      })
  }, [navigate])

  if (error) {
    return (
      <div className="flex h-screen w-full flex-col items-center justify-center gap-3 bg-canvas px-6 text-center font-sans text-foreground">
        <p className="text-sm text-red-500">{error}</p>
        <button
          type="button"
          onClick={() => navigate('/login', { replace: true })}
          className="text-sm text-muted underline-offset-2 hover:text-foreground hover:underline"
        >
          로그인 화면으로 돌아가기
        </button>
      </div>
    )
  }

  return (
    <div className="flex h-screen w-full items-center justify-center bg-canvas font-sans text-sm text-muted">
      로그인 처리 중...
    </div>
  )
}
