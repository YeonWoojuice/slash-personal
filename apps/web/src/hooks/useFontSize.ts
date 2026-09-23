import { useEffect, useState } from 'react'

export type FontSize = 'normal' | 'large' | 'x-large'

const STORAGE_KEY = 'slash-font-size'

function isFontSize(value: string | null): value is FontSize {
  return value === 'normal' || value === 'large' || value === 'x-large'
}

/**
 * 글씨 크기 설정. 테마와 같은 방식으로 루트에 data 속성을 걸고 localStorage에 남긴다 —
 * 새로고침해도 유지돼야 "설정"이라는 말이 성립한다.
 * 실제 크기 조절은 index.css의 `--font-scale`이 하고, 여기서는 어느 단계인지만 정한다.
 */
export function useFontSize() {
  const [fontSize, setFontSize] = useState<FontSize>(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    return isFontSize(stored) ? stored : 'normal'
  })

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, fontSize)
    document.documentElement.dataset.fontSize = fontSize
  }, [fontSize])

  return { fontSize, setFontSize }
}
