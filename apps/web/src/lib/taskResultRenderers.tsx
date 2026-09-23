// SearchBar의 결과 패널과 ChatDetailPage의 답변 카드가 같이 쓰는 taskType별 렌더링·문구.
// 한 곳에서만 고치면 두 화면이 항상 같은 모양을 보여준다.
import { useEffect, useRef, useState } from 'react'
import { FileText, FolderOpen, Check, Loader2, Droplets, Wind } from 'lucide-react'
import type {
  TaskStatus,
  SystemStatusResult,
  FileSearchResult,
  WeatherLookupResult,
  TextSummaryResult,
  BrowserTextSummaryResult,
  CodeAnalysisResult,
  AiAgentUsageResult,
} from './tasks'
import { formatRelativeTime, createTaskRequest, getTask, isTerminalTaskStatus } from './tasks'
import { ApiError } from './apiClient'

/** 결과를 기다리는 동안 쓰는 표시 — 제네릭 스피너 대신 브랜드 모티프인 "/"를 펄스시킨다(§7). */
export function LoadingIndicator({ label, className = '' }: { label: string; className?: string }) {
  return (
    <p className={`flex items-center gap-1.5 text-sm text-muted ${className}`}>
      <span className="flex h-4 w-4 shrink-0 animate-pulse items-center justify-center rounded-[4px] bg-accent-blue text-2xs font-semibold text-white">
        /
      </span>
      {label}
    </p>
  )
}

/** 문장 안 서술어 자리에 받침 유무로 "이에요"/"예요"를 고른다 (예: "맑음"→"맑음이에요", "비"→"비예요"). */
export function withCopula(noun: string): string {
  const code = noun.charCodeAt(noun.length - 1)
  const hasFinalConsonant = code >= 0xac00 && code <= 0xd7a3 && (code - 0xac00) % 28 !== 0
  return `${noun}${hasFinalConsonant ? '이에요' : '예요'}`
}

/** 주격 조사 — 받침이 있으면 '은', 없으면 '는'. */
export function withTopicParticle(noun: string): string {
  const code = noun.charCodeAt(noun.length - 1)
  const hasFinalConsonant = code >= 0xac00 && code <= 0xd7a3 && (code - 0xac00) % 28 !== 0
  return `${noun}${hasFinalConsonant ? '은' : '는'}`
}

/** 목적격 조사 — 받침이 있으면 '을', 없으면 '를'. ('검색어를 입력' / '파일 이름을 입력') */
export function withObjectParticle(noun: string): string {
  const code = noun.charCodeAt(noun.length - 1)
  const hasFinalConsonant = code >= 0xac00 && code <= 0xd7a3 && (code - 0xac00) % 28 !== 0
  return `${noun}${hasFinalConsonant ? '을' : '를'}`
}

/** 결과값을 그대로 늘어놓지 않고 사람이 답하듯 한 문장으로 합친다 — DESIGN.md §10 "결과 응답 스타일" 참고. */
export function describeWeather(result: WeatherLookupResult): string {
  const place = withTopicParticle(result.region || result.location)
  const temperature = Math.round(result.temperature)
  const apparent = Math.round(result.apparentTemperature)
  const rainNote = result.precipitation > 0 ? ` 비도 조금 내리고 있어요 (강수량 ${result.precipitation}mm).` : ''
  return `${place} 지금 ${temperature}°, ${withCopula(result.description)} 체감은 ${apparent}°이고, 습도는 ${result.humidity}%, 바람은 초속 ${result.windSpeed}m로 불고 있어요.${rainNote}`
}

/** WEATHER_LOOKUP 결과 카드 — slash-infra 이슈 #42 검증 중 실측한 필드 그대로 렌더링. */
export function WeatherResultCard({ result }: { result: WeatherLookupResult }) {
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm leading-6 text-foreground">{describeWeather(result)}</p>
      <div className="flex items-baseline justify-between gap-3 border-t border-hairline pt-3">
        <div>
          <p className="text-sm text-muted">{result.region}</p>
          <p className="text-2xl font-semibold text-foreground">{Math.round(result.temperature)}°</p>
        </div>
        <div className="text-right">
          <p className="text-sm text-foreground">{result.description}</p>
          <p className="text-xs text-muted">체감 {Math.round(result.apparentTemperature)}°</p>
        </div>
      </div>
      <div className="flex items-center gap-4 border-t border-hairline pt-3 text-xs text-muted">
        <span className="flex items-center gap-1.5">
          <Droplets size={14} />
          습도 {result.humidity}%
        </span>
        <span className="flex items-center gap-1.5">
          <Wind size={14} />
          풍속 {result.windSpeed}m/s
        </span>
      </div>
    </div>
  )
}

