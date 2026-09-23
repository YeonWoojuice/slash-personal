import { useEffect, useState } from 'react'
import { Search, ChevronDown, Check } from 'lucide-react'
import { useNavigate } from 'react-router'
import { ApiError } from '../../lib/apiClient'
import { getTaskHistory, toHistoryEntry, TASK_TYPE_COMMAND_LABELS, type HistoryEntry } from '../../lib/tasks'
import { CommandBadge } from '../../components/CommandBadge'

const PAGE_SIZE = 20

// "전체" + TASK_TYPE_COMMAND_LABELS의 각 taskType — 배지에 쓰는 것과 같은 목록이라, 필터로
// 고를 수 있는 값과 목록에 실제로 붙는 배지가 항상 일치한다.
const FILTER_OPTIONS: { taskType?: string; label: string }[] = [
  { label: '전체' },
  ...Object.entries(TASK_TYPE_COMMAND_LABELS).map(([taskType, label]) => ({ taskType, label: `/${label}` })),
]

export function HistoryPage() {
  const navigate = useNavigate()
  const [entries, setEntries] = useState<HistoryEntry[]>([])
  const [nextCursor, setNextCursor] = useState<string | undefined>(undefined)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [filterTaskType, setFilterTaskType] = useState<string | undefined>(undefined)
  const [filterOpen, setFilterOpen] = useState(false)

  useEffect(() => {
    setLoading(true)
    getTaskHistory({ limit: PAGE_SIZE, taskType: filterTaskType })
      .then((page) => {
        setEntries(page.items.map(toHistoryEntry))
        setNextCursor(page.nextCursor)
      })
      .catch((err) => setLoadError(err instanceof ApiError ? err.message : '이력을 불러오지 못했어요.'))
      .finally(() => setLoading(false))
  }, [filterTaskType])

  const loadMore = () => {
    if (!nextCursor) return
    setLoadingMore(true)
    getTaskHistory({ limit: PAGE_SIZE, cursor: nextCursor, taskType: filterTaskType })
      .then((page) => {
        setEntries((prev) => [...prev, ...page.items.map(toHistoryEntry)])
        setNextCursor(page.nextCursor)
      })
      .catch((err) => setLoadError(err instanceof ApiError ? err.message : '이력을 불러오지 못했어요.'))
      .finally(() => setLoadingMore(false))
  }

  const currentFilterLabel = FILTER_OPTIONS.find((o) => o.taskType === filterTaskType)?.label ?? '전체'

  return (
    <div className="w-full max-w-4xl">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">히스토리</h1>
        <div className="flex items-center gap-2">
          <button
            type="button"
            aria-label="검색"
            className="flex h-9 w-9 items-center justify-center rounded-full border border-hairline text-muted transition-colors hover:bg-surface-raised hover:text-foreground"
          >
            <Search size={16} />
          </button>
          <div className="relative">
            <button
              type="button"
              onClick={() => setFilterOpen((prev) => !prev)}
              className="flex items-center gap-1.5 rounded-full border border-hairline px-3 py-2 text-sm text-foreground transition-colors hover:bg-surface-raised"
            >
              필터 기준 {currentFilterLabel}
              <ChevronDown size={14} />
            </button>
            {filterOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setFilterOpen(false)} />
                <div className="absolute right-0 top-full z-50 mt-2 w-40 overflow-hidden rounded-xl border border-hairline bg-surface-raised py-1 text-left">
                  {FILTER_OPTIONS.map((option) => (
                    <button
                      key={option.label}
                      type="button"
                      onClick={() => {
                        setFilterTaskType(option.taskType)
                        setFilterOpen(false)
                      }}
                      className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-foreground/8"
                    >
                      <span className="flex-1">{option.label}</span>
                      {option.taskType === filterTaskType && <Check size={14} className="shrink-0 text-accent-blue" />}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
          <button
            type="button"
            onClick={() => navigate('/new')}
            className="rounded-full bg-foreground px-4 py-2 text-sm font-medium text-canvas transition-opacity hover:opacity-90"
          >
            새 검색
          </button>
        </div>
      </div>

      {loading ? (
        <p className="mt-6 px-2 text-sm text-muted">불러오는 중...</p>
      ) : loadError ? (
        <p className="mt-6 px-2 text-sm text-muted">{loadError}</p>
      ) : entries.length === 0 ? (
        <p className="mt-6 px-2 text-sm text-muted">
          {filterTaskType ? `${currentFilterLabel} 이력이 없어요.` : '아직 이력이 없어요.'}
        </p>
      ) : (
        <>
          <div className="mt-6 flex flex-col">
            {entries.map((entry) => (
              <button
                key={entry.id}
                type="button"
                onClick={() => navigate(`/chat/${entry.id}`)}
                className="flex items-center justify-between gap-4 border-b border-hairline px-2 py-3.5 text-left transition-colors hover:bg-surface-raised"
              >
                <span className="flex min-w-0 items-center gap-2 text-sm text-foreground">
                  <CommandBadge label={entry.commandLabel} />
                  <span data-clarity-mask="true" className="truncate">
                    {entry.text}
                  </span>
                </span>
                <span className="shrink-0 text-xs text-muted">{entry.timeLabel}</span>
              </button>
            ))}
          </div>

          {nextCursor && (
            <div className="mt-4 flex justify-center">
              <button
                type="button"
                onClick={loadMore}
                disabled={loadingMore}
                className="rounded-full border border-hairline px-4 py-2 text-sm text-foreground transition-colors hover:bg-surface-raised disabled:opacity-50"
              >
                {loadingMore ? '불러오는 중...' : '더 보기'}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
