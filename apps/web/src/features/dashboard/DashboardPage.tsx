import { useEffect, useState } from 'react'
import { ArrowRight } from 'lucide-react'
import { useNavigate } from 'react-router'
import { ApiError } from '../../lib/apiClient'
import { getTaskHistory, toHistoryEntry, type HistoryEntry } from '../../lib/tasks'
import { CommandBadge } from '../../components/CommandBadge'

const RECENT_COUNT = 5

export function DashboardPage() {
  const navigate = useNavigate()
  const [recent, setRecent] = useState<HistoryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    getTaskHistory({ limit: RECENT_COUNT })
      .then((page) => setRecent(page.items.map(toHistoryEntry)))
      .catch((err) => setLoadError(err instanceof ApiError ? err.message : '최근 활동을 불러오지 못했어요.'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="w-full max-w-4xl">
      <h1 className="text-2xl font-bold tracking-tight">대시보드</h1>

      <div className="mt-6">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">최근 활동</h2>
          <button
            type="button"
            onClick={() => navigate('/history')}
            className="flex items-center gap-1 text-sm text-muted transition-colors hover:text-foreground"
          >
            전체 보기
            <ArrowRight size={14} />
          </button>
        </div>

        {loading ? (
          <p className="mt-3 px-2 text-sm text-muted">불러오는 중...</p>
        ) : loadError ? (
          <p className="mt-3 px-2 text-sm text-muted">{loadError}</p>
        ) : recent.length === 0 ? (
          <p className="mt-3 px-2 text-sm text-muted">아직 활동이 없어요.</p>
        ) : (
          <div className="mt-3 flex flex-col">
            {recent.map((entry) => (
              <button
                key={entry.id}
                type="button"
                onClick={() => navigate(`/chat/${entry.id}`)}
                className="flex items-center justify-between gap-4 border-b border-hairline px-2 py-3 text-left text-sm transition-colors hover:bg-surface-raised"
              >
                <span className="flex min-w-0 items-center gap-2 text-foreground">
                  <CommandBadge label={entry.commandLabel} />
                  <span data-clarity-mask="true" className="truncate">
                    {entry.text}
                  </span>
                </span>
                <span className="shrink-0 text-xs text-muted">{entry.timeLabel}</span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
