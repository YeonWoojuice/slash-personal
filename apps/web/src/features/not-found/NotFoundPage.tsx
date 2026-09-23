import { useNavigate } from 'react-router'
import { useHomePath } from '../../hooks/authContext'

export function NotFoundPage() {
  const navigate = useNavigate()
  const homePath = useHomePath()

  return (
    <div className="flex h-screen w-full flex-col items-center justify-center bg-canvas px-6 font-sans text-foreground">
      <button
        type="button"
        onClick={() => navigate(homePath)}
        className="-mx-2 mb-10 flex w-fit items-center gap-2 rounded-[8px] px-2 py-1 text-control font-semibold transition-colors hover:bg-surface"
      >
        <img src="/logo.png" alt="" className="h-7 w-7 rounded-[7px]" />
        Slash
      </button>

      <div className="w-full max-w-sm text-center">
        <p className="text-sm font-medium text-muted">404</p>
        <h1 className="mt-2 text-2xl font-bold tracking-tight">이 페이지는 없어요</h1>
        <p className="mt-3 text-sm text-muted">주소를 다시 확인해 주세요.</p>

        <button
          type="button"
          onClick={() => navigate(homePath)}
          className="mt-8 w-full rounded-full bg-foreground px-4 py-3 text-sm font-medium text-canvas transition-opacity hover:opacity-90"
        >
          홈으로 가기
        </button>
      </div>
    </div>
  )
}
