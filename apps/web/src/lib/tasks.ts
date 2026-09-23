// 작업 접수/조회 — frontend-api-contract.md "입력창 화면(W1-04)" 구현.
// selectedDeviceId는 일부러 옵셔널로만 받는다 — "PC 고르는 화면이 아직 없으면 생략해도 되고,
// 서버가 연결된 PC 중에서 알아서 고른다"가 계약이라, PC 선택 UI가 없는 지금은 아예 안 보낸다.
import { apiRequest, newIdempotencyKey } from './apiClient'

export type TaskStatus =
  | 'ANALYZING'
  | 'NEEDS_CLARIFICATION'
  | 'WAITING_FOR_DEVICE'
  | 'QUEUED'
  | 'RUNNING'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'EXPIRED'

/** 진행 중(폴링 계속)인 상태 — SUCCEEDED/FAILED/EXPIRED만 최종 상태다. */
export function isTerminalTaskStatus(status: TaskStatus): boolean {
  return status === 'SUCCEEDED' || status === 'FAILED' || status === 'EXPIRED'
}

export interface TaskCreateResponse {
  taskId: string
  status: TaskStatus
  statusUrl: string
}

// slash-api 이슈 #38 — PC가 디스크를 읽지 못하면 Agent가 null로 두고, null 필드는 응답에서
// 아예 빠진다(계약서 §2). CPU·메모리는 항상 온다.
export interface SystemStatusResult {
  cpuPercent: number
  memoryPercent: number
  memoryTotalMb: number
  memoryUsedMb: number
  diskPercent?: number
  diskTotalMb?: number
  diskUsedMb?: number
  collectedAt: string
}

// 계약서 §2.1 FILE_SEARCH — Agent(slash-python-agent/file_index.py)가 실제로 보내는 여섯 필드
// (slash-api 이슈 #38). fileRef는 절대 경로 대신 쓰는 열쇠로, 열기 같은 후속 동작에 그대로
// 돌려보낸다. extension은 없으면 빈 문자열.
export interface FileSearchResultItem {
  fileRef: string
  name: string
  relativePath: string
  extension: string
  sizeBytes: number
  modifiedAt: string
}

export interface FileSearchResult {
  searchFolderId: string
  query: string
  items: FileSearchResultItem[]
  returnedCount: number
  truncated: boolean
}

// slash-infra 이슈 #42 검증 중 실측된 형태(slash-api PR #43 `WEATHER_LOOKUP`).
export interface WeatherLookupResult {
  location: string
  region: string
  country: string
  temperature: number
  apparentTemperature: number
  humidity: number
  windSpeed: number
  precipitation: number
  description: string
  observedAt: string
}

// slash-infra 이슈 #42 검증 중 실측된 형태(slash-api PR #42 `TEXT_SUMMARY`, slash-llm 연동).
export interface TextSummaryResult {
  summary: string
  model: string
}

// executionTarget이 BROWSER일 때의 결과 형태 — submitBrowserSummaryResult로 제출한 그대로
// 되돌아온다(frontend-api-contract.md "브라우저에서 이미 끝낸 요약 제출하기").
export interface BrowserTextSummaryResult {
  summary: string
  modelId: string
  promptVersion: string
  durationMs?: number
}

// slash-api docs/frontend-api-contract.md §CODE_ANALYSIS. slash-agent의 code_adapters.py가
// 실제로 만드는 필드 그대로다 — turns는 CLI가 준 값을 못 읽으면 null로 온다.
export interface CodeAnalysisResult {
  codeAdapter: 'CLAUDE_CODE' | 'CODEX'
  summary: string
  turns: number | null
  durationMs: number
  collectedAt: string
}

// slash-api docs/frontend-api-contract.md §AI_AGENT_USAGE. 다른 결과 타입과 다른 두 가지 예외가
// 있다 — totalReasoningTokens는 값이 없어도 null로 오고 필드가 안 빠진다(Claude Code는 null,
// Codex는 숫자). oldestSessionAt·newestSessionAt은 UTC(Z)로 오고 같은 응답의 collectedAt은
// KST라 한 응답에 시각 두 표기가 섞인다 — 그 도구를 쓴 적 없으면 CODE_AGENT_NOT_CONFIGURED(422).
export interface AiAgentUsageResult {
  provider: 'CLAUDE_CODE' | 'CODEX'
  totalSessions: number
  totalInputTokens: number
  totalOutputTokens: number
  totalCachedTokens: number
  totalReasoningTokens: number | null
  totalTokens: number
  oldestSessionAt: string | null
  newestSessionAt: string | null
  collectedAt: string
}