type TextSummaryResultUnion = TextSummaryResult | BrowserTextSummaryResult

/** TEXT_SUMMARY 결과 카드 — CPU 추출·Gemma는 slash-infra 이슈 #42 실측 필드,
 *  브라우저 WebLLM은 이 브라우저에서 요약할 때 보여주던 것과 같은 캡션을 쓴다
 *  (SearchBar.tsx의 실시간 표시와 이력 화면이 같은 문구를 보여줘야 한다). */
export function TextSummaryResultCard({ result }: { result: TextSummaryResultUnion }) {
  const caption =
    'modelId' in result
      ? '이 브라우저에서 직접 요약했어요 · 원문이 서버로 전송되지 않았어요.'
      : `${result.model}이(가) 요약했어요.`

  return (
    <div className="flex flex-col gap-2">
      <p className="whitespace-pre-wrap text-sm text-foreground">{result.summary}</p>
      <p className="text-xs text-muted">{caption}</p>
    </div>
  )
}

export function SystemStatusResultCard({ result }: { result: SystemStatusResult }) {
  const rows = [
    { label: 'CPU', percent: result.cpuPercent, detail: null },
    {
      label: '메모리',
      percent: result.memoryPercent,
      detail: `${result.memoryUsedMb.toLocaleString()} / ${result.memoryTotalMb.toLocaleString()} MB`,
    },
  ]
  if (result.diskPercent !== undefined) {
    rows.push({
      label: '디스크',
      percent: result.diskPercent,
      detail: `${result.diskUsedMb!.toLocaleString()} / ${result.diskTotalMb!.toLocaleString()} MB`,
    })
  }
  return (
    <div className="flex flex-col gap-2">
      {rows.map((row) => (
        <div key={row.label} className="flex items-center justify-between gap-3 text-sm">
          <span className="text-muted">{row.label}</span>
          <span className="text-foreground">
            {row.percent.toFixed(1)}%{row.detail ? ` · ${row.detail}` : ''}
          </span>
        </div>
      ))}
      {result.diskPercent === undefined && <p className="text-xs text-muted">디스크 정보를 읽지 못했어요.</p>}
    </div>
  )
}

type FileOpenState = { phase: 'idle' | 'loading' | 'done' } | { phase: 'error'; message: string }

const OPEN_POLL_INTERVAL_MS = 1500

/** 파일 검색 결과 행의 "위치 보기" 버튼 — FILE_OPEN은 fileRef를 그대로 돌려보내는 새 task라
 *  (결과 카드 없음, Finder·탐색기만 뜬다) ChatDetailPage로 옮기지 않고 이 자리에서 폴링해
 *  버튼 하나로 완결한다(복사·읽어주기 버튼과 같은 인라인 패턴). */
function FileOpenButton({ fileRef }: { fileRef: string }) {
  const [state, setState] = useState<FileOpenState>({ phase: 'idle' })
  const cancelledRef = useRef(false)
  useEffect(() => () => {
    cancelledRef.current = true
  }, [])

  async function pollUntilDone(taskId: string) {
    const detail = await getTask(taskId)
    if (cancelledRef.current) return
    if (!isTerminalTaskStatus(detail.status)) {
      await new Promise((resolve) => setTimeout(resolve, OPEN_POLL_INTERVAL_MS))
      if (!cancelledRef.current) await pollUntilDone(taskId)
      return
    }
    if (detail.status === 'SUCCEEDED') {
      setState({ phase: 'done' })
      setTimeout(() => !cancelledRef.current && setState({ phase: 'idle' }), 2000)
    } else {
      setState({ phase: 'error', message: taskErrorMessage(detail.errorCode) })
    }
  }

  async function openLocation() {
    if (state.phase === 'loading') return
    setState({ phase: 'loading' })
    try {
      const created = await createTaskRequest(`/open ${fileRef}`)
      await pollUntilDone(created.taskId)
    } catch (err) {
      if (!cancelledRef.current) {
        setState({ phase: 'error', message: err instanceof ApiError ? err.message : '요청을 보내지 못했어요.' })
      }
    }
  }

  if (state.phase === 'done') {
    return (
      <span className="flex shrink-0 items-center gap-1 text-xs text-accent-green">
        <Check size={13} />
        열었어요
      </span>
    )
  }
  return (
    <button
      type="button"
      onClick={openLocation}
      disabled={state.phase === 'loading'}
      className="flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-xs text-muted transition-colors hover:bg-foreground/8 hover:text-foreground disabled:opacity-60"
    >
      {state.phase === 'loading' ? <Loader2 size={13} className="animate-spin" /> : <FolderOpen size={13} />}
      {state.phase === 'error' ? state.message : '위치 보기'}
    </button>
  )
}

