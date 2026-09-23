// 최초 방문 1회만 뜨는 가벼운 온보딩 — 백엔드에 "본 적 있음" 상태를 둘 이유가 없어서
// localStorage로만 판단한다(AppShell.tsx). 계정이 아니라 브라우저 기준이라 다른 기기·브라우저·
// 시크릿창에서는 다시 뜬다 — 정확한 "계정당 1회"가 필요해지면 그때 백엔드 필드로 옮긴다.
export function OnboardingDialog({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4" onClick={onClose}>
      <div
        className="w-full max-w-sm rounded-2xl border border-hairline bg-surface p-6 text-left shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold">Slash 사용법</h2>
        <p className="mt-3 text-sm leading-6 text-muted">
          그냥 질문을 입력하면 AI가 답해요. 맨 앞에 <span className="text-foreground">/</span>를 붙이면
          파일 검색·웹 검색 같은 명령을 직접 실행할 수 있어요.
        </p>
        <button
          type="button"
          onClick={onClose}
          className="mt-5 w-full rounded-full bg-foreground px-4 py-2.5 text-sm font-medium text-canvas transition-opacity hover:opacity-90"
        >
          시작하기
        </button>
      </div>
    </div>
  )
}
