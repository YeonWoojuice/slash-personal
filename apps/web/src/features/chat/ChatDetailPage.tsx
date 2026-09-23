import { useEffect, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router'
import { ChevronDown, Share2, Copy, Check, Volume2, Square, ThumbsUp, ThumbsDown, RotateCcw } from 'lucide-react'
import { Tooltip } from '../../components/Tooltip'
import { CommandBadge } from '../../components/CommandBadge'
import { ShareDialog } from '../../components/ShareDialog'
import { ChatTitleMenu } from '../../components/ChatTitleMenu'
import { ApiError } from '../../lib/apiClient'
import {
  getTask,
  createTaskRequest,
  isTerminalTaskStatus,
  formatRelativeTime,
  TASK_TYPE_COMMAND_LABELS,
  type TaskDetail,
} from '../../lib/tasks'
import { ResultCard, summarizeResult, taskErrorMessage, LoadingIndicator, TASK_STATUS_LABELS } from '../../lib/taskResultRenderers'

const ACTION_BUTTON_CLASS =
  'flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-raised hover:text-foreground'

const POLL_INTERVAL_MS = 2000

// 백엔드엔 "대화(멀티턴)" 개념이 없다 — 요청 1개 = task 1개 = 답변 1개다. 그래서 이 화면은 한 번의
// 질문-답변만 보여주고, 이어서 더 묻는 입력창은 두지 않는다(§ dev 코멘트). 이어 묻고 싶으면
// "다시 생성"으로 새 task를 만들거나 /new로 돌아가 새로 시작한다.
export function ChatDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [task, setTask] = useState<TaskDetail | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  const [regenerating, setRegenerating] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)
  const [titleMenuOpen, setTitleMenuOpen] = useState(false)

  useEffect(() => {
    if (!id) {
      setLoadError('이 대화를 찾을 수 없어요. 지워졌거나 주소가 잘못된 것 같아요.')
      return
    }
    let cancelled = false
    let timeoutId: number | undefined

    const poll = () => {
      getTask(id)
        .then((detail) => {
          if (cancelled) return
          setTask(detail)
          setLoadError(null)
          // NEEDS_CLARIFICATION은 종결 상태가 아니지만 이 task 자체는 더 안 바뀐다 — 백엔드가
          // correlationId로 같은 태스크를 이어가지 않고, 답변도 새 text로 새 요청을 받는 구조라서다.
          if (!isTerminalTaskStatus(detail.status) && detail.status !== 'NEEDS_CLARIFICATION') {
            timeoutId = window.setTimeout(poll, POLL_INTERVAL_MS)
          }
        })
        .catch((err) => {
          if (cancelled) return
          setLoadError(err instanceof ApiError ? err.message : '이 대화를 불러오지 못했어요.')
        })
    }
    poll()

    return () => {
      cancelled = true
      window.clearTimeout(timeoutId)
    }
  }, [id])

  // 라우트를 벗어나면(다른 대화로 이동 등) 읽던 것도 멈춘다 — 안 그러면 화면엔 안 보이는데
  // 목소리만 계속 나온다.
  useEffect(() => () => window.speechSynthesis?.cancel(), [])

  const answerText = task ? summarizeResult(task.taskType, task.result) : null

  const copyText = () => {
    if (!answerText) return
    navigator.clipboard.writeText(answerText).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  const toggleSpeak = () => {
    if (!window.speechSynthesis || !answerText) return
    if (speaking) {
      window.speechSynthesis.cancel()
      setSpeaking(false)
      return
    }
    window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(answerText)
    utterance.lang = 'ko-KR'
    utterance.onend = () => setSpeaking(false)
    utterance.onerror = () => setSpeaking(false)
    window.speechSynthesis.speak(utterance)
    setSpeaking(true)
  }

  const regenerate = async () => {
    if (!task || regenerating) return
    setRegenerating(true)
    try {
      const created = await createTaskRequest(task.inputText)
      navigate(`/chat/${created.taskId}`, { replace: true })
    } catch {
      setRegenerating(false)
    }
  }

  if (loadError) {
    return (
      <div className="flex w-full max-w-3xl flex-1 flex-col items-center justify-center gap-3 text-center">
        <p className="text-sm text-muted">{loadError}</p>
        <Link
          to="/new"
          className="rounded-lg bg-foreground/10 px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-foreground/15"
        >
          새로 검색하기
        </Link>
      </div>
    )
  }

  if (!task) {
    return (
      <div className="flex w-full max-w-3xl flex-1 items-center justify-center">
        <LoadingIndicator label="불러오는 중이에요" />
      </div>
    )
  }

  const isCommand = task.inputText.startsWith('/')
  // 실제 원문은 "/명령 값"이 한 문자열이라(NLU가 갈라서 백엔드로 보낼 뿐 프론트는 다시 안 나눔),
  // 첫 토큰만 칩으로 떼어내고 나머지를 본문으로 보여준다 — command 필드가 따로 있던 mock과 달리
  // 정확한 명령 경로 파싱은 아니지만 화면 모양은 그대로 유지한다.
  const [commandToken, ...rest] = task.inputText.split(' ')
  const bodyText = isCommand ? rest.join(' ') : task.inputText
  // 브라우저 요약(WebLLM)처럼 원문을 서버에 보내지 않는 경로는 inputText가 `/`로 시작하지 않는다
  // (백엔드가 대신 보여줄 문구를 만들어 준다) — 그래도 taskType은 실제로 어떤 명령이었는지 알고
  // 있으므로, 리터럴 `/` 파싱이 실패하면 taskType으로 배지만 보충한다(본문은 원문 그대로 둔다).
  // CommandBadge는 슬래시 아이콘을 자체적으로 그리므로 라벨에선 슬래시를 뗀다.
  const badgeLabel = isCommand ? commandToken.slice(1) : task.taskType && TASK_TYPE_COMMAND_LABELS[task.taskType]
  const timeLabel = formatRelativeTime(task.completedAt ?? task.createdAt)

  return (
    <div className="flex w-full max-w-3xl flex-1 flex-col">
      <div className="flex items-center justify-between border-b border-hairline pb-4">
        <div className="relative min-w-0">
          <button
            type="button"
            onClick={() => setTitleMenuOpen((v) => !v)}
            className="flex min-w-0 items-center gap-1.5 text-sm font-semibold text-foreground"
          >
            {badgeLabel && <CommandBadge label={badgeLabel} />}
            <span data-clarity-mask="true" className="truncate">
              {bodyText || task.inputText}
            </span>
            <ChevronDown size={16} className="shrink-0 text-muted" />
          </button>
          {titleMenuOpen && <ChatTitleMenu onClose={() => setTitleMenuOpen(false)} />}
        </div>
        <button
          type="button"
          onClick={() => setShareOpen(true)}
          className="flex shrink-0 items-center gap-1.5 rounded-full border border-hairline px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-surface-raised"
        >
          <Share2 size={14} />
          공유
        </button>
      </div>

      {shareOpen && <ShareDialog onClose={() => setShareOpen(false)} />}

      <div className="flex flex-1 flex-col gap-6 py-6">
        <div className="ml-auto max-w-lg rounded-2xl border border-hairline bg-surface p-4">
          <p data-clarity-mask="true" className="text-sm text-foreground">
            {badgeLabel && (
              <span className="mr-2">
                <CommandBadge label={badgeLabel} />
              </span>
            )}
            {bodyText || task.inputText}
          </p>
        </div>

        <div className="max-w-2xl">
          {task.status === 'NEEDS_CLARIFICATION' ? (
            <div className="flex flex-col gap-1">
              <p className="text-control leading-relaxed text-foreground">
                {task.question ?? '추가 정보가 필요해요.'}
              </p>
              <p className="text-xs text-muted">
                이 요청은 더 진행되지 않아요 — 위 질문에 맞게 새로 검색해주세요.
              </p>
            </div>
          ) : !isTerminalTaskStatus(task.status) ? (
            <LoadingIndicator label={TASK_STATUS_LABELS[task.status] ?? '처리하는 중이에요'} />
          ) : task.status !== 'SUCCEEDED' ? (
            <div className="flex flex-col gap-2">
              <p className="text-control leading-relaxed text-accent-blue">{taskErrorMessage(task.errorCode)}</p>
              {task.errorCode === 'LOCATION_NOT_FOUND' && (
                <Link
                  to="/new"
                  className="inline-flex w-fit items-center rounded-lg bg-accent-blue px-3 py-1.5 text-control font-medium text-white transition-colors hover:bg-accent-blue/90"
                >
                  다시 검색하기
                </Link>
              )}
            </div>
          ) : task.result && answerText ? (
            <>
              {/* WEATHER_LOOKUP·TEXT_SUMMARY·CODE_ANALYSIS는 ResultCard 안에 이미 문장이
                  있다(DESIGN.md §10) — 그 외 타입만 여기서 한 줄 요약을 먼저 보여준다. */}
              {task.taskType !== 'WEATHER_LOOKUP' &&
                task.taskType !== 'TEXT_SUMMARY' &&
                task.taskType !== 'CODE_ANALYSIS' && (
                <p className="text-control leading-relaxed text-foreground">{answerText}</p>
              )}
              <div
                data-clarity-mask="true"
                className="mt-3 rounded-xl border border-hairline bg-surface p-3.5"
              >
                <ResultCard taskType={task.taskType} result={task.result} />
              </div>
            </>
          ) : (
            <p className="text-control leading-relaxed text-muted">이 결과는 아직 화면에서 지원하지 않아요.</p>
          )}

          {task.status === 'SUCCEEDED' && answerText && (
            <div className="mt-3 flex items-center gap-1">
              <Tooltip label={copied ? '복사됨' : '복사'}>
                <button type="button" onClick={copyText} className={ACTION_BUTTON_CLASS}>
                  {copied ? <Check size={15} /> : <Copy size={15} />}
                </button>
              </Tooltip>
              <Tooltip label={speaking ? '정지' : '읽어주기'}>
                <button type="button" onClick={toggleSpeak} className={ACTION_BUTTON_CLASS}>
                  {speaking ? <Square size={15} /> : <Volume2 size={15} />}
                </button>
              </Tooltip>
              <Tooltip label="좋아요">
                <button type="button" className={ACTION_BUTTON_CLASS}>
                  <ThumbsUp size={15} />
                </button>
              </Tooltip>
              <Tooltip label="별로예요">
                <button type="button" className={ACTION_BUTTON_CLASS}>
                  <ThumbsDown size={15} />
                </button>
              </Tooltip>
              <Tooltip label="다시 생성">
                <button
                  type="button"
                  onClick={regenerate}
                  disabled={regenerating}
                  className={`${ACTION_BUTTON_CLASS} disabled:opacity-40`}
                >
                  <RotateCcw size={15} />
                </button>
              </Tooltip>
              <span className="ml-1 text-xs text-muted">{timeLabel}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