export interface TaskDetail {
  taskId: string
  status: TaskStatus
  taskType: string | null
  result:
    | SystemStatusResult
    | FileSearchResult
    | WeatherLookupResult
    | TextSummaryResult
    | BrowserTextSummaryResult
    | CodeAnalysisResult
    | AiAgentUsageResult
    | null
  errorCode: string | null
  // NEEDS_CLARIFICATION일 때만 채워진다 — slash-api TaskDetailResponse의 question/correlationId
  // 그대로다. correlationId는 지금은 화면에서 쓰지 않지만(백엔드가 이어가는 대화가 아니라 새
  // text로 새 요청을 받는 구조라 답변도 새 요청이다), 응답 계약을 그대로 담아둔다.
  question?: string | null
  correlationId?: string | null
  /** 사용자가 접수 시점에 친 원문. 채팅 상세 화면의 사용자 말풍선·"다시 생성"에 쓴다. */
  inputText: string
  createdAt: string
  /** 끝난 작업만 있다. */
  completedAt?: string
}

export function createTaskRequest(text: string, selectedDeviceId?: string): Promise<TaskCreateResponse> {
  return apiRequest<TaskCreateResponse>('/api/v1/requests', {
    method: 'POST',
    body: selectedDeviceId ? { text, selectedDeviceId } : { text },
    idempotencyKey: newIdempotencyKey(),
  })
}

export function getTask(taskId: string): Promise<TaskDetail> {
  return apiRequest<TaskDetail>(`/api/v1/tasks/${taskId}`)
}

/** 브라우저(WebLLM)가 이미 끝낸 요약 결과를 제출한다 — slash-docs#3 권장 순서 3번.
 *
 *  원문은 여기 없다. `inputLength`(글자 수)만 보낸다 — 원문을 브라우저 밖으로 내보내지
 *  않는다는 게 이 경로의 존재 이유라, 호출부가 실수로 원문을 실어 보내도 받을 자리가
 *  없다. 응답은 `/requests`처럼 202가 아니라 이미 최종 상태(SUCCEEDED/FAILED)라 폴링할
 *  게 없다.
 *
 *  Idempotency-Key는 `/requests`와 달리 필수다 — 재시도가 실행을 다시 트리거하는 게
 *  아니라 새 이력을 또 만드는 것으로 이어지므로, 호출부가 요약 1회당 한 번만 불러야
 *  한다(재시도 시에도 같은 결과로 다시 부르면 서버가 같은 이력으로 묶어 준다). */
export function submitBrowserSummaryResult(params: {
  inputLength: number
  modelId: string
  promptVersion: string
  status: 'SUCCEEDED' | 'FAILED'
  summary?: string
  durationMs?: number
  errorMessage?: string
}): Promise<TaskCreateResponse> {
  return apiRequest<TaskCreateResponse>('/api/v1/tasks/text-summary/browser-result', {
    method: 'POST',
    body: params,
    idempotencyKey: newIdempotencyKey(),
  })
}

// 이력 화면·대시보드·사이드바 "최근" — frontend-api-contract.md "이력 화면 (P0-B)" 구현.
// result·parameters는 목록에 없다(한 건에 64KB까지 허용돼 스무 줄이면 1MB를 넘길 수 있어서) —
// 한 건 펼칠 때는 getTask로 따로 받는다.
export interface TaskHistoryItem {
  taskId: string
  status: TaskStatus
  /** 분석 전이거나 분석에 실패했으면 없다. */
  taskType?: string
  processingRoute?: string
  /** PC를 거치지 않는 작업(/weather·/summary)은 없다. */
  deviceId?: string
  requestSummary: string
  errorCode?: string
  createdAt: string
  /** 끝난 작업만 있다. */
  completedAt?: string
}

export interface TaskHistoryFilter {
  taskType?: string
  status?: TaskStatus
  deviceId?: string
  /** 1~100, 기본 20. */
  limit?: number
  /** 이전 응답의 nextCursor를 그대로 넣는다 — 뜻을 알 수 없는 값이라 내용을 들여다볼 필요는 없다. */
  cursor?: string
}

