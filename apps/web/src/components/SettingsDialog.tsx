import { useEffect, useMemo, useState } from 'react'
import { X, Monitor, Sun, Moon, ChevronDown, Plus, Pencil, Download, Info, Loader2 } from 'lucide-react'
import type { Theme } from '../hooks/useTheme'
import type { FontSize } from '../hooks/useFontSize'
import { useAgentStatus } from '../hooks/agentStatusContext'
import { getClientInfo } from '../lib/clientInfo'
import { SETTINGS_CATEGORIES as CATEGORIES, type SettingsCategoryId } from '../lib/settingsCategory'
import { Tooltip } from './Tooltip'
import { createPairingRequest, getPairingStatus, type PairingRequest } from '../lib/pairing'
import { listDevices, revokeDevice, setTaskIntake, type DeviceStatus } from '../lib/devices'
import { ApiError } from '../lib/apiClient'

const APPEARANCE_OPTIONS: { id: Theme; icon: typeof Monitor; label: string }[] = [
  { id: 'system', icon: Monitor, label: '시스템' },
  { id: 'light', icon: Sun, label: '라이트' },
  { id: 'dark', icon: Moon, label: '다크' },
]

// 모양은 아이콘만으로 뜻이 통하지만 크기는 그렇지 않아 글자 라벨을 쓴다. 라벨 자체도 함께
// 커지므로 고른 결과가 그 자리에서 바로 보인다.
const FONT_SIZE_OPTIONS: { id: FontSize; label: string }[] = [
  { id: 'normal', label: '보통' },
  { id: 'large', label: '크게' },
  { id: 'x-large', label: '매우 크게' },
]

const CLIENT_INFO_ROWS: { key: keyof ReturnType<typeof getClientInfo>; label: string }[] = [
  { key: 'timeZone', label: '타임존' },
  { key: 'os', label: '운영체제' },
  { key: 'browser', label: '브라우저' },
  { key: 'language', label: '언어' },
  { key: 'resolution', label: '화면 해상도' },
]

// 브라우저가 스스로 아는 값을 참고용으로 보여주는 자리. 표시 전용이라 여기서 값을 바꿀 방법은 없다 —
// 실제 동작을 이 값에 따라 바꿔야 한다면 백엔드가 요청 헤더로 별도 판단해야 한다 (src/lib/clientInfo.ts).
function ClientInfo() {
  const info = useMemo(() => getClientInfo(), [])

  return (
    <>
      <h3 className="mb-1 text-sm font-semibold">이 기기</h3>
      <p className="mb-3 text-xs text-muted">브라우저가 알려주는 값이에요 — 참고용으로만 보여드려요.</p>
      <div className="flex flex-col">
        {CLIENT_INFO_ROWS.map(({ key, label }) => (
          <div key={key} className="flex items-center justify-between border-b border-hairline py-2 last:border-b-0">
            <span className="text-sm text-muted">{label}</span>
            <span className="text-sm text-foreground">{info[key]}</span>
          </div>
        ))}
      </div>
    </>
  )
}

const MAX_DEVICES = 5

interface RegisteredDevice {
  id: string
  name: string
  registeredAt: string
  isThisDevice?: boolean
  // GET /api/v1/devices가 돌려주는 값 — 서버가 하트비트로 판정한 실제 연결 상태다. 이 PC가
  // 아닌 기기는 다른 물리적 기기의 localhost라 브라우저가 직접 확인할 방법이 없으므로, 그
  // 기기들은 이 값을 그대로 믿는다("이 PC" 자신은 실시간 useAgentStatus()를 우선한다).
  status?: DeviceStatus
  /** 해제(DELETE) 요청의 If-Match에 그대로 넣는다 — lib/devices.ts의 Device.version 참고. */
  version: number
  acceptingTasks: boolean
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')}`
}

type PairingPanelState =
  | { phase: 'idle' }
  | { phase: 'issuing' }
  | { phase: 'active'; request: PairingRequest; remainingSeconds: number }
  | { phase: 'expired'; request: PairingRequest }
  | { phase: 'error'; message: string }

const PAIRING_POLL_INTERVAL_MS = 2500

