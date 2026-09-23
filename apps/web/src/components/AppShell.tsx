import { useEffect, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { PanelLeft } from 'lucide-react'
import { Sidebar } from './Sidebar'
import { SettingsDialog } from './SettingsDialog'
import { CommandGuideDialog } from './CommandGuideDialog'
import { ShortcutsDialog } from './ShortcutsDialog'
import { OnboardingDialog } from './OnboardingDialog'
import { useAppearance } from '../hooks/appearanceContext'
import { AgentStatusProvider } from '../hooks/agentStatusContext'
import { CurrentUserProvider } from '../hooks/currentUserContext'
import { DEFAULT_SETTINGS_CATEGORY, isSettingsCategoryId, type SettingsCategoryId } from '../lib/settingsCategory'

const SETTINGS_HASH_PREFIX = '#settings/'
const GUIDE_HASH = '#guide'
const SHORTCUTS_HASH = '#shortcuts'
const ONBOARDING_STORAGE_KEY = 'slash-onboarding-seen'

export function AppShell({ children }: { children: ReactNode }) {
  const { theme, setTheme, fontSize, setFontSize } = useAppearance()
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()

  // 백엔드에 "온보딩 봤음" 상태를 둘 필요가 없어서 localStorage로만 판단한다 — 계정이 아니라
  // 이 브라우저 기준 1회다(OnboardingDialog.tsx 주석 참고).
  const [onboardingOpen, setOnboardingOpen] = useState(() => !localStorage.getItem(ONBOARDING_STORAGE_KEY))
  const dismissOnboarding = () => {
    localStorage.setItem(ONBOARDING_STORAGE_KEY, '1')
    setOnboardingOpen(false)
  }

  const settingsCategoryRaw = location.hash.startsWith(SETTINGS_HASH_PREFIX)
    ? location.hash.slice(SETTINGS_HASH_PREFIX.length)
    : null
  const settingsOpen = settingsCategoryRaw !== null
  const settingsCategory =
    settingsCategoryRaw && isSettingsCategoryId(settingsCategoryRaw) ? settingsCategoryRaw : DEFAULT_SETTINGS_CATEGORY

  const openSettings = (category: SettingsCategoryId = DEFAULT_SETTINGS_CATEGORY) =>
    navigate({ pathname: location.pathname, hash: `${SETTINGS_HASH_PREFIX}${category}` })
  const closeSettings = () => navigate({ pathname: location.pathname }, { replace: true })
  const changeSettingsCategory = (id: string) =>
    navigate({ pathname: location.pathname, hash: `${SETTINGS_HASH_PREFIX}${id}` }, { replace: true })

  // 화면을 옮기면 서랍은 할 일이 끝났다 — 모바일에서는 본문을 덮고 있으므로 더더욱.
  useEffect(() => {
    setMobileNavOpen(false)
  }, [location.pathname])

  const guideOpen = location.hash === GUIDE_HASH
  const openGuide = () => navigate({ pathname: location.pathname, hash: GUIDE_HASH })
  const closeGuide = () => navigate({ pathname: location.pathname }, { replace: true })

  const shortcutsOpen = location.hash === SHORTCUTS_HASH
  const openShortcuts = () => navigate({ pathname: location.pathname, hash: SHORTCUTS_HASH })
  const closeShortcuts = () => navigate({ pathname: location.pathname }, { replace: true })

  return (
    <AgentStatusProvider>
      <CurrentUserProvider>
      <div className="flex h-screen font-sans text-foreground">
        <Sidebar
          mobileOpen={mobileNavOpen}
          onMobileOpenChange={setMobileNavOpen}
          onOpenSettings={openSettings}
          onOpenGuide={openGuide}
          onOpenShortcuts={openShortcuts}
        />
        {/* 좁은 화면에서 사이드바를 여는 유일한 손잡이 — 사이드바 자체는 화면 밖에 있다. */}
        <button
          type="button"
          aria-label="사이드바 열기"
          onClick={() => setMobileNavOpen(true)}
          className="fixed left-3 top-3 z-20 flex h-9 w-9 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-raised hover:text-foreground md:hidden"
        >
          <PanelLeft size={18} />
        </button>
        {/* 모바일에서는 위쪽에 그 버튼이 앉을 자리를 비워둔다. */}
        <main className="flex flex-1 flex-col items-center overflow-y-auto px-6 pb-8 pt-16 md:pt-8">{children}</main>
        {settingsOpen && (
          <SettingsDialog
            theme={theme}
            onThemeChange={setTheme}
            fontSize={fontSize}
            onFontSizeChange={setFontSize}
            active={settingsCategory}
            onActiveChange={changeSettingsCategory}
            onClose={closeSettings}
          />
        )}
        {guideOpen && <CommandGuideDialog onClose={closeGuide} />}
        {shortcutsOpen && <ShortcutsDialog onClose={closeShortcuts} />}
        {onboardingOpen && <OnboardingDialog onClose={dismissOnboarding} />}
      </div>
      </CurrentUserProvider>
    </AgentStatusProvider>
  )
}
