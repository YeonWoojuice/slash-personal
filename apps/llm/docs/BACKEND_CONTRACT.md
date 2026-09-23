# Backend 연동 계약

`slash-api`의 2026-08-06 `dev`는 `async_jobs + outbox + SQS` 골격을 가지고
있지만 실제 publisher/consumer 계약은 아직 구현되지 않았다. 현재 HTTP endpoint는
로컬 개발과 요약 코어 검증용으로 유지하며, 확정 전 SQS worker를 임의로 구현하지 않는다.

## HTTP 내부 계약

| 항목 | 값 |
|---|---|
| Endpoint | `POST /internal/v1/llm/summary` |
| 요청 | `text`, 선택적 `requestId`, `taskId` |
| 성공 | `summary`, `model`, 제공된 추적 ID |
| 오류 | `error:{code,message,retryable}`, 제공된 추적 ID |

이 응답은 평탄 JSON이다. 공개 API의 `{data, meta}`·`{error, meta}` envelope와
Task 결과 저장은 Backend가 담당한다. 내부 응답에 공개 envelope를 중복 적용하지 않는다.

## 오류 변환 권장안

| LLM 코드 | Backend 권장 코드 |
|---|---|
| `INPUT_TOO_SHORT` | `INVALID_PARAMETERS` |
| `MODEL_BUSY` | `LLM_NOT_READY` |
| `MODEL_UNAVAILABLE` | `LLM_NOT_READY` |
| `MODEL_TIMEOUT` | `UPSTREAM_UNAVAILABLE` |
| `UPSTREAM_ERROR` | `UPSTREAM_UNAVAILABLE` |
| `INVALID_MODEL_RESPONSE` | `UPSTREAM_UNAVAILABLE` |

사용자/IP Rate Limit은 Backend가 Valkey로 처리하고 `429 RATE_LIMITED`와
`Retry-After`를 반환한다. LLM의 `503 MODEL_BUSY`는 모델 프로세스 자원 보호용이다.

## ID 전파

| 내부 값 | LLM 전달 |
|---|---|
| Backend `correlationId` | HTTP `requestId` |
| Backend `taskId` | HTTP `taskId` |

향후 SQS adapter는 최소 `eventId`, `jobId`, `taskId`, `correlationId`,
`jobType`, `payload.text`, `deadlineAt`을 받아야 한다. 결과에는 중복 반영을 막을
`eventId`, `jobId`, 성공 결과 또는 `{code,message,retryable}` 오류가 필요하다.
정확한 필드명, queue URL, ack/retry/DLQ 정책은 Backend 팀과 확정한 뒤 구현한다.
