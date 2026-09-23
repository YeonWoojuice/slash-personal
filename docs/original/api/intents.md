# 명령(intent) 목록

> 상태: **초안.** 팀 합의 후 확정
> 기준: `slash-web`의 `src/lib/commandTree.ts` (실제 구현체)
> 최종 수정: 2026-08-03 · 작성: 주연우

---

## 입력 경로는 두 가지다

```
① 슬래시 명령                       ② 자연어
   "/네이버 아이폰 16 가격"             "아이폰 16 얼마야"
        ↓ slash-web 이 파싱                ↓ 그대로
   { path: ["네이버"],                  { text: "아이폰 16 얼마야" }
     operands: ["아이폰 16 가격"] }
        ↓                                  ↓
        └──────── slash-nlu ───────────────┘
                     ↓
              내부 intent + 정규화된 인자
```

**①은 이미 파싱되어 옵니다.** `slash-web`이 명령어와 값을 분리해서 보냅니다.
그래도 `slash-nlu`를 거치는 이유는 **인자 정규화** 때문입니다.

```
/파일 작년 견적서
  → operands: ["작년 견적서"]
  → nlu: query="견적서", after="2025-01-01", before="2025-12-31"
```

②는 어느 명령인지부터 판단해야 합니다.

---

## 명령 목록

`slash-web` 트리에 등록된 명령입니다. `path`는 프론트가 쓰는 이름, `intent`는 내부 식별자입니다.

| path | 표시 이름 | operands | intent | 실행 위치 |
|---|---|---|---|---|
| `["파일"]` | 파일 | 파일 이름 | `FILE_SEARCH` | agent |
| `["파일","휴지통"]` | 파일 › 휴지통 | — | `FILE_TRASH` | agent |
| `["날씨"]` | 날씨 | 지역 | `WEATHER` | api → 날씨 API |
| `["네이버"]` | 네이버 | 검색어 | `WEB_SEARCH` | api → 네이버 API |
| `["네이버","지도"]` | 네이버 › 지도 | 장소 | `MAP_SEARCH` | api → 네이버 API |
| `["네이버","길찾기"]` | 네이버 › 길찾기 | 출발지, 도착지 | `MAP_ROUTE` | api → 네이버 API |
| `["구글"]` | 구글 | 검색어 | `WEB_SEARCH` | api → 구글 API |
| `["모델"]` | 모델 | — | — | 프론트 전용 패널 |

### 왜 이름을 둘로 나누나

- **`path`** — 사용자에게 보이는 한글 이름. 바뀔 수 있음 (`네이버` → `검색`)
- **`intent`** — 내부 식별자. 바뀌면 안 됨

`네이버`와 `구글`이 같은 `WEB_SEARCH`로 가는 것처럼, 표시 이름과 처리 방식은 1:1이 아닙니다.
공급자는 `args.provider`로 구분합니다.

### `모델`은 명령이 아니다

`/모델`은 백엔드로 가지 않습니다. 답변에 쓸 AI를 고르는 프론트 패널입니다.

---

## 인자

| 인자 | 형식 | 쓰는 곳 |
|---|---|---|
| `query` | string | `FILE_SEARCH`, `WEB_SEARCH` |
| `provider` | `naver` \| `google` | `WEB_SEARCH`, `MAP_*` |
| `location` | string | `WEATHER` — **형식은 날씨 API 확정 후 결정** |
| `place` | string | `MAP_SEARCH` |
| `origin` / `destination` | string | `MAP_ROUTE` |
| `rootId` | string | `FILE_SEARCH` — 색인 폴더. 없으면 전체 |
| `ext` | string[] | `FILE_SEARCH` |
| `after` / `before` | `YYYY-MM-DD` | `FILE_SEARCH` |

> `location` 형식 주의 — 기상청 공공 API는 격자 좌표(nx, ny)를 요구합니다.
> 그 API를 쓴다면 지역명 → 좌표 변환이 필요하며, 변환 주체를 정해야 합니다.

---

## 제어 명령

분석에 실패했거나 처리할 수 없을 때 반환합니다.

| intent | 인자 | 화면 처리 |
|---|---|---|
| `CLARIFY` | `question`(필수), `candidates` | 질문과 선택지를 보여주고 재입력 유도 |
| `UNSUPPORTED` | `hint` | "준비 중" 안내 |
| `REJECT` | `reason`(필수) | 사유 안내 |

```json
{
  "intent": "CLARIFY",
  "args": {
    "question": "어느 지역 날씨를 알려드릴까요?",
    "candidates": ["서울", "부산", "제주"]
  }
}
```

### CLARIFY 를 반환하는 경우

- 필수 인자가 비어 있음 (`/날씨`만 입력)
- 어느 명령인지 특정되지 않음
- 값이 모호함

### REJECT 는 좁게 쓴다

지식 질문은 `REJECT`가 아니라 **검색으로 넘깁니다.**

| 입력 | intent |
|---|---|
| "오늘 환율" | `WEB_SEARCH` |
| "데코레이터가 뭐야" | `WEB_SEARCH` 또는 모델 답변 |
| 서비스가 제공하지 않는 기능 | `REJECT` |

넓게 쓰면 "안 되는 서비스"로 인식됩니다.

---

## 상대 시간 표현

`after`와 `before`를 **모두** 채웁니다. 한쪽만 채우면 범위가 성립하지 않습니다.

| 입력 | after | before |
|---|---|---|
| 작년 | 2025-01-01 | 2025-12-31 |
| 지난주 | 해당 주 월요일 | 해당 주 일요일 |
| 어제 | 어제 | 어제 |
| 최근 | 30일 전 | 오늘 |

기준 시각은 요청 수신 시각(KST)입니다.

---

## 확인이 필요한 항목

아래는 아직 정해지지 않았습니다. 회의 안건입니다.

| 항목 | 내용 |
|---|---|
| **요약 · 시스템 상태** | 트리에 없음. 1단계에 넣을지, 넣는다면 어떤 이름으로 (`/요약`, `/상태`?) |
| **슬래시 명령의 nlu 경유** | `path/operands`가 이미 분리돼 오는데, nlu를 거칠지 api가 바로 처리할지 |
| **날씨 API** | 기상청 / OpenWeather / 네이버 — `location` 형식이 여기 달림 |
| **`rootId`** | 폴더 ID인지 경로인지. `slash-agent` 담당 확인 필요 |
| **`휴지통`·`기타기능`** | 1단계 범위인지 |
| **웹 검색** | 네이버·구글 API 키 발급 주체 |

---

## 확장 규칙

- 명령 추가 시 `slash-web`의 `commandTree.ts`와 이 문서를 **함께** 고칩니다
- `intent` 이름 변경·삭제는 팀 합의 후
- `path`(표시 이름)는 프론트 재량으로 바꿀 수 있습니다 — `intent`만 유지되면 됩니다

---

## 관련 문서

- [nlu.md](./nlu.md) — `slash-api` ↔ `slash-nlu` 호출 규격
- [llm.md](./llm.md) — `slash-api` ↔ `slash-llm` 호출 규격
- `slash-web/src/lib/commandTree.ts` — 명령 트리 구현체
