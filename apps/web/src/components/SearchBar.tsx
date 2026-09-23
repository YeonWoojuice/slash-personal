import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router'
import {
  Mic,
  AudioLines,
  Paperclip,
  Camera,
  Plus,
  ArrowUp,
  X,
  FileText,
  ChevronDown,
} from 'lucide-react'
import { Tooltip } from './Tooltip'
import { MicSettingsPopover } from './MicSettingsPopover'
import {
  ModelPickerPanel,
  ServiceIcon,
  SERVICES,
  MODELS_BY_SERVICE,
  type ModelView,
  type SelectedModel,
} from './ModelPickerPanel'
import { parseCommandChain, mockPlaceholderMessage } from '../lib/mockCommands'
import { buildDeepLink, deepLinkHint } from '../lib/deepLinks'
import { getSuggestions, findCommand, type CommandNode } from '../lib/commandTree'
import { useAgentStatus } from '../hooks/agentStatusContext'
import { ApiError } from '../lib/apiClient'
import { createTaskRequest, submitBrowserSummaryResult, type TaskStatus } from '../lib/tasks'
import { isWebGpuSupported } from '../lib/webgpuSupport'
import type { SummarizeProgress } from '../lib/webllm'
import {
  isWebLlmSummaryError,
  toWebLlmFailureCode,
  WEBLLM_MODEL_ID,
  WEBLLM_PROMPT_VERSION,
} from '../lib/webllmSummary'
import {
  withObjectParticle,
  TASK_STATUS_LABELS,
  LoadingIndicator,
} from '../lib/taskResultRenderers'

function AddMenuItem({
  icon: Icon,
  label,
  trailing,
  onClick,
}: {
  icon: typeof Plus
  label: string
  trailing?: ReactNode
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-foreground/8"
    >
      <Icon size={16} className="shrink-0 text-muted" />
      <span className="flex-1">{label}</span>
      {trailing}
    </button>
  )
}

type Attachment = {
  id: string
  name: string
  /** Preview image URL — present for images/screenshots, absent for other file types. */
  url?: string
}

/** 명령어가 이미 받은 값 하나를 나타내는 검색바 안쪽 칩. */
function OperandChip({ label, onClear }: { label: string; onClear: () => void }) {
  return (
    <span className="flex items-center gap-1 rounded-full bg-accent-blue/12 py-1 pl-2.5 pr-1.5 text-xs font-medium text-accent-blue">
      {label}
      <button
        type="button"
        aria-label={`${label} 지우기`}
        onClick={onClear}
        className="flex h-4 w-4 items-center justify-center rounded-full transition-colors hover:bg-accent-blue/20"
      >
        <X size={11} />
      </button>
    </span>
  )
}

// 접수(POST /requests)에 성공하는 순간 taskId로 /chat/{taskId}로 이동한다 — 결과는 그 화면이
// 폴링해서 보여준다. 그래서 여기 상태는 "접수 자체가 됐는지"만 추적하면 되고, 결과 phase('done')는
// 없다.
type StatusTaskState = { phase: 'idle' } | { phase: 'running'; status: TaskStatus } | { phase: 'failed'; message: string }

type FileSearchTaskState =
  | { phase: 'idle' }
  | { phase: 'running'; status: TaskStatus }
  | { phase: 'failed'; message: string }

type FreeTextTaskState =
  | { phase: 'idle' }
  | { phase: 'running'; status: TaskStatus }
  | { phase: 'failed'; message: string }

// /요약을 브라우저(WebLLM)에서 처리할 때만 쓴다 — 서버로 보내지 않으므로 결과가 먼저 나오고,
// 그 다음 이력에 남기려고 결과만 slash-api에 제출한다(runBrowserSummaryCommand). 제출이
// 성공하면 그 taskId로 /chat으로 옮기므로 이 succeeded 상태는 잠깐만 보인다. 제출이 실패하면
// 옮길 taskId가 없어 이 자리에 남는데, `historySaveFailed`가 그 경우를 표시해 안내 문구를 띄운다.
type BrowserSummaryTaskState =
  | { phase: 'idle' }
  | { phase: 'loading'; progress: number; message: string }
  | { phase: 'generating' }
  | { phase: 'succeeded'; summary: string; historySaveFailed?: boolean }
  | { phase: 'failed'; message: string }

// 입력창이 가로로 무한히 늘어나지 않도록 세로 auto-resize의 상한 — 대략 8줄.
const TEXTAREA_MAX_HEIGHT_PX = 192

