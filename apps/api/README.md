# Slash | 코어 API

Slash(/)는 자연어 질문과 `/` 슬래시 명령어를 한 입력창에서 처리하는 AI 에이전트 서비스입니다.
이 저장소는 그중 **코어 API** 파트를 담당합니다.

## 역할

- 인증
- 작업 관리
- 실행 위치 결정 (로컬 / 서버)
- DB 연동

## 시작하기

### 요구 사항

- JDK 21
- Docker (로컬 PostgreSQL·Valkey 구동용)

### 로컬 실행

Boot 4.1의 jOOQ 3.21 OSS에 맞춰 **새 PostgreSQL 18 환경**을 사용한다. 기존 `docker-compose.yml`의 PostgreSQL 16 볼륨은 보존한다. 아래 구성은 별도 이름·포트·볼륨으로 시작하며 기존 데이터를 자동으로 옮기지 않는다. [jOOQ 지원 범위](https://www.jooq.org/download/support-matrix)

```bash
# 1. 새 로컬 DB 기동 (PostgreSQL 18, Valkey 8)
docker compose -f docker-compose.boot4.yml up -d --wait

# 2. 앱과 테스트를 새 DB·캐시에 연결
export SPRING_DATASOURCE_URL=jdbc:postgresql://127.0.0.1:15432/slash
export SPRING_DATASOURCE_USERNAME=slash
export SPRING_DATASOURCE_PASSWORD=slash
export SPRING_DATA_REDIS_HOST=127.0.0.1
export SPRING_DATA_REDIS_PORT=16379

# 3. 마이그레이션 적용 + jOOQ 코드 생성 (Gradle DB 설정은 별도로 지정)
./gradlew generateJooq -Pdb.url=jdbc:postgresql://127.0.0.1:15432/slash

# 4. 애플리케이션 실행
./gradlew bootRun
```

테스트도 위 연결 환경에서 `JAVA_TOOL_OPTIONS=-Dspring.test.context.cache.maxSize=4 ./gradlew --max-workers=2 test`로 실행한다. 종료할 때는 `docker compose -f docker-compose.boot4.yml down`을 사용한다. 새 DB 데이터는 유지된다. 기존 PostgreSQL 16 데이터를 이전하는 작업은 별도로 검토한다. 위 구성의 비밀번호는 로컬 시험용 값이며 실제 서비스 자격 증명과 분리한다.

### 로컬 인증

기본은 **임시 인증**이다. 아무 문자열을 Bearer 로 보내면 그 문자열의 사용자가 된다.

```bash
curl -H "Authorization: Bearer alice" http://localhost:8080/api/v1/me
```

실제 Cognito 로 붙으려면 `.env` 에 값을 채운다.
**채우는 순간 임시 인증은 자동으로 꺼진다.** 설정 파일은 고치지 않는다.

```bash
cp .env.example .env    # 값을 채운 뒤
./gradlew bootRun
```

값은 팀 채널에서 받는다. `.env` 는 저장소에 올리지 않는다.

- `COGNITO_ISSUER_URI` 가 전환 스위치다. 이 값이 비어 있으면 나머지를 채워도 임시 인증을 쓴다.
- 발급자만 넣고 나머지를 빠뜨리면 기동 시점에 어떤 값이 없는지 알려주고 멈춘다.
- 시험(`./gradlew test`)은 이 값을 무시한다. 항상 임시 인증으로 돈다.

IDE 에서 실행한다면 `.env` 가 아니라 실행 구성의 환경 변수에 같은 값을 넣는다.
(`.env` 를 읽는 것은 `bootRun` 이다)

### 스키마를 변경할 때

1. `src/main/resources/db/migration/` 에 새 마이그레이션을 추가한다.
   - 파일명 `V{번호}__{설명}.sql`
   - 번호는 서비스 백엔드 담당자가 배정한다
   - **이미 공유된 마이그레이션은 수정하지 않고 새 번호를 추가한다**
2. 위 로컬 실행의 DB 주소를 지정한 `generateJooq`로 적용·재생성한다.
3. 생성 코드(`src/generated`)와 쿼리 시험을 **함께** 커밋한다.

### 디렉터리 구조

```
src/
├── main/
│   ├── java/com/likelion/slash/     # 애플리케이션 코드
│   └── resources/
│       ├── application.yml
│       └── db/migration/            # Flyway 마이그레이션
├── generated/jooq/                  # jOOQ 생성 코드 (커밋 대상, 직접 수정 금지)
└── test/java/com/likelion/slash/
```

### 프로필

| 프로필 | 용도 | DB |
|---|---|---|
| `local` (기본값) | 로컬 개발 | Docker PostgreSQL |
| `dev` | Dev EKS | Dev RDS (`slash_dev`) |
| `demo` | 시연 | Dev RDS (`slash_demo`) |

```bash
# 로컬은 별도 지정 없이 실행하면 된다
./gradlew bootRun

# 다른 프로필로 실행할 때
SPRING_PROFILES_ACTIVE=dev ./gradlew bootRun
```

### 환경 변수

Boot 4 로컬 실행은 위 `SPRING_DATASOURCE_*`·`SPRING_DATA_REDIS_*`를 주입해 별도 PostgreSQL 18·Valkey에 연결한다. 환경 변수를 생략하면 이전 개발 환경의 기본 포트로 연결되므로 두 구성을 혼용하지 않는다.
`dev`·`demo` 는 아래 값을 Secrets Manager 에서 주입한다.

| 변수 | 설명 |
|---|---|
| `DB_URL` | PostgreSQL 접속 주소 |
| `DB_USERNAME` / `DB_PASSWORD` | DB 자격증명 |
| `VALKEY_HOST` / `VALKEY_PORT` | ElastiCache for Valkey |
| `COGNITO_ISSUER_URI` | Cognito User Pool 발급자 주소 |
| `COGNITO_CLIENT_ID` | App Client ID. 다른 Client 의 토큰을 거르는 기준 |
| `COGNITO_USER_INFO_URI` | Hosted UI 의 `/oauth2/userInfo`. 최초 로그인 시 이메일을 받아온다 |
| `CORS_ALLOWED_ORIGINS` | 웹 클라이언트 오리진 (쉼표 구분) |
| `NLU_BASE_URL` | slash-nlu 내부 주소 (예: `http://slash-nlu/internal/v1`) |

> 자격증명을 저장소에 평문으로 두지 않는다. Namespace 를 코드에 고정하지 않는다.

### 코드 규칙

- **시각은 전 구간 한국 시각으로 통일한다.** API·WSS·SQS JSON 은 `2026-08-04T10:47:00+09:00` 형식,
  DB 열은 `timestamptz`, JDBC Session 과 SQL 조회는 `Asia/Seoul` 이다.
  `Instant` 는 오프셋이 없어 항상 `Z` 로 직렬화되므로 DTO 에 사용하지 않고 `OffsetDateTime` 을 쓴다.
  (V001 주석에 남은 "UTC 저장" 표현은 이미 공유된 마이그레이션이라 수정하지 않았다)
- 내부 PK 는 `bigint`, 외부 노출 식별자는 `uuid public_id` 를 사용한다.
- 상태값은 PostgreSQL Enum 대신 `varchar` + `CHECK` 로 관리한다.
- `DSLContext` 는 Repository 계층 안에서만 사용하고, 생성된 jOOQ Record 를 서비스 밖으로 내보내지 않는다.

## 문서

| 문서 | 대상 | 내용 |
|---|---|---|
| [프론트엔드 연동 규약](docs/frontend-api-contract.md) | slash-web | 공통 헤더, 응답·오류 형식, 오류 코드, Cognito 인증 흐름, WSS Ticket |
| [W1-06 WSS 멀티 Pod 라우팅](docs/w1-06-wss-routing.md) | 팀 · slash-infra | Pod 간 이벤트 전달 — 선택지 비교와 채택안(Valkey Pub/Sub) |

## 관련 저장소

| 저장소 | 역할 |
|---|---|
| [slash-web](https://github.com/LikeLionTeam4/slash-web) | 웹 클라이언트 — React·Vite UI, S3/CloudFront 배포 |
| **slash-api** (현재) | 코어 API — 인증, 작업 관리, 실행 위치 결정, DB 연동 |
| [slash-nlu](https://github.com/LikeLionTeam4/slash-nlu) | 자연어 분석 — slash 명령 파싱, 규칙·Kiwi 의도 분류, 인자 추출 |
| [slash-llm](https://github.com/LikeLionTeam4/slash-llm) | LLM 서비스 — Gemma 추론, 요약·대화 생성 |
| [slash-runner](https://github.com/LikeLionTeam4/slash-runner) | PC 작업 실행기 — PC 파일 검색, 상태 조회, 로컬 AI 실행·결과 전달 |
| [slash-infra](https://github.com/LikeLionTeam4/slash-infra) | 인프라 — Terraform(AWS), Helm·ArgoCD 배포 |
| [slash-docs](https://github.com/LikeLionTeam4/slash-docs) | 프로젝트 문서 — 아키텍처, API 계약, ERD, 회의록 |
