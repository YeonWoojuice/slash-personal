# Slash | 프로젝트 문서

Slash(/)는 자연어 질문과 `/` 슬래시 명령어를 한 입력창에서 처리하는 AI 에이전트 서비스입니다.
이 저장소는 **어느 한 저장소에도 속하지 않는 공통 문서** 파트를 담당합니다.

## 문서 경계

폴리레포라 문서가 흩어지기 쉽습니다. 아래 기준으로 위치를 정합니다.

**여기(slash-docs)에 둡니다**

- 전체 아키텍처 다이어그램 · 컴포넌트 간 데이터 흐름
- 서비스 간 API 계약 (`web ↔ api ↔ nlu/llm ↔ agent`)
- ERD · 데이터 모델
- 회의록 · 일정 · 의사결정 기록
- 발표 자료

**각 저장소 README에 둡니다**

- 그 저장소의 실행 방법 · 환경변수 · 의존성
- 그 저장소의 디렉터리 구조 · 내부 설계

기준은 하나입니다. **두 개 이상의 저장소가 합의해야 하는 내용이면 여기, 한 저장소 안에서 끝나는 내용이면 그 저장소 README.** API 계약을 `slash-api`에만 두면 프론트·에이전트 담당이 보지 않고, 7곳에 복사하면 곧바로 어긋납니다.

## 문서 목록

### API 계약

| 문서 | 내용 | 상태 |
|---|---|---|
| [api/intents.md](./api/intents.md) | 명령(intent) 목록·인자·제어 명령 | 초안 |
| [api/nlu.md](./api/nlu.md) | `slash-api` ↔ `slash-nlu` 호출 규격 | 초안 |
| [api/llm.md](./api/llm.md) | `slash-api` ↔ `slash-llm` 호출 규격 | 초안 |

> **초안**은 작성자가 제안한 상태이며 팀 합의 전입니다. 합의된 항목은 상태를 `확정`으로 바꿉니다.

## 관련 저장소

| 저장소 | 역할 |
|---|---|
| [slash-web](https://github.com/LikeLionTeam4/slash-web) | 웹 클라이언트 — React·Vite UI, S3/CloudFront 배포 |
| [slash-api](https://github.com/LikeLionTeam4/slash-api) | 코어 API — 인증, 작업 관리, 실행 위치 결정, DB 연동 |
| [slash-nlu](https://github.com/LikeLionTeam4/slash-nlu) | 자연어 분석 — slash 명령 파싱, 규칙·Kiwi 의도 분류, 인자 추출 |
| [slash-llm](https://github.com/LikeLionTeam4/slash-llm) | LLM 서비스 — Gemma 추론, 요약·대화 생성 |
| [slash-agent](https://github.com/LikeLionTeam4/slash-agent) | 로컬 에이전트 — PC 파일 검색, 상태 조회, 로컬 AI 실행·결과 전달 |
| [slash-infra](https://github.com/LikeLionTeam4/slash-infra) | 인프라 — Terraform(AWS), Helm·ArgoCD 배포 |
| **slash-docs** (현재) | 프로젝트 문서 — 아키텍처, API 계약, ERD, 회의록 |
