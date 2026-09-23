import { useState } from 'react'
import { useNavigate } from 'react-router'
import { useAuth, useHomePath } from '../../hooks/authContext'

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84c-.21 1.13-.84 2.09-1.8 2.73v2.27h2.91c1.7-1.57 2.69-3.87 2.69-6.64z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.91-2.27c-.81.54-1.85.86-3.05.86-2.34 0-4.32-1.58-5.03-3.71H.96v2.34C2.44 15.98 5.48 18 9 18z" />
      <path fill="#FBBC05" d="M3.97 10.7A5.4 5.4 0 0 1 3.68 9c0-.59.1-1.16.29-1.7V4.96H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.04l3.01-2.34z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.51.45 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0 5.48 0 2.44 2.02.96 4.96l3.01 2.34C4.68 5.16 6.66 3.58 9 3.58z" />
    </svg>
  )
}

// 이메일 입력·인증코드 단계는 이 화면이 직접 그리지 않는다 — Cognito Managed Login
// 페이지(리다이렉트 대상)가 그 UX 전체를 대신 맡는다(계약서 §5, Authorization Code+PKCE).
// 여기서는 그리로 보내는 버튼 두 개만 있으면 된다.
export function LoginPage() {
  const navigate = useNavigate()
  const homePath = useHomePath()
  const { login } = useAuth()
  const [redirecting, setRedirecting] = useState(false)

  const handleEmailContinue = async () => {
    setRedirecting(true)
    await login()
  }

  return (
    <div className="flex h-screen w-full bg-canvas font-sans text-foreground">
      <div className="flex w-full flex-col px-10 py-8">
        <button
          type="button"
          onClick={() => navigate(homePath)}
          className="-mx-2 flex w-fit items-center gap-2 rounded-[8px] px-2 py-1 text-control font-semibold transition-colors hover:bg-surface"
        >
          <img src="/logo.png" alt="" className="h-7 w-7 rounded-[7px]" />
          Slash
        </button>

        <div className="flex flex-1 flex-col items-center justify-center">
          <div className="w-full max-w-sm text-center">
            <h1 className="text-3xl font-bold tracking-tight">무엇이든 물어보세요</h1>
            <p className="mt-3 text-muted">파일·웹 검색, 생성형 AI, PC 제어까지 한 번에.</p>

            <div className="mt-8 rounded-2xl border border-hairline bg-surface p-6 text-left">
              <button
                type="button"
                disabled
                title="Google 로그인은 준비 중입니다"
                className="flex w-full cursor-not-allowed items-center justify-center gap-2 rounded-full border border-hairline bg-surface px-4 py-3 text-sm font-medium text-foreground opacity-50"
              >
                <GoogleIcon />
                Google로 계속하기
              </button>

              <div className="my-4 flex items-center gap-3 text-xs text-muted">
                <div className="h-px flex-1 bg-hairline" />
                또는
                <div className="h-px flex-1 bg-hairline" />
              </div>

              <button
                type="button"
                onClick={handleEmailContinue}
                disabled={redirecting}
                className="w-full rounded-full bg-foreground px-4 py-3 text-sm font-medium text-canvas transition-opacity hover:opacity-90 disabled:opacity-60"
              >
                {redirecting ? '이동 중...' : '이메일로 계속하기'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