export function FileSearchResultList({ result }: { result: FileSearchResult }) {
  if (result.items.length === 0) {
    return <p className="text-sm text-muted">일치하는 파일이 없어요.</p>
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="max-h-64 overflow-y-auto">
        {result.items.map((f) => (
          <div key={f.fileRef} className="flex items-center gap-2.5 py-2 text-sm">
            <FileText size={16} className="shrink-0 text-muted" />
            <span className="min-w-0 flex-1 truncate text-foreground">{f.name}</span>
            <span className="max-w-[30%] shrink-0 truncate text-xs text-muted">{f.relativePath}</span>
            <FileOpenButton fileRef={f.fileRef} />
          </div>
        ))}
      </div>
      {result.truncated && <p className="text-xs text-muted">결과가 더 있어요 — 검색어를 좁혀보세요.</p>}
    </div>
  )
}

const CODE_ADAPTER_LABELS: Record<CodeAnalysisResult['codeAdapter'], string> = {
  CLAUDE_CODE: 'Claude Code',
  CODEX: 'Codex',
}

/** CODE_ANALYSIS 결과 카드 — 등록한 프로젝트 폴더를 읽기 전용으로 분석한 답. turns는 CLI가
 *  준 값을 못 읽으면 null로 온다(slash-agent code_adapters.py). */
export function CodeAnalysisResultCard({ result }: { result: CodeAnalysisResult }) {
  const turnsLabel = result.turns !== null ? ` · ${result.turns}턴` : ''
  return (
    <div className="flex flex-col gap-2">
      <p className="whitespace-pre-wrap text-sm text-foreground">{result.summary}</p>
      <p className="text-xs text-muted">
        {CODE_ADAPTER_LABELS[result.codeAdapter]}이(가) 분석했어요{turnsLabel} ·{' '}
        {(result.durationMs / 1000).toFixed(1)}초
      </p>
    </div>
  )
}

/** AI_AGENT_USAGE 결과 카드 — frontend-api-contract.md §AI_AGENT_USAGE 실측 필드 그대로.
 *  provider별로 totalReasoningTokens 유무가 갈리고(Claude Code는 항상 null), 세션은
 *  있는데 토큰이 전부 0으로 오는 실측 케이스가 있어 그 경우 숫자 대신 안내 문구를 보여준다. */
export function AiAgentUsageResultCard({ result }: { result: AiAgentUsageResult }) {
  const zeroTokensDespiteSessions = result.totalSessions > 0 && result.totalTokens === 0
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="text-muted">세션</span>
        <span className="text-foreground">{result.totalSessions.toLocaleString()}개</span>
      </div>
      {zeroTokensDespiteSessions ? (
        <p className="text-xs text-muted">
          세션 기록은 있지만 토큰 사용량을 아직 못 읽었어요 — 로그 파일 형식이 바뀌었을 수 있어요.
        </p>
      ) : (
        <>
          <div className="flex items-center justify-between gap-3 text-sm">
            <span className="text-muted">총 토큰</span>
            <span className="tabular-nums text-foreground">{result.totalTokens.toLocaleString()}</span>
          </div>
          <p className="text-xs text-muted">
            입력 {result.totalInputTokens.toLocaleString()} · 출력 {result.totalOutputTokens.toLocaleString()} ·
            캐시 {result.totalCachedTokens.toLocaleString()}
            {result.totalReasoningTokens !== null && ` · 추론 ${result.totalReasoningTokens.toLocaleString()}`}
          </p>
        </>
      )}
      <p className="text-xs text-muted">
        {result.totalSessions > 0 && result.oldestSessionAt && result.newestSessionAt
          ? `${formatRelativeTime(result.oldestSessionAt)} ~ ${formatRelativeTime(result.newestSessionAt)} 세션 기준`
          : '아직 사용 기록이 없어요.'}
      </p>
    </div>
  )
}

/** 진행 중 상태별 안내 문구 — frontend-api-contract.md §W1-04 "상태값" 표. */
export const TASK_STATUS_LABELS: Partial<Record<TaskStatus, string>> = {
  ANALYZING: '무슨 요청인지 분석하는 중이에요',
  QUEUED: 'PC로 보냈어요, 수락을 기다리는 중이에요',
  RUNNING: '실행 중이에요',
  WAITING_FOR_DEVICE: 'PC가 꺼져 있어요 — 켜지면 자동으로 실행돼요',
  NEEDS_CLARIFICATION: '추가 정보가 필요해요',
}

