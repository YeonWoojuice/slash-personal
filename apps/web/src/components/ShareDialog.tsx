import { useState } from 'react'
import { X, Lock, Globe, Check } from 'lucide-react'
import { Tooltip } from './Tooltip'

type Visibility = 'private' | 'public'

const OPTIONS: { id: Visibility; icon: typeof Lock; label: string; description: string }[] = [
  { id: 'private', icon: Lock, label: '비공개 유지', description: '본인만 접근 가능' },
  { id: 'public', icon: Globe, label: '공개 링크 생성', description: '링크가 있는 모든 사람이 볼 수 있음' },
]

/** 대화 공유 다이얼로그 — Claude의 "비공개/공개 링크" 방식을 구조만 따른다(§ 2026-08-26 결정,
 *  ChatGPT의 SNS 아이콘 방식 대신). Slash 대화는 /코드·/사용량·/파일처럼 로컬 PC 정보를 담을 수
 *  있어 "공유가 이미 전제된" UI보다 공개를 명시적으로 선택해야 하는 쪽이 더 안전한 기본값이다.
 *  slash-api에 공유 링크 발급 API가 아직 없어(frontend-api-contract.md에 없음), 생성 버튼은
 *  LoginPage의 Google 로그인 버튼과 같은 선례로 disabled + 안내 툴팁만 둔다 — 동작하는 척하지 않는다. */
export function ShareDialog({ onClose }: { onClose: () => void }) {
  const [visibility, setVisibility] = useState<Visibility>('private')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4" onClick={onClose}>
      <div
        className="w-full max-w-sm rounded-2xl border border-hairline bg-surface p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-foreground">대화 공유</h2>
            <p className="mt-1 text-sm text-muted">이 지점까지의 메시지만 공유됩니다.</p>
          </div>
          <button
            type="button"
            aria-label="닫기"
            onClick={onClose}
            className="shrink-0 text-muted transition-colors hover:text-foreground"
          >
            <X size={18} />
          </button>
        </div>

        <div className="mt-4 overflow-hidden rounded-xl border border-hairline">
          {OPTIONS.map((option, i) => (
            <button
              key={option.id}
              type="button"
              onClick={() => setVisibility(option.id)}
              className={`flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-raised ${
                i > 0 ? 'border-t border-hairline' : ''
              }`}
            >
              <option.icon size={18} className="shrink-0 text-muted" />
              <span className="min-w-0 flex-1">
                <span className="block text-sm text-foreground">{option.label}</span>
                <span className="block text-xs text-muted">{option.description}</span>
              </span>
              {visibility === option.id && <Check size={16} className="shrink-0 text-accent-blue" />}
            </button>
          ))}
        </div>

        <p className="mt-3 text-xs text-muted">허가 없이 개인정보나 제3자 콘텐츠를 공유하지 마세요.</p>

        <div className="mt-4 flex justify-end">
          <Tooltip label="공유 링크 발급은 아직 준비 중이에요">
            <button
              type="button"
              disabled
              className="cursor-not-allowed rounded-full bg-foreground px-4 py-2 text-sm font-medium text-canvas opacity-50"
            >
              공유 링크 생성
            </button>
          </Tooltip>
        </div>
      </div>
    </div>
  )
}
