# slash-api ↔ slash-nlu

> 상태: **초안.** 팀 합의 후 확정
> 최종 수정: 2026-08-03 · 작성: 주연우

`slash-api`가 사용자 입력을 분석하기 위해 호출하는 **내부 동기 API**입니다.
사용자에게 직접 노출되지 않습니다.

---

## 규격

```
POST /internal/v1/nlu/analyze
Content-Type: application/json
```

**동기 호출입니다.** 작업 상태 기계(`QUEUED → RUNNING → …`)를 타지 않습니다.
목표 응답 시간은 **500ms 이내**입니다.

---

## 요청

입력 경로가 두 가지이므로 요청도 두 형태입니다.

### ① 슬래시 명령 — 이미 파싱되어 옴

`slash-web`이 명령어와 값을 분리해서 보냅니다.

```json
{
  "command": { "path": ["파일"], "operands": ["작년 견적서"] },
  "requestId": "req-8f2a41",
  "now": "2026-08-03T15:20:00+09:00"
}
```

명령은 이미 정해졌으므로 **인자 정규화만** 수행합니다.

### ② 자연어

```json
{
  "text": "작년 견적서 찾아줘",
  "requestId": "req-8f2a42",
  "now": "2026-08-03T15:20:00+09:00"
}
```

어느 명령인지 판단하는 것부터 시작합니다.

### 필드

| 필드 | 필수 | 설명 |
|---|---|---|
| `text` | △ | 사용자 원문. ②일 때 필수 |
| `command` | △ | `{ path, operands }`. ①일 때 필수 |
| `requestId` | O | 추적용. 로그에 그대로 남김 |
| `now` | X | 상대 날짜 계산 기준 시각. 없으면 서버 시각 |

`text`와 `command` 중 **하나는 반드시** 있어야 합니다. 둘 다 없으면 400입니다.

---

## 응답

```json
{
  "intent": "FILE_SEARCH",
  "args": {
    "query": "세미나 자료",
    "after": "2025-01-01",
    "before": "2025-12-31"
  },
  "confidence": 0.86,
  "matchedBy": "kiwi"
}
```

| 필드 | 필수 | 설명 |
|---|---|---|
| `intent` | O | [intents.md](./intents.md) 의 값 중 하나 |
| `args` | O | intent별 인자. 없으면 `{}` |
| `confidence` | O | 0.0~1.0 |
| `matchedBy` | O | `rule` / `kiwi` / `embedding` — 어느 단계에서 판정했는지 |

### matchedBy 를 두는 이유

분석이 여러 단계를 거치므로, 오분류가 발생했을 때 어느 단계가 원인인지 알아야 합니다.
이 필드 하나로 추적이 끝납니다. 로그에 `requestId`와 함께 남깁니다.

```
[req-8f2a41] "파일 찾아줘" → [kiwi] FILE_SEARCH
```

### confidence 사용 주의

**분기 기준으로 쓰지 마십시오.** 규칙·사전 기반 판정에서 이 값은 참고 지표입니다.
실제 판단은 `intent`와 필수 인자 유무로 합니다.

---

## slash-nlu 가 하지 않는 것

| 항목 | 담당 |
|---|---|
| 실행 위치 결정 (`CLOUD_SYNC` / `LOCAL_AGENT` / `AI_WORKER`) | `slash-api` Registry |
| 위험도 판정·승인 요구 | `slash-api` |
| 원문·버전·수신시각 기록 | `slash-api` |
| 실제 명령 실행 | `slash-agent` / `slash-llm` |

intent 이름은 실행 위치를 의미하지 않습니다. 커맨드 재배선(Config)이 가능하도록
`slash-api`가 매핑을 소유합니다.

---

## 오류

| 상태 | 상황 | 응답 |
|---|---|---|
| 200 | 분석 성공 (`CLARIFY` 포함) | 위 응답 형식 |
| 400 | `text` 없음 또는 빈 문자열 | `{"detail": "..."}` |
| 422 | 형식 오류 | FastAPI 기본 |
| 500 | 내부 오류 | `{"detail": "..."}` |

**분석 실패는 오류가 아닙니다.** 못 알아들은 경우 200으로 `CLARIFY` 또는 `UNSUPPORTED`를 반환합니다.
`slash-api`는 5xx일 때만 재시도하십시오.

---

## 예시

### 슬래시 명령 — 인자 정규화만

```jsonc
// 요청
{ "command": { "path": ["파일"], "operands": ["작년 견적서"] },
  "requestId": "req-1" }

// 응답 — "작년"을 날짜 범위로 분리했다
{ "intent": "FILE_SEARCH",
  "args": { "query": "견적서", "after": "2025-01-01", "before": "2025-12-31" },
  "confidence": 0.99, "matchedBy": "rule" }
```

```jsonc
{ "command": { "path": ["네이버","길찾기"],
               "operands": ["강남역", "홍대입구역"] },
  "requestId": "req-2" }

{ "intent": "MAP_ROUTE",
  "args": { "provider": "naver", "origin": "강남역", "destination": "홍대입구역" },
  "confidence": 0.99, "matchedBy": "rule" }
```

### 자연어 — 명령 판단부터

```jsonc
{ "text": "서울 날씨 어때", "requestId": "req-3" }

{ "intent": "WEATHER", "args": { "location": "서울" },
  "confidence": 0.91, "matchedBy": "kiwi" }
```

### 인자 부족 → 되묻기

```jsonc
{ "command": { "path": ["날씨"], "operands": [] }, "requestId": "req-4" }

{ "intent": "CLARIFY",
  "args": { "question": "어느 지역 날씨를 알려드릴까요?",
            "candidates": ["서울", "부산", "제주"] },
  "confidence": 0.0, "matchedBy": "rule" }
```

### 못 알아들음

```jsonc
{ "text": "메일 좀 보내줘", "requestId": "req-5" }

{ "intent": "UNSUPPORTED", "args": { "hint": "메일" },
  "confidence": 0.62, "matchedBy": "kiwi" }
```

---

## 구현 단계

`matchedBy` 값이 곧 구현 순서입니다. 앞 단계에서 판정되면 뒤 단계로 가지 않습니다.

| 단계 | 방식 | 시기 |
|---|---|---|
| `rule` | 슬래시 접두어 파싱 | 1단계 |
| `kiwi` | 형태소 분석 + 키워드 사전 | 1단계 |
| `embedding` | 의미 유사도 매칭 | 2단계 |

어느 단계에서도 판정되지 않으면 `CLARIFY`를 반환합니다.
`slash-llm`(Gemma)은 **호출하지 않습니다** — 비동기 워커라 동기 응답 시간을 맞출 수 없습니다.
