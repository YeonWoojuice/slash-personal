# Slash | LLM 서비스

Slash(/)는 자연어 질문과 `/` 슬래시 명령어를 한 입력창에서 처리하는 AI 에이전트 서비스입니다.
이 저장소는 그중 **LLM 추론** 파트를 담당합니다.

## 역할

- Gemma 모델 실행
- 요약 생성

현재 MVP는 `TEXT_SUMMARY`만 제공한다. 일반 대화와 SQS worker는 구현 범위가 아니다.

## 시작하기

### 1. Ollama 준비

```bash
# https://ollama.com 에서 설치 후
ollama pull gemma3:4b
```

### 2. 실행

```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

### 3. 확인

브라우저에서 http://localhost:8000/docs

Backend 연동 및 향후 SQS adapter 경계는
[`docs/BACKEND_CONTRACT.md`](docs/BACKEND_CONTRACT.md)에 정리돼 있습니다.

### 컨테이너 실행

Ollama와 모델은 애플리케이션 이미지에 포함하지 않습니다. 별도로 실행한 Ollama의
주소를 `OLLAMA_URL`로 주입합니다.

```bash
docker build -t slash-llm:local .
docker run --rm -p 8000:8000 \
  --add-host host.docker.internal:host-gateway \
  -e OLLAMA_URL=http://host.docker.internal:11434 \
  slash-llm:local
curl http://localhost:8000/health
```

`--add-host`는 Linux Docker에서 필요하며 Docker Desktop에서도 사용할 수 있습니다.

컨테이너는 비루트 사용자로 실행됩니다. `dev` 또는 `main` 브랜치에 반영되면 GitHub
Actions가 `sha-<commit>` 태그로 ECR에 이미지를 게시합니다.
동일 커밋의 이미지가 이미 있으면 immutable 태그를 다시 게시하지 않고 성공 처리합니다.
실제 dev 배포에는 `slash-infra`의 `values-dev.yaml` 이미지 태그와 `OLLAMA_URL`
갱신이 별도로 필요합니다.
현재 Helm 기준 Kubernetes Service는 `80`에서 컨테이너 `8000`으로 전달합니다.
Ollama 배치 방식과 GPU, SQS worker·재시도·DLQ 정책은 아직 확정 계약이 아니므로 이
이미지에는 포함하지 않습니다.

### 환경변수

| 이름 | 기본값 | 설명 |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` | Ollama 주소 |
| `LLM_MODEL` | `gemma3:4b` | 사용할 모델 |
| `LLM_TIMEOUT` | `120` | 응답 대기 시간(초) |
| `LLM_READY_TIMEOUT` | `2` | Ollama readiness 확인 제한 시간(초) |
| `SUMMARY_MIN_CHARS` | `150` | 요약 요청 최소 글자 수 |
| `SUMMARY_MAX_CHARS` | `8000` | 모델에 전달할 최대 글자 수 |
| `LLM_MAX_CONCURRENT_REQUESTS` | `1` | 프로세스당 동시 모델 호출 수 |
| `LLM_BUSY_RETRY_AFTER` | `1` | 과부하 응답의 재시도 권고 시간(초) |

### API

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/health` | 상태 확인 |
| `GET` | `/ready` | Ollama 연결 및 설정 모델 준비 확인 |
| `POST` | `/internal/v1/llm/summary` | 텍스트 요약 |

`/health`는 LLM API 프로세스의 생존만 확인합니다. `/ready`는 Ollama의
`/api/tags`를 조회하며 연결할 수 없거나 `LLM_MODEL`이 없으면 `503`을 반환합니다.
Kubernetes에서는 `/health`를 liveness/startup, `/ready`를 readiness probe로 사용합니다.

```bash
curl -X POST http://localhost:8000/internal/v1/llm/summary \
  -H "Content-Type: application/json" \
  -d '{"text": "요약할 긴 글"}'
