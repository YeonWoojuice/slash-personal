import { X } from 'lucide-react'

type ShortcutGroup = {
  title: string
  items: { label: string; keys: string[] }[]
}

const GROUPS: ShortcutGroup[] = [
  {
    title: '일반',
    items: [
      { label: '빠른 검색', keys: ['⌘', 'K'] },
      { label: '사이드바 전환', keys: ['⌘', '.'] },
      { label: '단축키', keys: ['⌘', '/'] },
      { label: '설정', keys: ['⇧', '⌘', ','] },
    ],
  },
  {
    title: '검색창에서',
    items: [
      { label: '검색어 보내기', keys: ['↵'] },
      { label: '검색어에서 줄바꿈', keys: ['⇧', '↵'] },
      { label: '파일 또는 사진 업로드', keys: ['⌘', 'U'] },
      { label: '녹음 중지', keys: ['Esc'] },
    ],
  },
]

export function ShortcutsDialog({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4" onClick={onClose}>
      <div
        className="flex h-[min(560px,85vh)] w-full max-w-sm flex-col overflow-hidden rounded-2xl border border-hairline bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="relative border-b border-hairline px-6 py-4">
          <h2 className="text-lg font-semibold">단축키</h2>
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
          {GROUPS.map((group, gi) => (
            <div key={group.title} className={gi > 0 ? 'mt-6' : ''}>
              <h3 className="mb-2 text-sm font-semibold text-muted">{group.title}</h3>
              <div className="overflow-hidden rounded-xl border border-hairline">
                {group.items.map((item, i) => (
                  <div
                    key={item.label}
                    className={`flex items-center justify-between px-4 py-2.5 text-sm ${
                      i > 0 ? 'border-t border-hairline' : ''
                    }`}
                  >
                    <span className="text-foreground">{item.label}</span>
                    <span className="flex shrink-0 gap-1">
                      {item.keys.map((k) => (
                        <span
                          key={k}
                          className="flex h-6 min-w-[24px] items-center justify-center rounded-[8px] bg-foreground/8 px-1.5 font-mono text-xs text-foreground"
                        >
                          {k}
                        </span>
                      ))}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
