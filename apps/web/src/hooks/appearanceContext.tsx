import { createContext, useContext, type ReactNode } from 'react'
import { useTheme, type Theme } from './useTheme'
import { useFontSize, type FontSize } from './useFontSize'

type Appearance = {
  theme: Theme
  setTheme: (theme: Theme) => void
  fontSize: FontSize
  setFontSize: (size: FontSize) => void
}

const AppearanceContext = createContext<Appearance | null>(null)

/**
 * 테마와 글씨 크기를 앱 전체에 적용한다. **라우터 바깥에서 감싸야 한다** — 로그인 화면처럼
 * AppShell을 쓰지 않는 화면도 있는데, 예전에는 이 둘이 AppShell 안에서만 돌아서 로그인 화면이
 * data 속성 없이 그려졌다. 그러면 CSS 기본값(다크, 기본 글씨)이 되어, 시스템이 라이트 모드여도
 * 로그인 화면만 어두웠다.
 */
export function AppearanceProvider({ children }: { children: ReactNode }) {
  const { theme, setTheme } = useTheme()
  const { fontSize, setFontSize } = useFontSize()
  return (
    <AppearanceContext.Provider value={{ theme, setTheme, fontSize, setFontSize }}>
      {children}
    </AppearanceContext.Provider>
  )
}

export function useAppearance(): Appearance {
  const value = useContext(AppearanceContext)
  if (!value) throw new Error('useAppearance는 AppearanceProvider 안에서만 쓸 수 있어요.')
  return value
}
