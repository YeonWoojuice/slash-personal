import { Pencil, Star, Trash2 } from 'lucide-react'

function MenuItem({ icon: Icon, label }: { icon: typeof Pencil; label: string }) {
  return (
    <button
      type="button"
      disabled
      title="아직 준비 중이에요"
      className="flex w-full cursor-not-allowed items-center gap-2.5 px-3 py-2 text-left text-sm text-foreground opacity-50"
    >
      <Icon size={16} className="shrink-0 text-muted" />
      <span className="flex-1">{label}</span>
    </button>
  )
}

/** 대화 제목 옆 ChevronDown이 여는 메뉴 — ProfileMenu.tsx와 같은 셸(백드롭+absolute 패널)을
 *  재사용한다. 세 항목 다 백엔드에 대화(스레드) 이름 변경·즐겨찾기·삭제 API가 아직 없어서
 *  (frontend-api-contract.md에 없음) ShareDialog의 "공유 링크 생성"과 같은 선례로 disabled +
 *  안내 툴팁만 둔다 — 로컬 state로 반짝였다가 새로고침하면 원상복구되는 반쪽짜리를 만들지 않는다. */
export function ChatTitleMenu({ onClose }: { onClose: () => void }) {
  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div className="absolute left-0 top-full z-50 mt-2 w-56 overflow-hidden rounded-xl border border-hairline bg-surface-raised py-1 text-left shadow-2xl">
        <MenuItem icon={Pencil} label="이름 변경" />
        <MenuItem icon={Star} label="즐겨찾기 추가" />
        <div className="border-t border-hairline pt-1">
          <MenuItem icon={Trash2} label="삭제" />
        </div>
      </div>
    </>
  )
}