function remainingSecondsFrom(expiresAt: string): number {
  return Math.max(0, Math.round((new Date(expiresAt).getTime() - Date.now()) / 1000))
}

function formatCountdown(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60)
  const s = totalSeconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

// 지정 PC 관리. 브라우저 요청을 실제로 받아 백엔드에 대신 요청하는 로컬 에이전트가 이 PC에
// 설치·실행 중인지 확인하고, 이 계정으로 접속 가능한 PC 목록을 관리하는 자리.
//
// 등록 흐름(frontend-api-contract.md "PC 등록 화면(W1-02)"): 코드 발급 → 6자리 표시 + 5분 카운트다운
// → 2~3초 간격 폴링 → CLAIMED 되면 등록 완료. pairingCode는 발급 응답에서 딱 한 번만 오므로
// 화면을 벗어나면 재발급해야 한다 — 그래서 코드가 없으면 폴링 자체를 멈춘다.
function PcManagement() {
  const agentStatus = useAgentStatus()
  const [devices, setDevices] = useState<RegisteredDevice[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [pairing, setPairing] = useState<PairingPanelState>({ phase: 'idle' })
  const [removingId, setRemovingId] = useState<string | null>(null)
  const [removeError, setRemoveError] = useState<string | null>(null)
  const [updatingIntakeId, setUpdatingIntakeId] = useState<string | null>(null)
  const [intakeError, setIntakeError] = useState<string | null>(null)

  // 화면을 열 때 부른다(계약서 "지정 PC 관리 화면" 절) — 다른 탭에서 등록한 PC도 여기서 같이
  // 보여야 하므로 세션 로컬 상태로 들고 있지 않는다.
  const refreshDevices = async () => {
    try {
      const { devices: fetched } = await listDevices()
      setDevices(
        fetched.map((d) => ({
          id: d.deviceId,
          name: d.name,
          registeredAt: formatDate(d.registeredAt),
          status: d.status,
          version: d.version,
          acceptingTasks: d.acceptingTasks,
        })),
      )
      setLoadError(null)
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : '기기 목록을 불러오지 못했어요.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refreshDevices()
  }, [])

  // 되돌릴 수 없는 요청이라(#26) 확인을 먼저 받고, 성공하면 로컬 state를 임의로 지우는 대신
  // refreshDevices()로 서버 목록을 다시 받는다 — 그 사이 다른 탭에서 바뀐 것까지 반영된다.
  const removeDevice = async (device: RegisteredDevice) => {
    if (removingId) return
    if (!window.confirm(`${device.name} 등록을 해제할까요? 이 PC에서는 다시 등록하기 전까지 접속할 수 없어요.`)) {
      return
    }
    setRemovingId(device.id)
    setRemoveError(null)
    try {
      await revokeDevice(device.id, device.version)
      await refreshDevices()
    } catch (err) {
      setRemoveError(err instanceof ApiError ? err.message : '기기를 해제하지 못했어요. 잠시 후 다시 시도해주세요.')
    } finally {
      setRemovingId(null)
    }
  }

  // 응답에 바뀐 기기 전체(새 version 포함)가 들어있어 refreshDevices() 없이 그 자리에서
  // state를 갱신한다 — 해제와 달리 되돌릴 수 있는 조작이라 확인창은 없다.
  const toggleTaskIntake = async (device: RegisteredDevice) => {
    if (updatingIntakeId) return
    setUpdatingIntakeId(device.id)
    setIntakeError(null)
    try {
      const updated = await setTaskIntake(device.id, !device.acceptingTasks, device.version)
      setDevices((prev) =>
        prev.map((d) =>
          d.id === device.id ? { ...d, acceptingTasks: updated.acceptingTasks, version: updated.version } : d,
        ),
      )
    } catch (err) {
      setIntakeError(err instanceof ApiError ? err.message : '설정을 바꾸지 못했어요. 잠시 후 다시 시도해주세요.')
    } finally {
      setUpdatingIntakeId(null)
    }
  }

  const renameDevice = (id: string, name: string) =>
    setDevices((prev) => prev.map((d) => (d.id === id ? { ...d, name: name.trim() || d.name } : d)))

  const issuePairingCode = async () => {
    setPairing({ phase: 'issuing' })
    try {
      const request = await createPairingRequest()
      setPairing({ phase: 'active', request, remainingSeconds: remainingSecondsFrom(request.expiresAt) })
    } catch (err) {
      setPairing({
        phase: 'error',
        message: err instanceof ApiError ? err.message : '코드를 발급받지 못했어요. 잠시 후 다시 시도해주세요.',
      })
    }
  }

  // 카운트다운 — 1초마다 만료까지 남은 시간을 다시 계산한다. 0이 되면 폴링을 멈추고 "코드 다시
  // 받기" 상태로 넘어간다 (서버 응답을 기다리지 않고 클라이언트 시계 기준으로 즉시 반영).
  useEffect(() => {
    if (pairing.phase !== 'active') return
    const id = setInterval(() => {
      setPairing((prev) => {
        if (prev.phase !== 'active') return prev
        const remainingSeconds = remainingSecondsFrom(prev.request.expiresAt)
        if (remainingSeconds <= 0) return { phase: 'expired', request: prev.request }
        return { ...prev, remainingSeconds }
      })
    }, 1000)
    return () => clearInterval(id)
  }, [pairing.phase])

  // 등록 진행 상태 폴링 — CLAIMED로 바뀌면 기기 목록에 실제 deviceId로 추가하고 패널을 닫는다.
  // pairingRequestId만 의존성에 넣는다 — pairing 객체 전체를 넣으면 카운트다운이 1초마다 바꾸는
  // remainingSeconds 때문에 매초 인터벌이 재생성돼 2.5초 폴링이 한 번도 못 나간다.
  const activePairingRequestId = pairing.phase === 'active' ? pairing.request.pairingRequestId : null
  useEffect(() => {
    if (!activePairingRequestId) return
    const pairingRequestId = activePairingRequestId
    let cancelled = false

    const poll = async () => {
      try {
        const status = await getPairingStatus(pairingRequestId)
        if (cancelled || status.status !== 'CLAIMED') return
        await refreshDevices()
        setPairing({ phase: 'idle' })
      } catch {
        // 폴링 중 일시적 네트워크 오류는 다음 주기에 다시 시도한다 — 카운트다운이 만료를 대신 처리한다.
      }
    }

    const id = setInterval(poll, PAIRING_POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [activePairingRequestId])

  return (
    <>
      <div className="mb-1 flex items-center justify-between gap-3 pr-8">
        <h2 className="flex items-center gap-1.5 text-lg font-semibold">
          지정 PC 관리
          <Tooltip label="이 계정으로 접속할 수 있는 PC를 등록하고 관리해요.">
            <Info size={14} className="text-muted" />
          </Tooltip>
        </h2>
        <button
          type="button"
          onClick={issuePairingCode}
          disabled={devices.length >= MAX_DEVICES || pairing.phase === 'issuing' || pairing.phase === 'active'}
          className="flex shrink-0 items-center gap-1.5 rounded-lg bg-foreground/10 px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-foreground/15 disabled:pointer-events-none disabled:opacity-40"
        >
          {pairing.phase === 'issuing' ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
          PC 기기 등록
        </button>
      </div>
      <p className="mb-4 text-xs text-muted">
        등록된 PC 기기 현황과, 이 PC의 로컬 에이전트가 정상 동작 중인지 확인할 수 있어요.
      </p>

      {(pairing.phase === 'active' || pairing.phase === 'expired' || pairing.phase === 'error') && (
        <div className="mb-4 rounded-xl border border-hairline p-4 text-center">
          {pairing.phase === 'error' ? (
            <>
              <p className="mb-3 text-sm text-muted">{pairing.message}</p>
              <button
                type="button"
                onClick={issuePairingCode}
                className="text-xs font-medium text-accent-blue transition-colors hover:brightness-110"
              >
                다시 시도
              </button>
            </>
          ) : (
            <>
              <p className="mb-2 text-xs text-muted">
                이 코드를 등록할 PC의 에이전트에 입력하세요
              </p>
              <p className="mb-2 text-3xl font-bold tracking-[0.2em] text-foreground">
                {pairing.request.pairingCode}
              </p>
              {pairing.phase === 'active' ? (
                <p className="mb-3 flex items-center justify-center gap-1.5 text-xs text-muted">
                  <Loader2 size={12} className="animate-spin" />
                  등록 대기 중 · {formatCountdown(pairing.remainingSeconds)} 후 만료
                </p>
              ) : (
                <p className="mb-3 text-xs text-muted">코드가 만료됐어요.</p>
              )}
              <div className="flex items-center justify-center gap-3">
                <button
                  type="button"
                  onClick={issuePairingCode}
                  className="text-xs font-medium text-accent-blue transition-colors hover:brightness-110"
                >
                  코드 다시 받기
                </button>
                {pairing.phase === 'active' && (
                  <button
                    type="button"
                    onClick={() => setPairing({ phase: 'idle' })}
                    className="text-xs font-medium text-muted transition-colors hover:text-foreground"
                  >
                    취소
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      )}

      <div className="rounded-xl border border-hairline p-4">
        {loading ? (
          <p className="text-sm text-muted">불러오는 중...</p>
        ) : loadError ? (
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-muted">{loadError}</p>
            <button
              type="button"
              onClick={refreshDevices}
              className="shrink-0 text-xs font-medium text-accent-blue transition-colors hover:brightness-110"
            >
              다시 시도
            </button>
          </div>
        ) : (
        <>
        <p className="mb-3 text-sm font-semibold">
          등록현황 {devices.length}/{MAX_DEVICES}
        </p>

        {removeError && <p className="mb-3 text-xs text-accent-blue">{removeError}</p>}
        {intakeError && <p className="mb-3 text-xs text-accent-blue">{intakeError}</p>}

        <div className="flex flex-col gap-1.5">
          {devices.map((d) => {
            const isOnline = d.isThisDevice ? agentStatus === 'online' : d.status !== undefined && d.status !== 'OFFLINE'
            const statusKnown = d.isThisDevice || d.status !== undefined

            return (
            <div key={d.id} className="flex items-center gap-2.5 rounded-lg border border-hairline px-3 py-2">
              <Tooltip
                label={
                  !statusKnown
                    ? '다른 기기 — 이 브라우저에서는 상태를 알 수 없어요'
                    : isOnline
                      ? '로컬 에이전트 정상 동작 중'
                      : '로컬 에이전트가 꺼져있어요'
                }
              >
                <span
                  className={`h-2 w-2 shrink-0 rounded-full ${
                    !statusKnown ? 'bg-muted/30' : isOnline ? 'bg-accent-green' : 'bg-muted'
                  }`}
                />
              </Tooltip>

              <div className="min-w-0 flex-1">
                {renamingId === d.id ? (
                  <input
                    autoFocus
                    defaultValue={d.name}
                    onBlur={(e) => {
                      renameDevice(d.id, e.target.value)
                      setRenamingId(null)
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') e.currentTarget.blur()
                      if (e.key === 'Escape') setRenamingId(null)
                    }}
                    className="w-full rounded-[6px] border border-hairline bg-canvas px-1.5 py-0.5 text-sm text-foreground focus:outline-none"
                  />
                ) : (
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-sm font-medium text-foreground">{d.name}</span>
                    {d.isThisDevice && (
                      <span className="shrink-0 rounded-[4px] bg-foreground/8 px-1.5 py-0.5 text-2xs text-muted">
                        이 PC
                      </span>
                    )}
                    <button
                      type="button"
                      aria-label={`${d.name} 이름 변경`}
                      onClick={() => setRenamingId(d.id)}
                      className="shrink-0 text-muted transition-colors hover:text-foreground"
                    >
                      <Pencil size={12} />
                    </button>
                  </div>
                )}
                <p className="text-2xs text-muted">
                  {d.registeredAt}
                  {statusKnown &&
                    ` · 에이전트 ${!isOnline ? '꺼져있음' : d.acceptingTasks ? '정상 동작 중' : '작업 수신 꺼짐'}`}
                </p>
              </div>

              <Tooltip label={d.acceptingTasks ? '새 작업을 받고 있어요 — 눌러서 끄기' : '새 작업을 받지 않아요 — 눌러서 켜기'}>
                <button
                  type="button"
                  role="switch"
                  aria-checked={d.acceptingTasks}
                  aria-label={`${d.name} 작업 수신 ${d.acceptingTasks ? '끄기' : '켜기'}`}
                  onClick={() => toggleTaskIntake(d)}
                  disabled={updatingIntakeId === d.id}
                  className={`relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-40 ${
                    d.acceptingTasks ? 'bg-accent-blue' : 'bg-foreground/20'
                  }`}
                >
                  <span
                    className={`absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                      d.acceptingTasks ? 'translate-x-4' : 'translate-x-0'
                    }`}
                  />
                </button>
              </Tooltip>

              <button
                type="button"
                aria-label={`${d.name} 삭제`}
                onClick={() => removeDevice(d)}
                disabled={removingId === d.id}
                className="shrink-0 text-muted transition-colors hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
              >
                {removingId === d.id ? <Loader2 size={14} className="animate-spin" /> : <X size={14} />}
              </button>
            </div>
            )
          })}
        </div>
        </>
        )}
      </div>

      {/* slash-agent에 아직 실제 배포판이 없어서, 지금은 릴리스가 올라올 실제 장소로 보낸다 —
          클릭해도 아무 일도 안 일어나는 죽은 버튼보다, 어디로 가는지 정직한 링크가 낫다. */}
      <a
        href="https://github.com/LikeLionTeam4/slash-agent/releases"
        target="_blank"
        rel="noreferrer"
        className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-muted transition-colors hover:text-foreground"
      >
        <Download size={13} />
        에이전트 다운로드
      </a>

      <ul className="mt-3 list-disc space-y-1 pl-4 text-xs text-muted">
        <li>PC는 최대 {MAX_DEVICES}대까지 등록할 수 있어요.</li>
        <li>등록되지 않은 PC에서는 접속이 제한돼요.</li>
        <li>이 브라우저가 설치된 PC(이 PC)만 로컬 에이전트 상태를 실시간으로 확인할 수 있어요 — 다른 PC의 상태는 참고용으로만 보여드려요.</li>
      </ul>
    </>
  )
}

/**
 * `/파일` 검색 대상 폴더 안내. 폴더는 이 화면(웹)이 아니라 PC에 설치한 로컬 에이전트 앱에서
 * 관리한다(에이전트의 트레이 아이콘 → 색인 폴더 관리 창) — 그 창을 여기서 원격으로 열게
 * 하려면 slash-api/slash-agent 쪽에 새 메시지 타입이 필요해서(WSS로 이미 연결된 채널 재사용)
 * 이번 PR 범위(웹 단독 변경) 밖이다. "지정 PC 관리" 탭도 페어링 상태만 보여줄 뿐 폴더는 없어서
 * 그리로 보내는 버튼은 만들지 않는다 — 실제로 폴더를 관리할 수 있는 곳(에이전트 트레이 아이콘)만
 * 문장으로 안내한다.
 */
function SearchFolders() {
  return (
    <>
      <h3 className="mb-1 text-sm font-semibold">파일 검색 폴더</h3>
      <p className="text-xs text-muted">
        <code className="text-foreground">/파일</code> 검색 대상 폴더는 여기서 정하지 않아요. PC에 설치한
        로컬 에이전트 앱의 트레이 아이콘에서 폴더를 추가·관리하면, 검색할 때마다 서버가 그중에서 자동으로
        골라요.
      </p>
    </>
  )
}

export function SettingsDialog({
  theme,
  onThemeChange,
  fontSize,
  onFontSizeChange,
  active,
  onActiveChange,
  onClose,
}: {
  theme: Theme
  onThemeChange: (theme: Theme) => void
  fontSize: FontSize
  onFontSizeChange: (size: FontSize) => void
  active: SettingsCategoryId
  onActiveChange: (id: SettingsCategoryId) => void
  onClose: () => void
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4"
      onClick={onClose}
    >
      <div
        className="flex h-[min(640px,85vh)] w-full max-w-3xl overflow-hidden rounded-2xl border border-hairline bg-surface shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="w-48 shrink-0 space-y-0.5 border-r border-hairline p-2">
          {CATEGORIES.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => onActiveChange(id)}
              className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
                active === id
                  ? 'bg-foreground/10 text-foreground'
                  : 'text-muted hover:bg-foreground/6 hover:text-foreground'
              }`}
            >
              <Icon size={16} />
              {label}
            </button>
          ))}
        </div>

        <div className="relative flex-1 overflow-y-auto p-6">
          <button
            type="button"
            aria-label="닫기"
            onClick={onClose}
            className="absolute right-4 top-4 text-muted transition-colors hover:text-foreground"
          >
            <X size={18} />
          </button>

          {active === 'general' ? (
            <div className="flex flex-col gap-6">
              <h2 className="text-lg font-semibold">프로필</h2>

              <div className="flex h-14 w-14 items-center justify-center rounded-full bg-foreground/10 text-lg font-medium">
                S
              </div>

              <label className="flex flex-col gap-1.5 text-sm">
                <span className="text-muted">성명</span>
                <input
                  defaultValue="Slash 사용자"
                  className="rounded-lg border border-hairline bg-canvas px-3 py-2 text-foreground focus:outline-none"
                />
              </label>

              <label className="flex flex-col gap-1.5 text-sm">
                <span className="text-muted">Slash가 어떻게 불러드릴까요?</span>
                <input
                  placeholder="닉네임"
                  className="rounded-lg border border-hairline bg-canvas px-3 py-2 text-foreground placeholder:text-muted focus:outline-none"
                />
              </label>

              <label className="flex flex-col gap-1.5 text-sm">
                <span className="text-muted">Slash 지침</span>
                <textarea
                  rows={3}
                  placeholder="예: 답변을 간단명료하게 유지"
                  className="resize-none rounded-lg border border-hairline bg-canvas px-3 py-2 text-foreground placeholder:text-muted focus:outline-none"
                />
              </label>

              <div className="border-t border-hairline pt-5">
                <h3 className="mb-3 text-sm font-semibold">환경설정</h3>

                <div className="flex items-center justify-between py-2">
                  <span className="text-sm text-muted">모양</span>
                  <div className="flex gap-1 rounded-lg border border-hairline p-1">
                    {APPEARANCE_OPTIONS.map(({ id, icon: Icon, label }) => (
                      <button
                        key={id}
                        type="button"
                        aria-label={label}
                        onClick={() => onThemeChange(id)}
                        className={`flex h-7 w-9 items-center justify-center rounded-[8px] transition-colors ${
                          theme === id ? 'bg-foreground/12 text-foreground' : 'text-muted hover:text-foreground'
                        }`}
                      >
                        <Icon size={15} />
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex items-center justify-between py-2">
                  <span className="text-sm text-muted">글씨 크기</span>
                  <div className="flex gap-1 rounded-lg border border-hairline p-1">
                    {FONT_SIZE_OPTIONS.map(({ id, label }) => (
                      <button
                        key={id}
                        type="button"
                        onClick={() => onFontSizeChange(id)}
                        className={`rounded-[8px] px-3 py-1 text-sm transition-colors ${
                          fontSize === id ? 'bg-foreground/12 text-foreground' : 'text-muted hover:text-foreground'
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex items-center justify-between py-2">
                  <span className="text-sm text-muted">검색 결과 글꼴</span>
                  <button
                    type="button"
                    className="flex items-center gap-1.5 rounded-lg border border-hairline px-3 py-1.5 text-sm text-foreground"
                  >
                    Pretendard
                    <ChevronDown size={14} />
                  </button>
                </div>
              </div>

              <div className="mt-6 border-t border-hairline pt-5">
                <ClientInfo />
              </div>
            </div>
          ) : active === 'files' ? (
            <div className="flex flex-col gap-6">
              <SearchFolders />
            </div>
          ) : active === 'plugins' ? (
            <div className="flex flex-col gap-6">
              <PcManagement />
            </div>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-muted">
              준비 중이에요.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
