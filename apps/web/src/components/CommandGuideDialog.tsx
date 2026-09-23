import { X } from 'lucide-react'
import { COMMAND_TREE } from '../lib/commandTree'

const SHORTCUTS = [
  { keys: '/', desc: '명령어 모드 시작 — 하위 명령어 자동완성이 떠요' },
  { keys: '↑ / ↓', desc: '자동완성 · 모델 선택 목록에서 항목 이동' },
  { keys: 'Enter', desc: '선택한 항목 확정 (하위 항목이 있으면 그 안으로 들어가요)' },
  { keys: '→', desc: '/모델 같은 계층형 목록에서 선택 항목 안으로 들어가기 (Enter와 동일)' },
  { keys: '←', desc: '한 단계 위 목록으로 돌아가기 (Esc와 동일)' },
  { keys: 'Backspace', desc: '입력창이 비어 있을 때 한 단계 되돌리기 — 확정한 값 → 명령어 자체' },
  { keys: '⌥ Backspace', desc: '검색어를 단어 단위로 지우기' },
  { keys: 'Esc', desc: '한 단계 위로 돌아가기, 최상위에서는 입력창 비우기' },
  { keys: '마이크 길게 누르기', desc: '녹음 시작 · 손을 떼면 종료 (설정에서 클릭 방식으로 바꿀 수 있어요)' },
]

export function CommandGuideDialog({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4" onClick={onClose}>
      <div
        className="flex h-[min(560px,85vh)] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-hairline bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="relative border-b border-hairline px-6 py-4">
          <h2 className="text-lg font-semibold">명령어 가이드</h2>
          <button
            type="button"
            aria-label="닫기"
            onClick={onClose}
            className="absolute right-4 top-4 text-muted transition-colors hover:text-foreground"
          >
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          <h3 className="mb-2 text-sm font-semibold text-muted">슬래시 명령어</h3>
          <div className="mb-6 space-y-3">
            {COMMAND_TREE.map((node) => (
              <div key={node.id} className="overflow-hidden rounded-xl border border-hairline">
                <div className="flex items-start gap-3 bg-surface-raised px-4 py-2.5">
                  <code className="shrink-0 rounded-[8px] bg-foreground/8 px-2 py-0.5 font-mono text-xs font-semibold text-foreground">
                    /{node.id}
                  </code>
                  <span className="text-sm text-muted">{node.description}</span>
                </div>
                {node.children?.map((child) => (
                  <div key={child.id} className="flex items-start gap-3 border-t border-hairline px-4 py-2.5 pl-8">
                    <code className="shrink-0 rounded-[8px] bg-foreground/8 px-2 py-0.5 font-mono text-xs text-foreground">
                      /{node.id}/{child.id}
                    </code>
                    <span className="text-sm text-muted">{child.description}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>

          <h3 className="mb-2 text-sm font-semibold text-muted">단축키</h3>
          <div className="overflow-hidden rounded-xl border border-hairline">
            {SHORTCUTS.map((s, i) => (
              <div
                key={s.keys}
                className={`flex items-start gap-3 px-4 py-2.5 text-sm ${i > 0 ? 'border-t border-hairline' : ''}`}
              >
                <code className="shrink-0 whitespace-nowrap rounded-[8px] bg-foreground/8 px-2 py-0.5 font-mono text-xs text-foreground">
                  {s.keys}
                </code>
                <span className="text-muted">{s.desc}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