/** 실패한 작업의 errorCode별 안내 — 계약서 §4 표 중 /status가 실제로 낼 수 있는 것들. */
const TASK_ERROR_MESSAGES: Partial<Record<string, string>> = {
  DEVICE_NOT_READY: 'PC 연결 상태를 확인해주세요.',
  DEVICE_BUSY: '다른 작업을 실행 중이에요. 잠시 후 다시 시도해주세요.',
  TASK_TYPE_NOT_SUPPORTED: '이 PC가 지원하지 않는 기능이에요.',
  TASK_EXPIRED: '실행 기한이 지났어요.',
  UNRECOGNIZED_COMMAND: '요청을 알아듣지 못했어요.',
  SEARCH_FOLDER_NOT_FOUND: 'PC의 에이전트에서 검색할 폴더를 추가해주세요.',
  FILE_NOT_FOUND: '파일을 찾을 수 없어요. 그 사이 옮겨졌거나 지워진 것 같아요.',
  AGENT_REJECTED: 'PC가 이 요청을 받지 않았어요.',
  AGENT_TASK_FAILED: 'PC에서 실행이 끝나지 못했어요.',
  DEVICE_REVOKED: 'PC 등록이 해제됐어요. 다시 등록해주세요.',
  NLU_UNAVAILABLE: '잠시 후 다시 시도해주세요.',
  UPSTREAM_UNAVAILABLE: '외부 서비스에 문제가 있어요.',
  LOCATION_NOT_FOUND: '지역을 찾지 못했어요. 시·군 이름으로 다시 말씀해주세요.',
  CODE_AGENT_NOT_CONFIGURED: '이 PC에서 그 도구를 쓴 적이 없어요.',
  WORKSPACE_NOT_FOUND: 'PC의 에이전트에서 분석할 프로젝트 폴더를 추가해주세요.',
  INVALID_PARAMETERS: '입력값을 다시 확인해주세요.',
  POLICY_DENIED: '요청을 처리하지 못했어요. 시간이 오래 걸리거나 실행 중 문제가 생겼을 수 있어요.',
}

export function taskErrorMessage(code: string | null): string {
  return (code && TASK_ERROR_MESSAGES[code]) || '요청이 실패했어요.'
}

/** 복사·읽어주기가 읽을 한 줄 — taskType마다 결과 모양이 달라 사람이 답하듯 한 문장으로 만든다. */
export function summarizeResult(taskType: string | null, result: TaskDetailResultUnion | null): string | null {
  if (!result) return null
  switch (taskType) {
    case 'WEATHER_LOOKUP':
      return describeWeather(result as WeatherLookupResult)
    case 'TEXT_SUMMARY':
      return (result as TextSummaryResultUnion).summary
    case 'SYSTEM_STATUS': {
      const r = result as SystemStatusResult
      const disk = r.diskPercent !== undefined ? `, 디스크 ${r.diskPercent.toFixed(1)}%` : ''
      return `CPU ${r.cpuPercent.toFixed(1)}%, 메모리 ${r.memoryPercent.toFixed(1)}%${disk}를 쓰고 있어요.`
    }
    case 'FILE_SEARCH': {
      const r = result as FileSearchResult
      return r.items.length === 0 ? '일치하는 파일이 없어요.' : `파일 ${r.items.length}개를 찾았어요.`
    }
    case 'CODE_ANALYSIS':
      return (result as CodeAnalysisResult).summary
    case 'AI_AGENT_USAGE': {
      const r = result as AiAgentUsageResult
      return r.totalSessions > 0 && r.totalTokens === 0
        ? '세션 기록은 있지만 토큰 사용량을 아직 못 읽었어요.'
        : `세션 ${r.totalSessions.toLocaleString()}개, 토큰 ${r.totalTokens.toLocaleString()}개를 썼어요.`
    }
    default:
      return null
  }
}

type TaskDetailResultUnion =
  | SystemStatusResult
  | FileSearchResult
  | WeatherLookupResult
  | TextSummaryResultUnion
  | CodeAnalysisResult
  | AiAgentUsageResult

/** taskType에 맞는 결과 카드로 분기 — 아직 화면이 없는 타입(FILE_OPEN·AI_AGENT_USAGE 등)은 null. */
export function ResultCard({ taskType, result }: { taskType: string | null; result: TaskDetailResultUnion }) {
  switch (taskType) {
    case 'WEATHER_LOOKUP':
      return <WeatherResultCard result={result as WeatherLookupResult} />
    case 'TEXT_SUMMARY':
      return <TextSummaryResultCard result={result as TextSummaryResultUnion} />
    case 'SYSTEM_STATUS':
      return <SystemStatusResultCard result={result as SystemStatusResult} />
    case 'FILE_SEARCH':
      return <FileSearchResultList result={result as FileSearchResult} />
    case 'CODE_ANALYSIS':
      return <CodeAnalysisResultCard result={result as CodeAnalysisResult} />
    case 'AI_AGENT_USAGE':
      return <AiAgentUsageResultCard result={result as AiAgentUsageResult} />
    default:
      return null
  }
}
