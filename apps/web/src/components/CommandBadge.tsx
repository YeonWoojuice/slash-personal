/** 히스토리·최근·대시보드·채팅상세에서 어떤 명령(taskType)의 결과인지 보여주는 배지 — 원래
 *  슬래시 명령 자체를 나타내던 파란 정사각 "/" 아이콘 뒤에, 구체적 명령 이름(날씨 등, 슬래시는
 *  아이콘이 이미 담당하니 라벨엔 안 붙임) 알약 배지를 이어붙인다. label이 없으면 자유입력이거나
 *  아직 분류되지 않은 항목이라 아무것도 렌더링하지 않는다. */
export function CommandBadge({ label }: { label: string | null }) {
  if (!label) return null
  return (
    <span className="inline-flex shrink-0 items-center gap-1 align-middle">
      <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-[4px] bg-accent-blue text-2xs font-semibold text-white">
        /
      </span>
      <span className="rounded-full bg-accent-blue/12 px-2 py-0.5 text-2xs font-medium text-accent-blue">
        {label}
      </span>
    </span>
  )
}