export function SearchBar({ presetQuery }: { presetQuery?: { path: string[]; operands: string[] } }) {
  const [value, setValue] = useState('')
  const [focused, setFocused] = useState(false)
  const [addMenuOpen, setAddMenuOpen] = useState(false)
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [isRecording, setIsRecording] = useState(false)
  const [micSettingsOpen, setMicSettingsOpen] = useState(false)
  const [selectedMicId, setSelectedMicId] = useState<string | null>(null)
  const [holdToRecord, setHoldToRecord] = useState(true)
  const [highlightIndex, setHighlightIndex] = useState(0)
  const [modelView, setModelView] = useState<ModelView>('services')
  const [modelHighlight, setModelHighlight] = useState(0)
  const [selectedModel, setSelectedModel] = useState<SelectedModel>({ service: 'claude', modelId: 'sonnet-5' })
  const [modelSearchPickerOpen, setModelSearchPickerOpen] = useState(false)
  // Enter로 제출했을 때도 검색 버튼을 마우스로 누른 것과 같은 눌림 효과를 잠깐 보여준다.
  const [keyboardPressed, setKeyboardPressed] = useState(false)
  // 값을 받는 명령(`/네이버`, `/구글`, `/파일`, `/네이버/길찾기` …)은 명령어 텍스트를 입력창에
  // 남겨두지 않고 칩으로 뺀다. path = 명령어 경로, operands = 이미 확정된 값(칩).
  // 지금 입력 중인 값은 `value`에 있다 — 명령어와 검색어는 한 문자열로 합치지 않고 끝까지 따로
  // 들고 있다가 백엔드에도 따로 보낸다.
  const [commandMode, setCommandMode] = useState<{ path: string[]; operands: string[] } | null>(null)
  const [statusTask, setStatusTask] = useState<StatusTaskState>({ phase: 'idle' })
  const [fileSearchTask, setFileSearchTask] = useState<FileSearchTaskState>({ phase: 'idle' })
  const [freeTextTask, setFreeTextTask] = useState<FreeTextTaskState>({ phase: 'idle' })
  const [browserSummaryTask, setBrowserSummaryTask] = useState<BrowserSummaryTaskState>({ phase: 'idle' })
  const fileInputRef = useRef<HTMLInputElement>(null)
  const textInputRef = useRef<HTMLTextAreaElement>(null)
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null)
  const agentStatus = useAgentStatus()
  const navigate = useNavigate()
  const location = useLocation()
  // IME composition tracking (한글/일본어/중국어 등) — Enter that confirms a composing syllable
  // must NOT also trigger our own Enter handling, or the last character doubles.
  const isComposingRef = useRef(false)
  const compositionEndedAtRef = useRef(0)
  // 조합 확정에 먹힌 Enter가 있었는지 — 같은 키의 keyup에서 실제 동작을 실행하기 위한 표시.
  const pendingEnterRef = useRef(false)

  const trimmed = value.trim()
  const hasText = trimmed.length > 0
  // 명령어 모드에서는 입력창에 명령어 텍스트가 남아 있지 않고(칩으로 빠져 있음) 값만 들어있다 —
  // 그래도 명령 모드이므로 `/` 배지는 파랗게, 자유입력 힌트는 뜨지 않게 해야 한다.
  const isCommand = value.startsWith('/') || commandMode !== null
  const isFreeText = hasText && !isCommand
  const hasAttachments = attachments.length > 0
  const active = focused || hasText || commandMode !== null
  // 완전 pill(rounded-full)은 명령어 칩·여러 줄 내용이 들어차면 곡률이 과해져 번잡해 보였다
  // (2026-08-20) — 항상 첨부파일 상태와 같은 28px 라운드 사각형으로 통일.
  const shape = 'rounded-[28px]'

  // 명령어가 받는 값들의 이름 — 하나면 한 번에 받고, 둘 이상이면 Enter마다 한 값씩 확정한다.
  const operandNames = (commandMode ? findCommand(commandMode.path)?.operands : null) ?? []
  const stepped = operandNames.length > 1
  const nextOperandName: string | undefined = operandNames[commandMode?.operands.length ?? 0]
  const operandsFilled = commandMode !== null && operandNames.length > 0 && nextOperandName === undefined

  // 명령어 모드에서는 텍스트를 파싱하지 않는다 — 경로와 값이 이미 나뉘어 있으니 그대로 조립만 한다.
  // (모드에 들어가지 않는 미등록 명령은 예전처럼 한 줄 텍스트에서 파싱한다.)
  const commandChain =
    commandMode !== null
      ? hasText
        ? { namespace: commandMode.path[0], action: commandMode.path[1] ?? '', query: trimmed }
        : null
      : isCommand
        ? parseCommandChain(value)
        : null
  const suggestions = commandMode === null && isCommand ? getSuggestions(value) : null
  const isFileSearchCommand = commandChain?.namespace === '파일' && !commandChain.action
  const isModelSearchCommand = commandChain?.namespace === '모델' && commandChain.action === '검색'
  const placeholderMsg = commandChain ? mockPlaceholderMessage(commandChain) : null
  const deepLink = commandChain ? buildDeepLink(commandChain) : null
  const deepLinkHintText = commandChain ? deepLinkHint(commandChain) : null
  // 값을 하나만 받고, 딥링크도 없고, /파일처럼 자기 전용 패널도 없는 명령(예: /날씨) — Enter를
  // 치면 자유 텍스트와 같은 방식으로 "/명령어 값" 한 문자열을 그대로 백엔드에 보낸다.
  const isGenericCommand = commandMode !== null && !stepped && !deepLink && commandMode.path[0] !== '파일'
  // 값을 여러 개 받는 명령은 입력 중에도 "지금 무슨 값을 받는 중인지"를 계속 보여준다.
  // 하나만 받는 명령은 값을 치기 시작하면 딥링크·준비중 안내에 자리를 넘긴다.
  const commandModeHint =
    commandMode === null
      ? null
      : operandsFilled
        ? `${commandMode.operands.join(' → ')} · 아직 준비 중이에요.`
        : stepped || !hasText
          ? `${withObjectParticle(nextOperandName!)} 입력하고 Enter를 눌러주세요.`
          : null
  const currentServiceLabel = SERVICES.find((s) => s.id === selectedModel.service)?.label ?? ''
  const currentModelLabel =
    MODELS_BY_SERVICE[selectedModel.service].find((m) => m.id === selectedModel.modelId)?.label ?? ''
  // 모델 이름이 이미 서비스 이름으로 시작하면 "Gemini · Gemini 3 Flash"처럼 겹쳐 읽힌다.
  const modelDestination = currentModelLabel.startsWith(currentServiceLabel)
    ? currentModelLabel
    : `${currentServiceLabel} · ${currentModelLabel}`

  const showModelPicker = commandMode === null && trimmed === '/모델'
  const showStatusCommand = commandMode === null && trimmed === '/상태'
  const showSuggestions = !!suggestions && !showModelPicker && !showStatusCommand
  const showFileSearch = !showSuggestions && !showModelPicker && isFileSearchCommand
  const showModelSearch = !showSuggestions && !showModelPicker && !showFileSearch && isModelSearchCommand
  // 검색 상태 패널이 떠 있으면 "파일 이름을 입력하고 Enter" 줄은 겹쳐서 시끄럽기만 하다.
  const showCommandModeHint = !!commandModeHint && !showFileSearch
  // /요약은 WebGPU가 없으면 서버로 조용히 넘어간다(기존 서버 경로 그대로, 새로 생긴 동작이
  // 아니라 원래도 서버로 가던 경로다) — 그래도 왜 브라우저에서 안 되는지는 미리 알려준다.
  // WebGPU가 있으면 submitCommand에서 runBrowserSummaryCommand가 먼저 채가서 여기까지
  // 오지 않는다(commandModeHint는 이 경우 항상 null이라 겹치지 않음).
  const showWebGpuUnsupportedHint =
    isGenericCommand &&
    commandMode?.path[0] === '요약' &&
    hasText &&
    browserSummaryTask.phase === 'idle' &&
    !isWebGpuSupported()
  const showPlaceholderMsg =
    !showSuggestions && !showModelPicker && !showFileSearch && !showModelSearch && !showCommandModeHint && !!placeholderMsg
  const showDeepLinkHint =
    !showSuggestions &&
    !showModelPicker &&
    !showFileSearch &&
    !showModelSearch &&
    !showCommandModeHint &&
    !!deepLinkHintText
  const modelPickerActive = showModelPicker || (showModelSearch && modelSearchPickerOpen)

  useEffect(() => {
    setHighlightIndex(0)
  }, [value])

  // 입력창을 가로로 무한히 늘리는 대신 세로로 늘어나게 한다 — 높이를 일단 초기화해야
  // 줄어드는 방향(긴 문장을 지웠을 때)도 scrollHeight가 정확히 다시 계산된다.
  useEffect(() => {
    const el = textInputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, TEXTAREA_MAX_HEIGHT_PX)}px`
  }, [value])

  // 쿼리를 고치면 끝난 에러는 지운다 — 진행 중(접수 요청이 나간 상태)인 건 그대로 두고(중복 요청은
  // Enter 쪽에서 막는다) 접수가 끝난 뒤에야 다음 입력에 반응한다.
  useEffect(() => {
    setFileSearchTask((prev) => (prev.phase === 'failed' ? { phase: 'idle' } : prev))
  }, [value])

  // 자유 텍스트도 같은 이유로.
  useEffect(() => {
    setFreeTextTask((prev) => (prev.phase === 'failed' ? { phase: 'idle' } : prev))
  }, [value])

  // 자유 텍스트 모드를 벗어나면(명령어로 바꾸거나 입력을 지우면) 상태를 초기화한다.
  // /날씨처럼 딥링크 없는 단일 값 명령(isGenericCommand)도 같은 freeTextTask를 빌려 쓰므로
  // 그 모드에 있는 동안에는 여기서 지우면 안 된다.
  useEffect(() => {
    if (isFreeText || isGenericCommand) return
    setFreeTextTask({ phase: 'idle' })
  }, [isFreeText, isGenericCommand])

  // 파일 검색 모드를 벗어나면(다른 명령으로 바꾸거나 명령어 자체를 지우면) 상태를 초기화한다 —
  // /상태 쪽의 같은 목적 effect와 동일한 이유.
  useEffect(() => {
    if (commandMode?.path[0] === '파일') return
    setFileSearchTask({ phase: 'idle' })
  }, [commandMode])

  // 브라우저 요약 결과·진행 상태도 같은 이유로, /요약을 벗어나면 지운다.
  useEffect(() => {
    if (commandMode?.path[0] === '요약') return
    setBrowserSummaryTask({ phase: 'idle' })
  }, [commandMode])

  // Suggestion chips on the home screen set a query in from the outside — the caller passes a new
  // object each time (even for the same value), so this fires even on repeat clicks of one chip.
  // 칩도 명령어와 값을 따로 넘기므로 문자열을 만들었다가 다시 쪼갤 일이 없다. 마지막 값만 입력창에
  // 남겨 바로 Enter를 칠 수 있게 하고, 앞의 값들은 확정된 칩으로 들어간다.
  useEffect(() => {
    if (!presetQuery) return
    setCommandMode({ path: presetQuery.path, operands: presetQuery.operands.slice(0, -1) })
    setValue(presetQuery.operands[presetQuery.operands.length - 1] ?? '')
    textInputRef.current?.focus()
  }, [presetQuery])

  // Reset the model picker's drill-down state whenever it closes, so reopening starts fresh.
  useEffect(() => {
    if (!modelPickerActive) {
      setModelView('services')
      setModelHighlight(0)
    }
  }, [modelPickerActive])

  // /status를 벗어나면(입력을 지우거나 다른 명령으로 바꾸면) 상태를 초기화한다.
  useEffect(() => {
    if (showStatusCommand) return
    setStatusTask({ phase: 'idle' })
  }, [showStatusCommand])

  // /모델/검색 stops being the active command (query cleared, chain changed, etc.) — collapse
  // the inline "모델 변경" picker so it doesn't linger open under a different panel next time.
  useEffect(() => {
    if (!showModelSearch) setModelSearchPickerOpen(false)
  }, [showModelSearch])

  function selectSuggestion(pathIds: string[], option: CommandNode) {
    const fullPath = [...pathIds, option.id]
    if (option.submitOnSelect) {
      // 값을 더 안 받는 리프(예: /사용량/클로드) — 첫 세그먼트는 명령어, 나머지는 값으로 이어붙여
      // 자유 텍스트와 같은 경로로 바로 보낸다.
      flashSubmitButton()
      runFreeTextCommand(`/${fullPath[0]} ${fullPath.slice(1).join(' ')}`)
      setValue('')
      return
    }
    if (option.operands) {
      // 값을 받는 명령 — 명령어 텍스트는 칩으로 빠지고 입력창은 값만 받는다.
      setCommandMode({ path: fullPath, operands: [] })
      setValue('')
    } else if (option.id === '모델') {
      setValue(`/${fullPath.join('/')}`)
    } else {
      setValue(`/${fullPath.join('/')} `)
    }
  }

  /**
   * `/네이버 ` 처럼 등록된 명령 뒤에 공백을 치면 명령어를 칩으로 빼고 입력창에는 나머지만 남긴다.
   * 붙여넣기(`/네이버/지도 강남역 맛집`)도 같은 경로로 들어온다. 해당 없으면 null.
   */
  function splitCommandFromText(text: string): { path: string[]; rest: string } | null {
    const match = text.match(/^\/([^\s]+)\s(.*)$/)
    if (!match) return null
    const path = match[1].split('/')
    return findCommand(path)?.operands ? { path, rest: match[2] } : null
  }

  function handleValueChange(next: string) {
    const split = commandMode === null ? splitCommandFromText(next) : null
    if (split) {
      setCommandMode({ path: split.path, operands: [] })
      setValue(split.rest)
      return
    }
    setValue(next)
  }

  /**
   * 모델 확정 — 서비스 목록이 아니라 모델 목록에서 고른 순간에만 부른다.
   * 모델 목록은 트리의 끝이라 여기서 Enter는 "더 들어가기"가 아니라 "고르기 끝"이어야 한다.
   * 단독 `/모델` 피커는 입력창을 비워 스스로 닫고 바로 질문을 칠 수 있는 상태로 돌려준다.
   * (`/모델/검색`의 인라인 피커는 이미 친 질문을 지우면 안 되므로 피커만 접는다.)
   */
  function selectModel(modelId: string) {
    setSelectedModel({ service: modelView as Exclude<ModelView, 'services'>, modelId })
    setModelSearchPickerOpen(false)
    if (showModelPicker) setValue('')
  }

  // 딥링크 명령(/네이버/지도, /네이버/길찾기)은 결과가 앱 밖 새 탭에서 열린다 — 이슈 #6의 방식 1.
  // window.open은 클릭/Enter 같은 사용자 제스처 안에서 호출해야 팝업 차단을 피할 수 있다.
  function openDeepLink(url: string) {
    window.open(url, '_blank', 'noopener,noreferrer')
  }

  /** Enter로 실제 제출이 일어날 때 검색 버튼에 마우스 클릭과 같은 눌림 효과를 준다. */
  function flashSubmitButton() {
    setKeyboardPressed(true)
    window.setTimeout(() => setKeyboardPressed(false), 150)
  }

  // POST /api/v1/requests로 접수되는 즉시 /chat/{taskId}로 이동한다 — 결과는 그 화면이 폴링해서
  // 보여준다(taskResultRenderers.tsx가 SearchBar와 공유). 그래서 여기서는 접수 자체가 실패했을
  // 때(네트워크 오류 등, taskId조차 못 받은 경우)만 인라인으로 알려준다.
  async function runStatusCommand() {
    if (statusTask.phase === 'running') return
    setStatusTask({ phase: 'running', status: 'ANALYZING' })
    try {
      const created = await createTaskRequest('/상태')
      navigate(`/chat/${created.taskId}`)
    } catch (err) {
      setStatusTask({
        phase: 'failed',
        message: err instanceof ApiError ? err.message : '요청을 보내지 못했어요. 잠시 후 다시 시도해주세요.',
      })
    }
  }

  async function runFileSearchCommand(query: string) {
    if (fileSearchTask.phase === 'running') return
    setFileSearchTask({ phase: 'running', status: 'ANALYZING' })
    try {
      const created = await createTaskRequest(`/파일 ${query}`)
      navigate(`/chat/${created.taskId}`)
    } catch (err) {
      setFileSearchTask({
        phase: 'failed',
        message: err instanceof ApiError ? err.message : '요청을 보내지 못했어요. 잠시 후 다시 시도해주세요.',
      })
    }
  }

  /** 명령어를 조립하지 않고 입력창의 문장을 그대로 보낸다 (frontend-api-contract.md "입력창의
   *  한 줄을 그대로 보내세요" — 슬래시 여부는 서버·NLU가 가른다). */
  async function runFreeTextCommand(text: string) {
    if (freeTextTask.phase === 'running') return
    setFreeTextTask({ phase: 'running', status: 'ANALYZING' })
    try {
      const created = await createTaskRequest(text)
      navigate(`/chat/${created.taskId}`)
    } catch (err) {
      setFreeTextTask({
        phase: 'failed',
        message: err instanceof ApiError ? err.message : '요청을 보내지 못했어요. 잠시 후 다시 시도해주세요.',
      })
    }
  }

  /** `/요약`을 이 브라우저에서 직접 처리한다 — 원문이 서버 밖으로 나가지 않는다
   *  (slash-docs#3 "명시적인 브라우저 요약은 원문을 브라우저에 유지한다"). WebGPU가 없으면
   *  이 함수를 아예 부르지 않고 지금까지와 같은 서버 경로(runFreeTextCommand)로 보낸다 —
   *  그쪽은 원래도 서버로 가던 경로라 "조용한 대체"가 아니다.
   *  `@mlc-ai/web-llm`은 여기서 동적으로만 불러온다 — 이 명령을 한 번도 안 쓰는 사용자의
   *  메인 번들에 수 MB짜리 라이브러리가 딸려 들어가지 않게 하기 위함(webgpuSupport.ts 참고).
   *  결과를 다 보여준 뒤 slash-api에 결과만 제출해 작업 이력에 남긴다(원문은 안 보냄,
   *  slash-docs#3 권장 순서 3번). 제출이 성공하면 그 taskId로 /chat으로 옮겨서 다른 명령과
   *  똑같이 히스토리·공유·재생성이 되는 화면을 정본으로 삼는다 — 실패하면(taskId가 없으니)
   *  옮기지 않고 이 자리에 결과를 그대로 둔다(이력 한 줄이 안 남을 뿐, 방금 받은 요약은 그대로다). */
  async function runBrowserSummaryCommand(text: string) {
    if (browserSummaryTask.phase === 'loading' || browserSummaryTask.phase === 'generating') return
    setBrowserSummaryTask({ phase: 'loading', progress: 0, message: '모델을 준비하고 있어요' })
    const startedAt = performance.now()
    try {
      const { summarizeInBrowser } = await import('../lib/webllm')
      const summary = await summarizeInBrowser(text, (progress: SummarizeProgress) => {
        if (progress.phase === 'loading') {
          setBrowserSummaryTask({
            phase: 'loading',
            progress: progress.report.progress,
            message: '모델을 준비하고 있어요',
          })
        } else {
          setBrowserSummaryTask({ phase: 'generating' })
        }
      })
      setBrowserSummaryTask({ phase: 'succeeded', summary })
      submitBrowserSummaryResult({
        inputLength: text.length,
        modelId: WEBLLM_MODEL_ID,
        promptVersion: WEBLLM_PROMPT_VERSION,
        status: 'SUCCEEDED',
        summary,
        durationMs: Math.round(performance.now() - startedAt),
      })
        .then((created) => navigate(`/chat/${created.taskId}`))
        .catch(() => setBrowserSummaryTask({ phase: 'succeeded', summary, historySaveFailed: true }))
    } catch (err) {
      setBrowserSummaryTask({
        phase: 'failed',
        message: isWebLlmSummaryError(err)
          ? err.message
          : '브라우저에서 요약하지 못했어요. 잠시 후 다시 시도해주세요.',
      })
      submitBrowserSummaryResult({
        inputLength: text.length,
        modelId: WEBLLM_MODEL_ID,
        promptVersion: WEBLLM_PROMPT_VERSION,
        status: 'FAILED',
        errorMessage: toWebLlmFailureCode(err),
      }).catch(() => {})
    }
  }

  function submitCommand() {
    if (commandMode && stepped) {
      // 값을 여러 개 받는 명령은 Enter마다 한 값씩 칩으로 확정한다. 마지막 값까지 모이면
      // 명령어(`/네이버/길찾기`)와 값 배열이 그대로 백엔드에 보낼 수 있는 형태로 남는다.
      // TODO(#6): { command, operands } 를 백엔드 길찾기 엔드포인트로 보내고 결과 패널에 렌더한다.
      // 딥링크로 넘기지 않기로 한 이유 — 이름만으로는 네이버가 경로를 계산해주지 않고(좌표 필요,
      // DESIGN.md §9), 결과가 앱 밖으로 나가면 스레드/히스토리에 남지 않는다.
      if (!hasText || operandsFilled) return
      setCommandMode({ ...commandMode, operands: [...commandMode.operands, trimmed] })
      setValue('')
      return
    }
    if (deepLink) {
      flashSubmitButton()
      openDeepLink(deepLink)
      return
    }
    // /요약만 예외 — 이 브라우저가 WebGPU를 쓸 수 있으면 서버로 보내지 않고 여기서 바로 처리한다.
    // 못 쓰면 아래 일반 경로(서버)로 그대로 떨어진다 — 원래도 서버로 가던 경로라 사용자 동의 없이
    // 뭔가를 바꾸는 게 아니다.
    if (isGenericCommand && hasText && commandMode!.path[0] === '요약' && isWebGpuSupported()) {
      flashSubmitButton()
      runBrowserSummaryCommand(trimmed)
      return
    }
    // 딥링크도, /파일 같은 전용 패널도 없는 단일 값 명령(예: /날씨) — 자유 텍스트와 같은 방식으로
    // "/명령어 값" 한 문자열을 그대로 백엔드에 보낸다. commandMode는 isGenericCommand가 참일 때만
    // null이 아니다.
    if (isGenericCommand && hasText) {
      flashSubmitButton()
      runFreeTextCommand(`/${commandMode!.path.join('/')} ${trimmed}`)
    }
  }

  /** Enter가 하는 일을 한 곳에 모아둔다 — keydown과 (조합 확정 시) keyup 양쪽에서 부른다. */
  function runEnterAction() {
    if (modelPickerActive) {
      if (modelView === 'services') {
        setModelView(SERVICES[modelHighlight].id)
        setModelHighlight(0)
      } else {
        selectModel(MODELS_BY_SERVICE[modelView][modelHighlight].id)
      }
      return
    }
    // 검색 폴더는 서버가 자동으로 고르므로 Enter는 접수만 한다 — 진행 중엔 중복 접수를 막는다.
    if (showFileSearch) {
      if (hasText) {
        flashSubmitButton()
        runFileSearchCommand(trimmed)
      }
      return
    }
    if (showStatusCommand) {
      flashSubmitButton()
      runStatusCommand()
      return
    }
    if (commandMode || deepLink) {
      submitCommand()
      return
    }
    if (isFreeText) {
      flashSubmitButton()
      runFreeTextCommand(trimmed)
      return
    }
    if (suggestions) {
      selectSuggestion(suggestions.pathIds, suggestions.options[highlightIndex] ?? suggestions.options[0])
    }
  }

  function handleInputKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // 미뤄둔 Enter는 그 키를 뗄 때까지만 유효하다. 조합을 확정하는 Enter의 keyup은 IME가 삼켜서
    // 아예 오지 않을 수 있는데, 그러면 깃발이 계속 남아 있다가 그다음 Enter의 keyup이 그걸 주워
    // 동작을 한 번 더 실행한다 — keydown에서 한 번, keyup에서 또 한 번. `/모델`에서 서비스로
    // 들어가자마자 그 서비스의 첫 모델이 선택되고 창이 닫히던 증상이 이것이었다.
    pendingEnterRef.current = false

    if (e.key === 'Enter') {
      // Shift+Enter는 항상 줄바꿈 — 우리 쪽 제출/확정 로직을 타지 않고 textarea 기본 동작에 맡긴다.
      if (e.shiftKey) return

      // 한글/일본어/중국어는 마지막 음절이 조합 중인 채로 Enter를 맞는다. 그 Enter로 여기서 바로
      // 상태를 바꾸면 조합 중이던 글자가 중복 입력된다(예전 "검색" 버그). 그렇다고 그냥 버리면
      // 한글 입력은 항상 Enter를 두 번 눌러야 한다.
      // → 같은 키의 keyup으로 미룬다. 그때는 조합이 이미 확정됐고, keyup도 사용자 제스처라
      //   window.open이 팝업 차단에 걸리지도 않는다.
      // (일부 브라우저는 조합을 확정하는 바로 그 keydown에서도 isComposing:false를 보고하므로
      //  ref와 짧은 유예 시간까지 함께 본다.)
      const justFinishedComposing = Date.now() - compositionEndedAtRef.current < 50
      if (e.nativeEvent.isComposing || isComposingRef.current || justFinishedComposing) {
        // 입력창이 textarea로 바뀐 뒤로는(2026-08-19) 여기서도 기본 동작을 막아야 한다 — 안 그러면
        // keyup으로 미루는 사이 Enter의 기본 동작(줄바꿈)이 먼저 실행돼, 조합이 막 끝난 슬래시
        // 명령어 뒤에 줄바꿈이 끼어든다(예: "/날씨" 확정 시 줄바꿈되던 버그).
        e.preventDefault()
        pendingEnterRef.current = true
        return
      }
      e.preventDefault()
      runEnterAction()
      return
    }

    if (modelPickerActive) {
      const list = modelView === 'services' ? SERVICES : MODELS_BY_SERVICE[modelView]
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setModelHighlight((i) => (i + 1) % list.length)
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setModelHighlight((i) => (i - 1 + list.length) % list.length)
      } else if (e.key === 'ArrowRight' && modelView === 'services') {
        // → drills into the highlighted service, same as Enter would at this level.
        e.preventDefault()
        setModelView(SERVICES[modelHighlight].id)
        setModelHighlight(0)
      } else if (e.key === 'ArrowLeft' && modelView !== 'services') {
        // ← backs out to the service list, same as Escape would at this level.
        e.preventDefault()
        setModelView('services')
        setModelHighlight(0)
      } else if (e.key === 'Escape') {
        e.preventDefault()
        if (modelView !== 'services') {
          setModelView('services')
          setModelHighlight(0)
        } else if (modelSearchPickerOpen) {
          // Closing the inline "모델 변경" picker should keep the typed query — only clear
          // the input when Escape is pressed on the standalone /모델 picker.
          setModelSearchPickerOpen(false)
        } else {
          setValue('')
        }
      }
      return
    }

    if (commandMode) {
      if (e.key === 'Escape') {
        // 두 단계로 나눈다 — 긴 검색어를 지우려고 Backspace를 오래 누르고 있을 이유가 없어야 하고,
        // 그렇다고 오타 하나 고치려다 명령어까지 잃어버려서도 안 된다.
        e.preventDefault()
        if (value !== '') setValue('')
        else setCommandMode(null)
      } else if (e.key === 'Backspace' && value === '') {
        // 빈 입력창에서 Backspace = 한 단계씩 되돌린다 (CLI 지우기 감각).
        // 확정한 값 → … → 명령어 텍스트(`/네이버/길찾기`). 값이 없을 때 한 번 더 지우면 명령어 모드를
        // 빠져나가 텍스트로 복원하므로, 되돌리다 막다른 곳에 갇히지 않는다.
        e.preventDefault()
        if (commandMode.operands.length > 0) {
          setCommandMode({ ...commandMode, operands: commandMode.operands.slice(0, -1) })
        } else {
          setCommandMode(null)
          // 공백 없이 복원해야 한다 — 공백이 붙으면 곧바로 다시 명령어 모드로 들어간다.
          setValue(`/${commandMode.path.join('/')}`)
        }
      }
      return
    }

    if (!suggestions) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlightIndex((i) => (i + 1) % suggestions.options.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlightIndex((i) => (i - 1 + suggestions.options.length) % suggestions.options.length)
    } else if (e.key === 'Escape') {
      setValue('')
    }
  }

  /** 조합 확정에 먹힌 Enter를 여기서 이어받는다 — 조합이 끝난 값 기준으로 한 번만 실행된다. */
  function handleInputKeyUp(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== 'Enter' || !pendingEnterRef.current) return
    pendingEnterRef.current = false
    e.preventDefault()
    runEnterAction()
  }

  function removeAttachment(id: string) {
    setAttachments((prev) => {
      const target = prev.find((a) => a.id === id)
      if (target?.url) URL.revokeObjectURL(target.url)
      return prev.filter((a) => a.id !== id)
    })
  }

  function handleAddFiles() {
    setAddMenuOpen(false)
    fileInputRef.current?.click()
  }

  function handleFilesSelected(files: FileList | null) {
    if (!files) return
    const next: Attachment[] = Array.from(files).map((file) => ({
      id: `${file.name}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
      name: file.name,
      url: file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined,
    }))
    setAttachments((prev) => [...prev, ...next])
  }

  function startRecording() {
    const SpeechRecognitionCtor = window.SpeechRecognition ?? window.webkitSpeechRecognition
    if (!SpeechRecognitionCtor || recognitionRef.current) return

    const recognition = new SpeechRecognitionCtor()
    recognition.lang = 'ko-KR'
    recognition.interimResults = true
    recognition.continuous = true
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map((result) => result[0]?.transcript ?? '')
        .join('')
      setValue(transcript)
    }
    recognition.onerror = () => setIsRecording(false)
    recognition.onend = () => {
      setIsRecording(false)
      recognitionRef.current = null
    }

    recognitionRef.current = recognition
    recognition.start()
    setIsRecording(true)
  }

  function stopRecording() {
    recognitionRef.current?.stop()
  }

  async function handleCaptureScreenshot() {
    setAddMenuOpen(false)
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: true })
      const video = document.createElement('video')
      video.srcObject = stream
      await video.play()
      const canvas = document.createElement('canvas')
      canvas.width = video.videoWidth
      canvas.height = video.videoHeight
      canvas.getContext('2d')?.drawImage(video, 0, 0)
      stream.getTracks().forEach((track) => track.stop())
      setAttachments((prev) => [
        ...prev,
        { id: `screenshot-${Date.now()}`, name: '스크린샷', url: canvas.toDataURL('image/png') },
      ])
    } catch {
      // user cancelled the picker or denied permission — no-op
    }
  }

  return (
    <div className="relative w-full">
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept="image/*,.pdf,.doc,.docx,.txt"
        className="hidden"
        onChange={(e) => {
          handleFilesSelected(e.target.files)
          e.target.value = ''
        }}
      />
      {/* 1.5px padding + conditional gradient bg = a gradient ring on focus, a plain hairline ring otherwise.
          Shape grows from a full pill to a rounded rectangle when attachments are present, so previews
          live inside the same bordered container instead of floating above it. */}
      <div
        className={`w-full ${shape} p-[1.5px] transition-[background] duration-200 ${
          active ? 'brand-gradient' : 'bg-hairline'
        }`}
      >
        <div className={`flex w-full flex-col ${shape} bg-surface`}>
          {hasAttachments && (
            <div className="flex flex-wrap gap-2 px-4 pb-1 pt-3.5">
              {attachments.map((a) => (
                <div
                  key={a.id}
                  className="relative h-16 w-16 shrink-0 overflow-hidden rounded-lg border border-hairline"
                >
                  {a.url ? (
                    <img src={a.url} alt={a.name} className="h-full w-full object-cover" />
                  ) : (
                    <div className="flex h-full w-full flex-col items-center justify-center gap-1 bg-surface-raised p-1">
                      <FileText size={18} className="text-muted" />
                      <span className="w-full truncate text-center text-2xs text-muted">{a.name}</span>
                    </div>
                  )}
                  <button
                    type="button"
                    title="제거"
                    aria-label={`${a.name} 제거`}
                    onClick={() => removeAttachment(a.id)}
                    className="absolute right-1 top-1 flex h-4 w-4 items-center justify-center rounded-full bg-black/60 text-white"
                  >
                    <X size={10} />
                  </button>
                </div>
              ))}
            </div>
          )}
          {/* 두 줄로 나눈다(2026-08-20) — Shift+Enter로 줄바꿈해 내용이 길어져도 아래 툴바(마이크·
              제출·+ 버튼)는 항상 같은 높이로 고정되고, 늘어나는 건 위 textarea뿐이어야 한다.
              하나의 행에서 items-end로 정렬하던 예전 구조는 textarea가 커질 때 툴바 버튼들이
              바닥에 붙은 채로 같이 아래로 밀려 내려가 버렸다(Claude Code 스타일 참고). */}
          <div className="flex w-full flex-col gap-1.5 px-4 py-3.5">
            <div className="flex w-full items-start gap-3">
              {commandMode && (
                <div className="flex shrink-0 flex-wrap items-center gap-1.5 pt-1">
                  <span className="rounded-full bg-accent-blue/12 px-2.5 py-1 text-xs font-medium text-accent-blue">
                    {commandMode.path.join('/')}
                  </span>
                  {commandMode.operands.map((operand, i) => (
                    <OperandChip
                      key={`${operandNames[i]}-${operand}`}
                      label={`${operandNames[i]} ${operand}`}
                      // 앞의 값을 지우면 그 뒤에 받은 값들도 함께 빠진다 — 순서가 곧 의미이므로
                      // 중간만 비어 있는 상태를 만들지 않는다.
                      onClear={() => {
                        setCommandMode({ ...commandMode, operands: commandMode.operands.slice(0, i) })
                        textInputRef.current?.focus()
                      }}
                    />
                  ))}
                </div>
              )}
              <textarea
                ref={textInputRef}
                value={value}
                rows={1}
                onChange={(e) => handleValueChange(e.target.value)}
                onKeyDown={handleInputKeyDown}
                onKeyUp={handleInputKeyUp}
                onCompositionStart={() => {
                  isComposingRef.current = true
                }}
                onCompositionEnd={() => {
                  isComposingRef.current = false
                  compositionEndedAtRef.current = Date.now()
                }}
                onFocus={() => setFocused(true)}
                onBlur={() => setFocused(false)}
                placeholder={
                  isRecording
                    ? '듣고 있어요...'
                    : commandMode
                      ? nextOperandName
                        ? `${nextOperandName} 입력`
                        : ''
                      : "무엇이든 물어보세요 · '/'로 명령어도 가능해요"
                }
                className="min-w-0 flex-1 resize-none overflow-y-auto bg-transparent py-1 text-control font-medium leading-6 text-foreground placeholder:text-muted focus:outline-none"
              />
            </div>
            <div className="flex w-full items-center gap-3">
              {/* 아이들·모드 표시용 "/" — 클로드 컴포저의 모드 토글 자리와 같은 위치(하단 좌측)로
                  옮겼다(2026-08-20). 콘텐츠(경로 칩·값)가 아니라 크롬이라 늘어나는 위 줄이 아니라
                  높이가 고정된 이 줄에 속해야 위 칸에 혼자 붕 떠 보이지 않는다. */}
              <span
                className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-sm font-semibold transition-colors ${
                  isCommand ? 'bg-accent-blue text-white' : 'bg-foreground/8 text-foreground'
                }`}
              >
                /
              </span>
              <div className="group relative ml-auto flex shrink-0 items-center">
                <Tooltip label="마이크 설정">
                  <button
                    type="button"
                    aria-label="마이크 설정"
                    onClick={() => setMicSettingsOpen((o) => !o)}
                    className="flex h-6 w-4 items-center justify-center text-muted opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100"
                  >
                    <ChevronDown size={14} />
                  </button>
                </Tooltip>
                <Tooltip label={holdToRecord ? '길게 눌러 녹음' : '클릭해서 녹음'}>
                  <button
                    type="button"
                    aria-label="음성 입력"
                    onMouseDown={holdToRecord ? startRecording : undefined}
                    onMouseUp={holdToRecord ? stopRecording : undefined}
                    onMouseLeave={holdToRecord ? () => isRecording && stopRecording() : undefined}
                    onTouchStart={holdToRecord ? startRecording : undefined}
                    onTouchEnd={holdToRecord ? stopRecording : undefined}
                    onClick={!holdToRecord ? () => (isRecording ? stopRecording() : startRecording()) : undefined}
                    className={`shrink-0 transition-colors ${
                      isRecording ? 'animate-pulse text-accent-blue' : 'text-muted hover:text-foreground'
                    }`}
                  >
                    <Mic size={18} />
                  </button>
                </Tooltip>
                {micSettingsOpen && (
                  <MicSettingsPopover
                    selectedDeviceId={selectedMicId}
                    onSelectDevice={setSelectedMicId}
                    holdToRecord={holdToRecord}
                    onHoldToRecordChange={setHoldToRecord}
                    onClose={() => setMicSettingsOpen(false)}
                  />
                )}
              </div>
              {hasText ? (
                <Tooltip label="검색하기">
                  <button
                    type="button"
                    aria-label="검색"
                    onClick={submitCommand}
                    className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-all duration-100 hover:brightness-110 active:scale-90 ${
                      keyboardPressed ? 'scale-90 brightness-110' : 'scale-100'
                    } ${isCommand ? 'bg-accent-blue text-white' : 'bg-foreground/12 text-foreground'}`}
                  >
                    <ArrowUp size={16} />
                  </button>
                </Tooltip>
              ) : (
                <Tooltip label="음성 모드">
                  <button
                    type="button"
                    aria-label="음성 모드"
                    onClick={() => alert('준비 중입니다.')}
                    className="shrink-0 text-muted transition-colors hover:text-foreground"
                  >
                    <AudioLines size={18} />
                  </button>
                </Tooltip>
              )}
              <div className="relative shrink-0">
                <Tooltip label="추가">
                  <button
                    type="button"
                    aria-label="추가"
                    onClick={() => setAddMenuOpen((o) => !o)}
                    className={`flex h-7 w-7 items-center justify-center rounded-lg transition-colors ${
                      addMenuOpen ? 'bg-foreground/12 text-foreground' : 'text-muted hover:text-foreground'
                    }`}
                  >
                    <Plus size={18} />
                  </button>
                </Tooltip>

                {addMenuOpen && (
                  <>
                    <div className="fixed inset-0 z-40" onClick={() => setAddMenuOpen(false)} />
                    <div className="absolute right-0 top-full z-50 mt-2 w-60 overflow-hidden rounded-xl border border-hairline bg-surface-raised py-1.5 text-left shadow-2xl">
                      <AddMenuItem icon={Paperclip} label="파일 또는 사진 추가" onClick={handleAddFiles} />
                      <AddMenuItem icon={Camera} label="스크린샷 캡처하기" onClick={handleCaptureScreenshot} />
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Absolutely positioned so none of this participates in the page's flow layout — it was
          pushing/pulling everything below (including this very search bar, since the whole hero
          block is vertically centered) every time a panel appeared, disappeared, or resized.
          Also hidden entirely while recording, since the live interim transcript changes on every
          syllable and would otherwise flicker panels in and out even with the overlay fix. */}
      {!isRecording && (
        <div className="absolute inset-x-0 top-full z-30 mt-2">
      {showSuggestions && (
        <div className="overflow-hidden rounded-xl border border-hairline bg-surface text-left">
          {suggestions!.options.map((opt, i) => (
            <button
              key={opt.id}
              type="button"
              onClick={() => selectSuggestion(suggestions!.pathIds, opt)}
              className={`flex w-full items-center justify-between gap-3 px-4 py-2 text-left text-sm transition-colors ${
                i === highlightIndex ? 'bg-foreground/8' : 'hover:bg-foreground/6'
              }`}
            >
              <span className="text-foreground">/{[...suggestions!.pathIds, opt.id].join('/')}</span>
              <span className="shrink-0 truncate text-xs text-muted">{opt.description}</span>
            </button>
          ))}
        </div>
      )}

      {showModelPicker && (
        <ModelPickerPanel
          view={modelView}
          highlightIndex={modelHighlight}
          selected={selectedModel}
          onHighlightChange={setModelHighlight}
          onSelectService={(id) => {
            setModelView(id)
            setModelHighlight(0)
          }}
          onSelectModel={selectModel}
          onBack={() => {
            setModelView('services')
            setModelHighlight(0)
          }}
        />
      )}

      {showModelSearch &&
        (modelSearchPickerOpen ? (
          <ModelPickerPanel
            view={modelView}
            highlightIndex={modelHighlight}
            selected={selectedModel}
            onHighlightChange={setModelHighlight}
            onSelectService={(id) => {
              setModelView(id)
              setModelHighlight(0)
            }}
            onSelectModel={selectModel}
            onBack={() => {
              setModelView('services')
              setModelHighlight(0)
            }}
          />
        ) : (
          <div className="overflow-hidden rounded-xl border border-hairline bg-surface text-left">
            <div className="flex items-center justify-between gap-3 px-4 py-3">
              <div className="flex items-center gap-2 text-sm text-foreground">
                <ServiceIcon icon={SERVICES.find((s) => s.id === selectedModel.service)?.icon ?? null} />
                <span>{modelDestination}로 물어볼게요</span>
              </div>
              <button
                type="button"
                onClick={() => {
                  setModelView(selectedModel.service)
                  setModelHighlight(
                    Math.max(
                      0,
                      MODELS_BY_SERVICE[selectedModel.service].findIndex((m) => m.id === selectedModel.modelId),
                    ),
                  )
                  setModelSearchPickerOpen(true)
                }}
                className="shrink-0 rounded-lg bg-foreground/10 px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-foreground/15"
              >
                모델 변경
              </button>
            </div>
            <p className="border-t border-hairline px-4 py-2 text-xs text-muted">
              "{commandChain!.query}" 질문 준비 완료 — 실제 API 연동 전, mock이에요.
            </p>
          </div>
        ))}

      {showFileSearch && (
        <div className="overflow-hidden rounded-xl border border-hairline bg-surface text-left">
          {fileSearchTask.phase === 'idle' ? (
            <p className="px-4 py-3 text-sm text-muted">Enter를 누르면 등록된 PC에서 찾아요.</p>
          ) : fileSearchTask.phase === 'running' ? (
            <LoadingIndicator
              className="px-4 py-3"
              label={TASK_STATUS_LABELS[fileSearchTask.status] ?? '검색하는 중이에요'}
            />
          ) : (
            <p className="px-4 py-3 text-sm text-accent-blue">{fileSearchTask.message}</p>
          )}
        </div>
      )}

      {showStatusCommand && (
        <div className="overflow-hidden rounded-xl border border-hairline bg-surface p-4 text-left">
          {statusTask.phase === 'idle' && <p className="text-sm text-muted">Enter를 누르면 이 PC의 상태를 확인해요.</p>}
          {statusTask.phase === 'running' && (
            <LoadingIndicator label={TASK_STATUS_LABELS[statusTask.status] ?? '처리하는 중이에요'} />
          )}
          {statusTask.phase === 'failed' && <p className="text-sm text-accent-blue">{statusTask.message}</p>}
        </div>
      )}

      {(isFreeText || isGenericCommand) && freeTextTask.phase !== 'idle' && (
        <div className="overflow-hidden rounded-xl border border-hairline bg-surface p-4 text-left">
          {freeTextTask.phase === 'running' && (
            <LoadingIndicator label={TASK_STATUS_LABELS[freeTextTask.status] ?? '처리하는 중이에요'} />
          )}
          {freeTextTask.phase === 'failed' && <p className="text-sm text-accent-blue">{freeTextTask.message}</p>}
        </div>
      )}

      {/* /요약을 이 브라우저에서 처리하는 동안·끝난 뒤의 표시 — TextSummaryResultCard
          (taskResultRenderers.tsx)와 같은 문단·캡션 배치를 그대로 따른다(새 시각 패턴을 만들지
          않음, DESIGN.md §14). 이력 제출까지 성공하면 곧바로 /chat으로 옮겨가므로 이 succeeded
          블록은 보통 잠깐만 보인다 — 이력 제출이 실패했을 때만(historySaveFailed) 여기 남는다. */}
      {browserSummaryTask.phase !== 'idle' && (
        <div className="overflow-hidden rounded-xl border border-hairline bg-surface p-4 text-left">
          {browserSummaryTask.phase === 'loading' && (
            <LoadingIndicator
              label={`${browserSummaryTask.message} (${Math.round(browserSummaryTask.progress * 100)}%)`}
            />
          )}
          {browserSummaryTask.phase === 'generating' && <LoadingIndicator label="요약을 만들고 있어요" />}
          {browserSummaryTask.phase === 'succeeded' && (
            <div className="flex flex-col gap-2">
              <p data-clarity-mask="true" className="whitespace-pre-wrap text-sm text-foreground">
                {browserSummaryTask.summary}
              </p>
              <p className="text-xs text-muted">이 브라우저에서 직접 요약했어요 · 원문이 서버로 전송되지 않았어요.</p>
              {browserSummaryTask.historySaveFailed && (
                <p className="text-xs text-accent-blue">이력에는 남기지 못했어요 — 방금 받은 요약은 그대로예요.</p>
              )}
            </div>
          )}
          {browserSummaryTask.phase === 'failed' && (
            <p className="text-sm text-accent-blue">{browserSummaryTask.message}</p>
          )}
        </div>
      )}

      {showPlaceholderMsg && <p className="pl-4 text-left text-xs text-muted">{placeholderMsg}</p>}

      {showDeepLinkHint && <p className="pl-4 text-left text-xs text-accent-blue">{deepLinkHintText}</p>}

      {showCommandModeHint && <p className="pl-4 text-left text-xs text-accent-blue">{commandModeHint}</p>}

      {showWebGpuUnsupportedHint && (
        <p className="pl-4 text-left text-xs text-accent-blue">
          이 브라우저는 WebLLM을 지원하지 않아 서버에서 요약해요.
        </p>
      )}

      {/* 자유 입력은 `/모델`에서 고른 모델로 간다 — 그 선택이 실제로 어디에 쓰이는지 보이는 유일한
          자리이므로, 모델 이름을 고정 문구("로컬 LLM") 대신 여기에 그대로 적는다. 조사는 사용자가
          친 문장과 모델 이름 둘 다 뒤에 붙으므로 '이(가)'와 같은 병기 형태로 둔다 — 모델 이름이
          'o3', 'Gemini 3 Flash'처럼 받침 여부가 제각각이라 하나로 정할 수 없다.
          자유 입력은 로컬 에이전트를 거쳐 백엔드로 가므로, 에이전트가 꺼져있으면 보낼 곳 자체가
          없다는 걸 여기서 바로 알려준다 (§ Settings > 연동 > 지정 PC 관리). */}
      {isFreeText &&
        freeTextTask.phase === 'idle' &&
        (agentStatus === 'offline' ? (
          <p className="pl-4 text-left text-xs text-accent-blue">
            로컬 에이전트가 꺼져있어서 요청을 보낼 수 없어요 ·{' '}
            <button
              type="button"
              onClick={() => navigate({ pathname: location.pathname, hash: '#settings/plugins' })}
              className="underline underline-offset-2 hover:brightness-110"
            >
              PC 관리에서 확인하기
            </button>
          </p>
        ) : (
          <p className="pl-4 text-left text-xs text-muted">
            '{trimmed}'이(가) {modelDestination}에 요청됩니다.
          </p>
        ))}
        </div>
      )}
    </div>
  )
}