```

기존 요청과 응답은 그대로 사용할 수 있다.

```json
{
  "text": "150자 이상의 요약할 원문"
}
```

```json
{
  "summary": "생성된 요약",
  "model": "gemma3:4b"
}
```

요청 추적이 필요하면 `requestId`, `taskId`를 선택적으로 전달한다. 제공한 값만
성공 또는 오류 응답에 그대로 포함된다.

```json
{
  "text": "150자 이상의 요약할 원문",
  "requestId": "request-1",
  "taskId": "task-1"
}
```

150자 미만은 `400`으로 거부하고, 8000자 초과 입력은 기존 동작과 같이 앞의
8000자만 모델에 전달한다.

### 오류 응답

```json
{
  "error": {
    "code": "MODEL_TIMEOUT",
    "message": "모델 응답 시간이 초과되었다.",
    "retryable": true
  },
  "requestId": "request-1",
  "taskId": "task-1"
}
```

| HTTP | 코드 | 재시도 | 조건 |
|---:|---|---:|---|
| 400 | `INPUT_TOO_SHORT` | 아니요 | 공백 제거 후 150자 미만 |
| 503 | `MODEL_UNAVAILABLE` | 예 | Ollama 연결 실패 |
| 503 | `MODEL_BUSY` | 예 | 동시 모델 호출 한도 초과; `Retry-After` 포함 |
| 504 | `MODEL_TIMEOUT` | 예 | Ollama timeout |
| 502 | `UPSTREAM_ERROR` | 예 | Ollama 4xx/5xx 응답 |
| 502 | `INVALID_MODEL_RESPONSE` | 예 | 비 JSON, 필드 누락, 빈 결과 |

Pydantic 요청 형식 검증 실패는 FastAPI 기본 `422` 응답을 사용한다.

사용자/IP별 요청 횟수 제한은 인증 정보를 가진 `slash-api`가 담당합니다. 권장
계약은 HTTP `429`, 오류 코드 `RATE_LIMITED`, `Retry-After` 헤더입니다. 이
서비스의 `MODEL_BUSY`는 사용자 제한이 아니라 Ollama 자원 보호용입니다.

## 테스트

자동 테스트는 실제 Ollama를 호출하지 않는다.

```bash
pytest
python -m compileall .
```

### 팀 통합 스모크 테스트

`slash-nlu`와 `slash-llm`을 같은 상위 폴더에 두고, 두 저장소에서 각각
가상환경과 의존성 설치를 마친 뒤 실행합니다.

```text
slash/
├── slash-nlu/
└── slash-llm/
```

```bash
cd slash-llm
.venv/bin/python scripts/team_demo.py
```

위 명령은 가짜 Ollama와 NLU·LLM 서버를 임시 포트에 실행하고 파일 검색,
상태 조회, 누락 인자, NLU→LLM 요약, 미지원 명령까지 5개 계약을 확인한 뒤
모두 종료합니다. 모델 설치 없이 팀원이 API 연결을 빠르게 확인할 때 사용합니다.

### dev 배포 스모크 테스트

배포된 LLM API와 실제 Ollama 모델의 연결은 아래 스크립트로 확인합니다. 스크립트는
`/health`, `/ready`, `/internal/v1/llm/summary`를 차례로 호출하고 모델명과 추적 ID를
검증합니다. 합성 입력만 사용하며 입력 원문과 요약 결과는 출력하지 않습니다.

```bash
LLM_SMOKE_BASE_URL=http://<slash-llm-address> \
  .venv/bin/python scripts/smoke_dev.py
```

서비스가 클러스터 내부에만 열려 있으면 먼저 port-forward를 사용합니다.

```bash
kubectl -n <namespace> port-forward svc/slash-llm 18000:80
LLM_SMOKE_BASE_URL=http://127.0.0.1:18000 \
  .venv/bin/python scripts/smoke_dev.py
```

기대 모델이 다르면 `LLM_SMOKE_MODEL`을 설정합니다. probe 제한 시간은
`LLM_SMOKE_PROBE_TIMEOUT`(기본 10초), 실제 요약 제한 시간은
`LLM_SMOKE_SUMMARY_TIMEOUT`(기본 180초)으로 따로 조정할 수 있습니다. 성공하면 실제
요약 처리 시간도 출력합니다. Ollama EC2가 정지된 시간에는 `/ready`가 `503`을 반환하는
것이 정상이며, 실제 추론 검증은 EC2 가동 시간에 실행해야 합니다.

실제 Ollama와 `gemma3:4b`를 준비했다면 다음과 같이 모델 호출까지 확인합니다.

```bash
ollama serve
.venv/bin/python scripts/team_demo.py --real-ollama
```

이 테스트는 현재 구현된 NLU와 LLM의 직접 HTTP 연동만 검증합니다. Backend의
Task API와 로컬 Agent가 연결되기 전까지 Web→Backend→Agent 전체 E2E로 보지 않습니다.

실제 모델을 포함한 로컬 수동 시험은 서버와 Ollama를 실행한 뒤 진행한다.

```bash
python samples.py
python bench.py
```

## 관련 저장소

| 저장소 | 역할 |
|---|---|
| [slash-web](https://github.com/LikeLionTeam4/slash-web) | 웹 클라이언트 — React·Vite UI, S3/CloudFront 배포 |
| [slash-api](https://github.com/LikeLionTeam4/slash-api) | 코어 API — 인증, 작업 관리, 실행 위치 결정, DB 연동 |
| [slash-nlu](https://github.com/LikeLionTeam4/slash-nlu) | 자연어 분석 — slash 명령 파싱, 규칙·Kiwi 의도 분류, 인자 추출 |
| **slash-llm** (현재) | LLM 서비스 — Gemma 추론, 요약·대화 생성 |
| [slash-runner](https://github.com/LikeLionTeam4/slash-runner) | PC 작업 실행기 — PC 파일 검색, 상태 조회, 로컬 AI 실행·결과 전달 |
| [slash-infra](https://github.com/LikeLionTeam4/slash-infra) | 인프라 — Terraform(AWS), Helm·ArgoCD 배포 |
| [slash-docs](https://github.com/LikeLionTeam4/slash-docs) | 프로젝트 문서 — 아키텍처, API 계약, ERD, 회의록 |
