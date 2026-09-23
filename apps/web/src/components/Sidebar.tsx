import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { PanelLeft, Plus, History, LayoutDashboard, Calendar, Command, Download } from 'lucide-react'
import { Tooltip } from './Tooltip'
import { ProfileMenu } from './ProfileMenu'
import { CommandBadge } from './CommandBadge'
import { useAuth, useHomePath } from '../hooks/authContext'
import { getTaskHistory, toHistoryEntry, type HistoryEntry } from '../lib/tasks'
import { useAgentStatus } from '../hooks/agentStatusContext'
import { useCurrentUser } from '../hooks/currentUserContext'
import type { SettingsCategoryId } from '../lib/settingsCategory'

const RECENT_LIMIT = 8

/** Tailwind의 `md:`와 같은 값이어야 한다 — 접힘(레일) 모드를 쓸지 말지를 JS와 CSS가 같이 판단한다. */
const DESKTOP_QUERY = '(min-width: 768px)'

/**
 * 좁은 화면에서는 접힘 모드가 없다. 68px 레일은 본문 옆에 자리가 남을 때나 쓸모가 있고,
 * 모바일에서는 사이드바가 본문을 덮는 서랍이라 "열림/닫힘" 두 상태로 충분하다.
 */
function useIsDesktop() {
  const [isDesktop, setIsDesktop] = useState(() => window.matchMedia(DESKTOP_QUERY).matches)

  useEffect(() => {
    const media = window.matchMedia(DESKTOP_QUERY)
    const apply = () => setIsDesktop(media.matches)
    media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [])

  return isDesktop
}

const NAV_ITEMS: { icon: typeof History; label: string; path?: string }[] = [
  { icon: History, label: '히스토리', path: '/history' },
  { icon: LayoutDashboard, label: '대시보드', path: '/dashboard' },
  { icon: Calendar, label: '일정' },
]

export function Sidebar({
  mobileOpen,
  onMobileOpenChange,
  onOpenSettings,
  onOpenGuide,
  onOpenShortcuts,
}: {
  mobileOpen: boolean
  onMobileOpenChange: (open: boolean) => void
  onOpenSettings: (category?: SettingsCategoryId) => void
  onOpenGuide: () => void
  onOpenShortcuts: () => void
}) {
  const [collapsed, setCollapsed] = useState(true)
  const [profileMenuOpen, setProfileMenuOpen] = useState(false)
  const isDesktop = useIsDesktop()
  const agentStatus = useAgentStatus()
  const location = useLocation()
  const navigate = useNavigate()
  const homePath = useHomePath()
  const { logout } = useAuth()
  const { displayName, email } = useCurrentUser()
  const profileLabel = displayName ?? '고객'
  const avatarLetter = (displayName ?? email ?? 'S').charAt(0).toUpperCase()
  const [recentEntries, setRecentEntries] = useState<HistoryEntry[]>([])

  // 사이드바는 상시 노출되는 크롬이라 오류를 문구로 알리지 않는다 — 실패하면 그냥 빈 목록으로 둔다.
  useEffect(() => {
    getTaskHistory({ limit: RECENT_LIMIT })
      .then((page) => setRecentEntries(page.items.map(toHistoryEntry)))
      .catch(() => {})
  }, [])
  // 레일(아이콘만) 모드는 데스크톱에서만 — 모바일 서랍은 열리면 항상 제 너비로 보인다.
  const rail = isDesktop && collapsed

  // 넓은 화면으로 바뀌면 서랍은 의미가 없다. 열린 채로 두면 다시 좁아졌을 때 느닷없이 펼쳐져 있다.
  useEffect(() => {
    if (isDesktop) onMobileOpenChange(false)
  }, [isDesktop, onMobileOpenChange])

  useEffect(() => {
    if (!mobileOpen) return
    const onKeyDown = (e: KeyboardEvent) => e.key === 'Escape' && onMobileOpenChange(false)
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [mobileOpen, onMobileOpenChange])

  return (
    <>
      {/* 서랍이 열렸을 때만 깔리는 막 — 데스크톱에서는 사이드바가 본문을 덮지 않으므로 없다. */}
      {mobileOpen && (
        <div className="fixed inset-0 z-30 bg-black/50 md:hidden" onClick={() => onMobileOpenChange(false)} />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex h-screen w-[260px] shrink-0 flex-col border-r border-hairline bg-surface transition-transform duration-200 md:static md:translate-x-0 md:transition-[width] ${
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        } ${rail ? 'md:w-[68px]' : 'md:w-[260px]'}`}
      >
        <div className="flex items-center justify-between px-3 pt-4">
          {!rail && (
            <button
              type="button"
              onClick={() => navigate(homePath)}
              className="-mx-1 flex items-center gap-2 rounded-[8px] px-2 py-1 text-control font-semibold transition-colors hover:bg-surface-raised"
            >
              <img src="/logo.png" alt="" className="h-6 w-6 rounded-[6px]" />
              Slash
            </button>
          )}
          <Tooltip label={!isDesktop ? '사이드바 닫기' : rail ? '사이드바 펼치기' : '사이드바 접기'}>
            <button
              aria-label={isDesktop ? '사이드바 접기/펼치기' : '사이드바 닫기'}
              onClick={() => (isDesktop ? setCollapsed((c) => !c) : onMobileOpenChange(false))}
              className={`flex h-8 w-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-raised hover:text-foreground ${
                rail ? 'mx-auto' : ''
              }`}
            >
              <PanelLeft size={18} />
            </button>
          </Tooltip>
        </div>

        <div className="px-3 pt-4">
          <button
            type="button"
            onClick={() => navigate('/new')}
            className={`flex w-full items-center gap-2 rounded-lg bg-foreground/8 px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-foreground/12 ${
              rail ? 'justify-center' : ''
            }`}
          >
            <Plus size={16} />
            {!rail && '새 채팅'}
          </button>
        </div>

        <nav className="flex flex-col gap-0.5 px-3 pt-3">
          {NAV_ITEMS.map(({ icon: Icon, label, path }) => {
            const active = path !== undefined && location.pathname === path
            return (
              <button
                key={label}
                type="button"
                onClick={path ? () => navigate(path) : undefined}
                className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                  active
                    ? 'bg-foreground/8 text-foreground'
                    : 'text-muted hover:bg-surface-raised hover:text-foreground'
                } ${rail ? 'justify-center' : ''}`}
              >
                <Icon size={17} />
                {!rail && label}
              </button>
            )
          })}
          <button
            type="button"
            onClick={onOpenGuide}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted transition-colors hover:bg-surface-raised hover:text-foreground ${
              rail ? 'justify-center' : ''
            }`}
          >
            <Command size={17} />
            {!rail && '명령어 가이드'}
          </button>
        </nav>

        {rail ? (
          <div className="flex-1" />
        ) : (
          <div className="mt-4 flex-1 overflow-y-auto px-3">
            <p className="px-3 pb-1 text-xs font-medium text-muted">최근</p>
            <div className="flex flex-col gap-0.5">
              {recentEntries.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => navigate(`/chat/${item.id}`)}
                  className="flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-foreground/80 transition-colors hover:bg-surface-raised"
                >
                  <CommandBadge label={item.commandLabel} />
                  <span data-clarity-mask="true" className="truncate">
                    {item.text}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="relative flex items-center gap-1 border-t border-hairline px-2 py-2">
          <button
            type="button"
            onClick={() => setProfileMenuOpen((o) => !o)}
            className={`flex min-w-0 flex-1 items-center gap-2.5 rounded-lg px-1.5 py-1.5 text-left transition-colors hover:bg-surface-raised ${
              rail ? 'justify-center' : ''
            }`}
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-foreground/10 text-sm font-medium text-foreground">
              {avatarLetter}
            </div>
            {!rail && (
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-foreground">{profileLabel}</p>
                <p className="text-xs text-muted">무료 플랜</p>
              </div>
            )}
          </button>

          {/* 로컬 에이전트가 꺼져있을 때만 보인다 — 켜져있으면 할 일이 없으니 아이콘 자체가 사라진다
              (모양이 아니라 색으로 "알림"을 표현하면 accent-blue/green을 원래 역할 밖에 쓰게 된다). */}
          {!rail && agentStatus === 'offline' && (
            <Tooltip label="로컬 에이전트가 꺼져있어요 — 다운로드 및 PC 등록하기">
              <button
                type="button"
                aria-label="로컬 에이전트 다운로드"
                onClick={() => onOpenSettings('plugins')}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-raised hover:text-foreground"
              >
                <Download size={16} />
              </button>
            </Tooltip>
          )}

          {profileMenuOpen && (
            <ProfileMenu
              email={email ?? ''}
              onOpenSettings={onOpenSettings}
              onOpenShortcuts={onOpenShortcuts}
              // logout()이 Cognito 로그아웃 엔드포인트로 전체 페이지 리다이렉트를 일으키므로
              // 이후 navigate가 필요 없다 — 브라우저가 이미 이 페이지를 떠난다.
              onLogout={() => {
                void logout()
              }}
              onClose={() => setProfileMenuOpen(false)}
            />
          )}
        </div>
      </aside>
    </>
  )
}
