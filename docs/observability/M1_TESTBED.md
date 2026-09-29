# M1: Slash API 관측 Testbed

## 대상과 선정 이유

개인용 Slash 저장소의 `apps/api` 한 서비스와 로컬 PostgreSQL 16을 대상으로 한다. 이 API는 인증·작업 요청을 처리하며 jOOQ로 PostgreSQL에 직접 접근한다. 따라서 한 서비스만 실행해도 HTTP 오류·지연과 DB 쿼리 지연을 함께 관찰할 수 있다. `apps/web`, `apps/nlu`, `apps/llm`, `apps/agent` 및 `infra/reference`는 이 Testbed의 실행 대상이 아니다. API 실행에는 기존 로컬 구성에 따라 Valkey도 필요하다.

## 시작

JDK 21과 Docker Desktop이 필요하다. M1은 별도 Compose 프로젝트와 데이터 볼륨을 사용한다. 기존 API Compose의 호스트 5432/6379와 충돌하지 않도록 PostgreSQL은 `127.0.0.1:15432`, Valkey는 `127.0.0.1:16379`에 연다. Prometheus는 `127.0.0.1:19090`, Grafana는 `127.0.0.1:13000`에 연다. 기존 로컬 DB는 이 실험에서 사용하지 않는다.

저장소 루트에서 터미널 두 개를 연다.

```bash
# 터미널 1: M1 전용 의존 서비스와 관측 스택
docker compose -f observability/m1/compose.yaml up -d
```

```bash
# 터미널 2: API. 기존 로컬 DB/Valkey 대신 M1 전용 포트 사용
cd apps/api
SPRING_PROFILES_ACTIVE=local,m1 \
SPRING_DATASOURCE_URL=jdbc:postgresql://localhost:15432/slash \
SPRING_DATA_REDIS_PORT=16379 \
./gradlew bootRun
```

M1 프로필에서는 API가 `127.0.0.1:8080`에만 바인딩된다. Prometheus는 Docker Desktop의 `host.docker.internal:8080`을 5초마다 스크레이프한다. 이 연결은 macOS Docker Desktop에서 검증했다. 다른 환경에서 호스트나 포트를 바꾼다면 [`prometheus.yml`](../../observability/m1/prometheus/prometheus.yml)의 target을 함께 바꾼다.

Grafana는 `http://127.0.0.1:13000`에서 열고 `admin` / `slash-m1-local`로 로그인한다. 로컬 암호를 바꾸려면 Compose 실행 전에 `M1_GRAFANA_ADMIN_PASSWORD`를 설정한다. 이미 만들어진 Grafana 볼륨이 있으면 최초 설정된 암호가 유지된다. `Slash M1 / Slash API | M1 Testbed` 대시보드와 Prometheus 데이터 소스는 시작할 때 자동 등록된다.

## 수집 확인

먼저 요청을 하나 만들고 API의 표준 메트릭 endpoint를 확인한다.

```bash
curl -fsS -H 'Authorization: Bearer alice' http://127.0.0.1:8080/api/v1/me
curl -fsS http://127.0.0.1:8080/actuator/prometheus | rg 'http_server_requests_seconds_count|hikaricp_connections_active|slash_db_query_seconds_count'
```

`http://127.0.0.1:19090/targets`에서 `slash-api-m1`의 상태가 `UP`인지 확인한다. Grafana 대시보드는 요청률, 5xx 비율, 평균 요청 지연, Hikari 연결 수, DB 쿼리 평균·p95 지연의 다섯 패널을 제공한다. 패널은 최근 15분을 5초마다 갱신한다. 요청 직후 그래프가 비어 있다면 최소 두 번의 스크레이프가 끝난 뒤 다시 본다.

## Metric과 Label

| 관측 항목 | Prometheus 시계열 | Label |
| --- | --- | --- |
| 요청 수 | `http_server_requests_seconds_count` | `service`, `environment`, `version`, `uri`, `method`, `status` |
| 5xx 비율 | 요청 수 시계열에서 `status=~"5.."` / 전체로 계산 | 위와 같음 |
| 요청 지연 | `http_server_requests_seconds_sum` / `_count` | 위와 같음 |
| DB 연결 | `hikaricp_connections_active`, `_idle` 등 | `service`, `environment`, `version`, `pool` |
| DB 쿼리 지연 | `slash_db_query_seconds_sum`, `_count`, `_bucket` | `service`, `environment`, `version` (`_bucket`에는 `le` 추가) |