export interface TaskHistoryPage {
  items: TaskHistoryItem[]
  /** 없으면 마지막 쪽 — 항목 수가 limit과 같은지로 판단하면 안 된다. */
  nextCursor?: string
}

export function getTaskHistory(filter: TaskHistoryFilter = {}): Promise<TaskHistoryPage> {
  const params = new URLSearchParams()
  if (filter.taskType) params.set('taskType', filter.taskType)
  if (filter.status) params.set('status', filter.status)
  if (filter.deviceId) params.set('deviceId', filter.deviceId)
  if (filter.limit) params.set('limit', String(filter.limit))
  if (filter.cursor) params.set('cursor', filter.cursor)

  const query = params.toString()
  return apiRequest<TaskHistoryPage>(`/api/v1/tasks${query ? `?${query}` : ''}`)
}

/** taskType → 배지·필터에 쓰는 명령 이름. 결과 화면(ResultCard, taskResultRenderers.tsx)이 있는
 *  타입만 넣는다 — 히스토리 필터 드롭다운도 이 맵의 키를 그대로 옵션으로 쓴다(배지와 필터가
 *  서로 다른 기준으로 어긋나지 않도록 한 곳만 고친다). */
export const TASK_TYPE_COMMAND_LABELS: Record<string, string> = {
  WEATHER_LOOKUP: '날씨',
  TEXT_SUMMARY: '요약',
  FILE_SEARCH: '파일',
  SYSTEM_STATUS: '상태',
  CODE_ANALYSIS: '코드',
  AI_AGENT_USAGE: '사용량',
}

/** 히스토리·최근·대시보드가 공유하는 행 모양. commandLabel은 requestSummary 문자열이 아니라
 *  taskType으로 정한다 — 브라우저 요약(WebLLM)처럼 실제로는 `/요약`으로 시작했지만 원문을 서버에
 *  보내지 않아 requestSummary가 `/`로 시작하지 않는 경우가 있어서, 텍스트 접두어만으로는
 *  명령 여부를 알 수 없다(taskType은 항상 그 작업이 실제로 어떤 종류인지를 담고 있다). text는
 *  명령이었다면 그 토큰을 뗀 나머지만 담는다 — 행에서 CommandBadge와 나란히 그리는 게
 *  이미 그 토큰을 보여주므로, text에 남겨두면 "/날씨 /날씨 서울"처럼 중복된다. */
export type HistoryEntry = { id: string; text: string; commandLabel: string | null; timeLabel: string }

export function toHistoryEntry(item: TaskHistoryItem): HistoryEntry {
  const commandLabel = (item.taskType && TASK_TYPE_COMMAND_LABELS[item.taskType]) ?? null
  // FILE_OPEN의 원문은 "/open f62dfe8a-…"처럼 사용자가 알아볼 수 없는 fileRef를 담고 있다 —
  // 파일 검색 결과 카드의 "위치 보기" 버튼이 대신 보낸 것이라(사용자가 직접 친 게 아님) 잘라내는
  // 걸로는 못 고친다. 고정 문구로 통째로 바꾼다.
  if (item.taskType === 'FILE_OPEN') {
    return {
      id: item.taskId,
      text: '파일 위치 보기',
      commandLabel,
      timeLabel: formatRelativeTime(item.createdAt),
    }
  }
  const isCommand = item.requestSummary.startsWith('/')
  // taskType이 안 알려진 명령이면(라벨 없음) 배지를 못 그리니 원문을 그대로 둔다 — 잘라내기만
  // 하고 배지가 안 뜨면 명령 토큰 자체가 화면에서 사라져버린다.
  const text = isCommand && commandLabel ? item.requestSummary.split(' ').slice(1).join(' ') : item.requestSummary
  return {
    id: item.taskId,
    text,
    commandLabel,
    timeLabel: formatRelativeTime(item.createdAt),
  }
}

export function formatRelativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const diffMinutes = Math.floor(diffMs / 60_000)
  const diffHours = Math.floor(diffMs / 3_600_000)
  const diffDays = Math.floor(diffMs / 86_400_000)

  if (diffMinutes < 1) return '방금 전'
  if (diffMinutes < 60) return `${diffMinutes}분 전`
  if (diffHours < 24) return `${diffHours}시간 전`
  if (diffDays === 1) return '어제'
  if (diffDays === 2) return '그저께'
  if (diffDays < 7) return `${diffDays}일 전`
  return new Date(iso).toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' })
}
