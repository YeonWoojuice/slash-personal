# slash-llm agent guide

이 저장소에서 작업하는 메인·서브 에이전트용 지침이다. 수정 범위는 `slash-llm`으로 제한한다.

## 작업 범위

### 이 저장소가 담당한다

- FastAPI 기반 LLM 내부 서비스
- Ollama/Gemma 호출
- 확정된 LLM 작업의 프롬프트와 출력 검증
- 입력 길이·timeout·모델 오류 처리
- LLM 단위 테스트와 벤치마크

### 이 저장소가 담당하지 않는다

- NLU 분류와 TaskType 결정
- Task 실행 위치 결정
- Task 상태와 DB 저장
- 사용자 PC 작업 실행
- 외부 날씨·검색 API 호출
- Web UI와 Agent WSS 변경

`slash-api`, `slash-runner`, `slash-web`, `slash-nlu`, `slash-docs`, `slash-infra`는 읽기 전용 참고 대상이다. 사용자 요청 없이 수정하지 않는다.

## 현재 상태

`main.py`에 다음이 구현돼 있다.

| 항목 | 현재 구현 |
|---|---|
| 서버 | FastAPI |
| 모델 | Ollama `gemma3:4b` |
| 상태 확인 | `GET /health` |
| 요약 | `POST /internal/v1/llm/summary` |
| 입력 제한 | 150자 미만 거부, 8000자 초과 절삭 |
| timeout | 환경변수 `LLM_TIMEOUT`, 기본 120초 |
| 수동 시험 | `samples.py`, `bench.py` |
| 요청 추적 | 선택적 `requestId`, `taskId` 전달 |
| 오류 응답 | 모델 timeout·연결·HTTP·잘못된 응답 구분 |
| 자동 테스트 | `tests/test_main.py`의 mock 기반 계약 테스트 |
| 요약 코어 | `summary_core.py`의 입력 정규화·프롬프트 생성 |

아직 없는 항목:

- 일반 대화 endpoint
- SQS worker (`docs/BACKEND_CONTRACT.md`의 메시지 초안은 합의용이며 구현 계약 아님)
- 배포 환경 검증

일반 대화와 SQS는 현재 MVP 범위가 아니다. README와 `slash-docs/api/*.md`에
관련 설명이 있더라도 실제 구현 완료로 간주하지 않는다.

## 확정된 MVP 계약

| 항목 | 결정 |
|---|---|
| MVP 기능 | `TEXT_SUMMARY`만 제공 |
| 전달 방식 | 현재 HTTP 유지 |
| 요청 추적 | 선택적 `requestId`, `taskId`; 제공된 값만 응답에 포함 |
| 오류 계약 | `{error:{code,message,retryable}, requestId?, taskId?}` |
| 8000자 초과 | 앞의 8000자만 모델에 전달 |
| 응답 형식 | 기존 `{summary, model}` 호환 유지 |
| 사용자 Rate Limit | `slash-api` 소유; `429 RATE_LIMITED`와 `Retry-After`로 연동 |
| 모델 동시성 | LLM 프로세스가 환경변수 기준으로 제한; 초과 시 `503 MODEL_BUSY`와 `Retry-After` |
| Backend 경계 | 내부 평탄 JSON 유지; 공개 envelope와 오류 변환은 `slash-api` 소유 |

일반 대화, SQS, 성공 응답 envelope 같은 추가 계약은 별도 결정 없이 구현하지 않는다.

## 구현 원칙

- Gemma는 전달받은 텍스트를 가공하는 역할만 한다.
- 날씨, 뉴스, 환율 같은 최신 사실을 모델 지식만으로 답하지 않는다.
- 프롬프트에 없는 사실을 추가하지 않도록 작업별 제약을 둔다.
- Ollama 응답의 필수 필드를 검증하고 연결·timeout·잘못된 응답을 구분한다.
- 모델 URL, 모델명, timeout, 입력 제한은 환경변수로 유지한다.
- API key, 원문 전체, 민감 데이터는 불필요하게 로그에 남기지 않는다.
- 현재 HTTP 구현을 SQS로 바꾸는 작업은 별도 결정 없이 진행하지 않는다.
- SQS adapter는 Backend가 메시지 필드·재시도·DLQ 정책을 확정한 뒤 요약 코어 위에 추가한다.
- 사용자/IP별 횟수 제한을 이 서비스에 중복 구현하지 않는다. LLM은 모델 호출 동시성과 timeout만 방어한다.

## 권장 내부 구조

현재 `main.py` 하나를 유지해도 되지만 기능이 늘면 다음 경계를 사용한다.

```text
main.py              FastAPI app과 endpoint
models.py            요청·응답 모델
ollama_client.py     Ollama 호출과 오류 정규화
prompts.py           작업별 프롬프트
tests/
  test_summary.py
```

사용자가 실제로 두 파일만 허용하면 `main.py`와 `test_main.py`로 시작한다.

## 메인·서브 에이전트 분할

| 작업 | 담당 가능 |
|---|---|
| 외부 API 계약과 응답 모델 | 메인 에이전트 단독 |
| Ollama client와 timeout 처리 | 서브 에이전트 |
| 요약 프롬프트·검증 | 서브 에이전트 |
| 테스트와 fixture | 서브 에이전트 |
| 전체 통합·회귀 검증 | 메인 에이전트 |

여러 에이전트가 요청·응답 모델이나 endpoint 경로를 동시에 변경하지 않는다.

## 완료 기준

```text
[ ] `/health`가 모델 설정을 노출한다.
[ ] 정상 요약 요청이 검증된 응답을 반환한다.
[ ] 최소·최대 입력 경계가 테스트된다.
[ ] Ollama 연결 실패와 timeout이 예측 가능한 오류로 반환된다.
[ ] 모델 응답 필드 누락이 테스트된다.
[ ] 기존 samples/bench 사용법이 깨지지 않거나 변경점이 문서화된다.
[ ] 모든 자동 테스트가 통과한다.
```

권장 검증 명령:

```bash
pytest
python -m compileall .
```

실제 Ollama가 필요한 시험은 단위 테스트에서 mock하고, 로컬 통합 시험은 별도로 보고한다.

## 인수인계 형식

```markdown
### 결과
완료 / 부분 완료 / 차단

### 변경 파일
- 경로와 변경 이유

### 검증
- 실행 명령과 결과

### 모델·계약 가정
- 사용자가 확정한 내용만 기록

### 남은 결정
- API나 인프라 담당의 확인이 필요한 내용
```
