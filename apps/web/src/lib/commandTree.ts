// Static slash-command tree for the discovery/autocomplete dropdown (type "/" to browse).

export type CommandNode = {
  id: string
  label: string
  description: string
  children?: CommandNode[]
  /**
   * 이 명령이 받는 값들의 이름. 하나라도 있으면 `/명령` 뒤에 공백을 치는 순간 명령어는 칩으로
   * 빠지고 입력창은 값만 받는다 — 명령어와 검색어를 한 문자열로 섞지 않기 위해서다(백엔드에도
   * 둘을 따로 보낸다). 값이 둘 이상이면 Enter마다 한 값씩 확정한다(`/네이버/길찾기`).
   * 값을 받지 않는 명령(`/모델`, `/파일/휴지통` 같은 패널)은 이 필드가 없다.
   */
  operands?: string[]
  /**
   * 값을 더 안 받고 고르는 즉시 제출하는 리프 노드(예: /사용량/클로드) — operands도 없고 하위
   * 메뉴로 더 내려가지도 않는다. 선택하면 첫 세그먼트는 명령어, 나머지는 공백으로 이어붙인
   * 값으로 조립해(`/사용량 클로드`) 바로 전송한다(SearchBar.tsx의 selectSuggestion).
   */
  submitOnSelect?: boolean
}

// Flattened (2026-07-30, later): "/" already implies "search", so a literal "검색" segment was
// redundant everywhere it appeared. /파일/검색 → /파일 (파일's only other action, 휴지통, stays an
// explicit child). /검색/네이버 and /지도·/길찾기 under 네이버 collapsed into one 네이버 node —
// bare /네이버 is search, and 지도/길찾기 are its children — since a service (네이버) always
// means the same thing wherever it appears, unlike the old tree where "네이버" was sometimes the
// top-level trigger and sometimes a child, depending on position. 구글 only ever searches, so it's
// a bare leaf with no children needed. 날씨는 그 반대 방향으로 갈라져 나갔다 — 아래 주석 참고.
export const COMMAND_TREE: CommandNode[] = [
  {
    id: '파일',
    label: '파일',
    description: '선택한 폴더에서 파일 이름으로 검색',
    operands: ['파일 이름'],
    children: [
      { id: '휴지통', label: '휴지통', description: '삭제한 파일 보기 · 복원 · 완전 삭제' },
      { id: '기타기능', label: '기타기능', description: '준비 중이에요' },
    ],
  },
  { id: '모델', label: '모델', description: '답변에 사용할 AI 모델 선택' },
  // slash-nlu의 SLASH_ALIASES(intents.py)가 실제로 인식하는 별칭이다 — '상태'·'status' 둘 다
  // SYSTEM_STATUS로 매핑되지만, 이 앱의 다른 명령어가 전부 한글이라 그쪽에 맞춘다.
  { id: '상태', label: '상태', description: '이 PC의 CPU·메모리·디스크 사용량을 확인해요' },
  // workspaceId는 서버가 등록된 프로젝트 폴더 중에서 자동으로 고른다(TaskType.CODE_ANALYSIS의
  // backendProvidedParameters) — /파일의 searchFolderId와 같은 이유로 여기서 값을 받지 않는다.
  { id: '코드', label: '코드', description: '등록한 프로젝트 폴더를 읽기 전용으로 분석해요', operands: ['질문'] },
  // provider는 텍스트로 자유 입력받지 않고 둘 중 하나를 고르게 한다 — slash-nlu(analyzer.py의
  // _USAGE_PROVIDER_ALIASES)가 "클로드"·"코덱스" 표기를 그대로 CLAUDE_CODE·CODEX로 인식한다.
  {
    id: '사용량',
    label: '사용량',
    description: 'Claude Code·Codex CLI의 로컬 사용량을 확인해요',
    children: [
      { id: '클로드', label: '클로드', description: 'Claude Code 사용량', submitOnSelect: true },
      { id: '코덱스', label: '코덱스', description: 'Codex 사용량', submitOnSelect: true },
    ],
  },
  {
    id: '네이버',
    label: '네이버',
    description: '네이버 통합검색',
    operands: ['검색어'],
    children: [
      { id: '지도', label: '지도', description: '네이버 지도', operands: ['장소'] },
      { id: '길찾기', label: '길찾기', description: '네이버 길찾기', operands: ['출발지', '도착지'] },
    ],
  },
  { id: '구글', label: '구글', description: '구글 검색', operands: ['검색어'] },
  // 날씨는 네이버 아래가 아니라 최상위다 — 네이버조차 외부 기상 API를 받아 보여주는 것이라,
  // "어느 서비스로 볼지"를 물을 이유가 없다. 백엔드가 API에서 직접 받아온 값을 돌려준다.
  { id: '날씨', label: '날씨', description: '지역 날씨', operands: ['지역'] },
  // slash-nlu가 150자 미만이면 NEEDS_CLARIFICATION으로 되묻는다 — 프론트는 그 흐름을
  // 자유 텍스트와 동일하게 그대로 받으면 되므로 별도 검증 없이 값만 넘긴다.
  { id: '요약', label: '요약', description: '긴 텍스트를 요약해요 (150자 이상)', operands: ['내용'] },
]

/** 경로(`['네이버','지도']`)에 해당하는 노드. 중간에 끊기면 null. */
export function findCommand(pathIds: string[]): CommandNode | null {
  let nodes = COMMAND_TREE
  let found: CommandNode | null = null

  for (const id of pathIds) {
    const match = nodes.find((n) => n.id === id)
    if (!match) return null
    found = match
    nodes = match.children ?? []
  }
  return found
}

export type Suggestions = { pathIds: string[]; options: CommandNode[] }

/** Returns the command-tree options matching what's typed after the last "/", or null if nothing matches. */
export function getSuggestions(value: string): Suggestions | null {
  if (!value.startsWith('/') || value.includes(' ')) return null

  const segments = value.slice(1).split('/')
  let nodes = COMMAND_TREE

  for (let i = 0; i < segments.length - 1; i++) {
    const match = nodes.find((n) => n.id === segments[i])
    if (!match?.children) return null
    nodes = match.children
  }

  const filterText = segments[segments.length - 1]
  const options = nodes.filter((n) => n.id.startsWith(filterText))
  return options.length > 0 ? { pathIds: segments.slice(0, -1), options } : null
}