`service=slash-api`, `environment=local`은 이 실행의 고정 값이다. `version`은 `SLASH_VERSION` 환경 변수에서 읽으며, 미설정 시 `local`이다. HTTP의 `uri`는 실제 URL 대신 Spring이 매칭한 경로 템플릿으로, M1에서 말하는 `endpoint` 역할을 한다. 예를 들어 `/api/v1/tasks/{taskId}`의 ID 값은 라벨에 들어가지 않는다. 사용자 ID, 요청 본문·쿼리 문자열, SQL 원문·매개변수, 임의의 예외 메시지도 라벨로 사용하지 않는다.

Prometheus에서 직접 확인할 때는 다음 PromQL을 사용한다. 짧은 실험에서 `rate` 값이 비어 있으면 요청을 반복하고 두 번 이상 스크레이프될 때까지 기다린다.

```promql
sum by (uri, method, status) (rate(http_server_requests_seconds_count{service="slash-api",uri!~"/actuator.*"}[1m]))
sum(rate(http_server_requests_seconds_count{service="slash-api",status=~"5..",uri!~"/actuator.*"}[1m])) / clamp_min(sum(rate(http_server_requests_seconds_count{service="slash-api",uri!~"/actuator.*"}[1m])), 1e-9)
sum by (uri) (rate(http_server_requests_seconds_sum{service="slash-api",uri!~"/actuator.*"}[1m])) / clamp_min(sum by (uri) (rate(http_server_requests_seconds_count{service="slash-api",uri!~"/actuator.*"}[1m])), 1e-9)
hikaricp_connections_active{service="slash-api"}
histogram_quantile(0.95, sum by (le) (rate(slash_db_query_seconds_bucket{service="slash-api"}[1m])))
```

## 첫 장애 실험

M1 전용 `local,m1` 프로필과 `slash.observability.faults.enabled=true`가 함께 설정될 때만 아래 경로를 사용할 수 있다. 운영 프로필에서는 노출되지 않는다. 지연값은 0~5000ms로 제한된다. 각 실험을 몇 번 반복한 뒤 두 번 이상 스크레이프가 진행되면 패널의 변화를 볼 수 있다.

```bash
# ① 특정 API에서 500 응답: Request rate와 5xx error ratio 확인
curl -i -H 'Authorization: Bearer alice' \
  http://127.0.0.1:8080/internal/m1/error

# ② 특정 API 응답 지연: Request latency 패널 확인
curl -sS -o /dev/null -w 'HTTP %{http_code}, elapsed %{time_total}s\n' \
  -H 'Authorization: Bearer alice' \
  'http://127.0.0.1:8080/internal/m1/latency?delayMs=1500'

# ③ PostgreSQL 쿼리 지연: DB query latency 패널 확인
curl -sS -o /dev/null -w 'HTTP %{http_code}, elapsed %{time_total}s\n' \
  -H 'Authorization: Bearer alice' \
  'http://127.0.0.1:8080/internal/m1/db-latency?delayMs=1500'
```

①은 HTTP 500, ②와 ③은 약 1.5초 뒤 HTTP 200이 예상된다. ③은 쿼리 타이머의 합계와 횟수를 늘린다. 짧은 지연 중 Hikari `active` 게이지는 스크레이프 시점에 따라 순간 증가를 놓칠 수 있다.

## 실행 검증 (2026-09-30, macOS Docker Desktop)

JDK 21과 Docker Desktop에서 위 구성으로 실제 실행했다. `/actuator/prometheus`는 HTTP 200, Prometheus target은 `UP`(`up=1`), Grafana API에서 5개 패널과 DB 지연 패널의 평균·p95 쿼리가 등록된 것을 확인했다. API는 `127.0.0.1:8080`에만 바인딩된 상태에서도 컨테이너의 scrape가 성공했다.

각 장애를 1200ms 설정으로 5회 재현했다. 오류 경로는 5회 모두 HTTP 500, API 지연 경로는 5회 모두 HTTP 200과 평균 1.216초, DB 지연 경로는 5회 모두 HTTP 200과 평균 1.222초였다. Prometheus에 세 경로의 요청 횟수 5건씩과 5xx 5건이 저장됐고, DB 쿼리 p95는 실험 직후 1분 창에서 약 1.33초였다. Hikari idle connection 시계열도 수집됐다. 이 수치는 로컬 실험값이며 부하 시험 기준은 아니다.

## 종료

API 프로세스를 중지한 뒤 저장소 루트에서 `docker compose -f observability/m1/compose.yaml down`을 실행한다. 데이터 볼륨은 삭제하지 않는다.

## 현재 범위와 다음 결정

M1은 개인 저장소의 로컬 API·PostgreSQL·Valkey와 Prometheus/Grafana에 한정한다. 운영 클러스터의 `/actuator/prometheus` 접근 정책, 장기 저장·알림, 버전 값의 배포 파이프라인 연결, 다른 서비스의 메트릭 표준은 후속 단계에서 정한다. `infra/reference`의 과거 팀 AWS 설정은 실행하지 않는다.
