import { useLayoutEffect, useRef, useState } from 'react'
import { SearchBar } from '../components/SearchBar'
import { useCurrentUser } from '../hooks/currentUserContext'

export function HomePage() {
  const { displayName } = useCurrentUser()
  const nameLabel = displayName ? `${displayName}님` : '고객님'
  const rootRef = useRef<HTMLDivElement>(null)
  const coreRef = useRef<HTMLDivElement>(null)
  const [topOffset, setTopOffset] = useState(0)

  // justify-center는 뺐다(2026-08-20) — Shift+Enter로 입력창이 여러 줄로 늘어나면 [헤딩+검색창]
  // 묶음의 총 높이가 바뀌고, justify-center가 그때마다 다시 중앙정렬하면서 통째로 위로 움직였다.
  // 대신 마운트 시점(아직 아무것도 안 늘어난 idle 상태) 딱 한 번만 그 묶음의 실제 높이를 재서
  // 화면 정중앙에 오는 위쪽 여백을 계산해 고정한다 — 이후 검색창이 늘어나도 이 값은 다시
  // 계산되지 않으니 "묶음 자체는 정확히 중앙"이면서 "늘어나는 만큼은 아래로만" 둘 다 된다.
  // useLayoutEffect를 쓰는 이유: 페인트 전에 값을 확정해야 padding 0인 상태가 잠깐 보이지 않는다.
  useLayoutEffect(() => {
    const root = rootRef.current
    const core = coreRef.current
    if (!root || !core) return
    setTopOffset(Math.max(0, (root.clientHeight - core.offsetHeight) / 2))
  }, [])

  return (
    <div ref={rootRef} className="flex w-full max-w-3xl flex-1 flex-col items-center text-center">
      <div ref={coreRef} style={{ paddingTop: topOffset }} className="flex w-full flex-col items-center">
        {/* 부제 삭제(2026-08-20) — "파일·웹 검색, 생성형 AI, PC 제어까지 한 번에."는 기능
            나열형이라, 바로 위 인사말이 만든 "비서가 말을 거는" 느낌(자비스 컨셉)을 도로 스펙
            카탈로그 톤으로 깨뜨렸다. 능력 안내는 placeholder 문구·사이드바 명령어 가이드·
            온보딩 다이얼로그가 나눠서 이미 커버하므로, 인사말 하나로 남긴다. */}
        <h1 className="text-4xl font-bold tracking-tight">{nameLabel}, 무엇을 도와드릴까요?</h1>

        <div className="mt-10 w-full">
          <SearchBar />
        </div>
      </div>
    </div>
  )
}
