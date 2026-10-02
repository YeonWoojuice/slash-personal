# M2 CloudWatch 계측 계약

`slash-api`의 M1 Micrometer 계측에서 **여섯 개 지표만** CloudWatch에 발행한다. 기본값은 비활성이다. M1의 Prometheus/Grafana 실행과 장애 주입 경로는 바꾸지 않는다.

| Metric (`LambdaOps/Slash`) | 1회 발행 값 | CloudWatch 조회 통계 |
| --- | --- | --- |
| `RequestCount` | 새 HTTP 요청 수 | `Sum` |
| `ServerErrorCount` | 새 HTTP 5xx 수 | `Sum` |
| `RequestDurationMsTotal` | 새 HTTP 요청의 총 소요 시간(ms) | `Sum` |
| `DBQueryCount` | 새 jOOQ 쿼리 수 | `Sum` |
| `DBQueryDurationMsTotal` | 새 jOOQ 쿼리의 총 소요 시간(ms) | `Sum` |
| `DBConnectionsActive` | 발행 시점의 Hikari 활성 연결 수(풀 합계) | `Sum` |

차원은 `Service=slash-api`, `Environment=<명시 값>` 두 개뿐이다. `/actuator/**` 요청은 제외한다. `uri`, `method`, `status`, `version`, `pool`, SQL 및 사용자 값은 CloudWatch 차원에 넣지 않는다. 첫 다섯 집계 지표는 각 지표의 해당 이벤트가 없는 주기에도 0을 발행한다. `DBConnectionsActive`는 60초 간격의 순간값이므로 짧은 연결 급증은 놓칠 수 있다. 인스턴스마다 주기당 한 표본일 때 `Sum`은 인스턴스별 활성 연결을 합산하지만, 응답 유실 뒤 재시도한 표본이 중복 수락되면 값이 부풀 수 있다. 이 지표는 진단용이며 첫 3개 장애 알람에는 사용하지 않는다. AWS에 RDS를 배치할 경우 서버 측 `AWS/RDS`의 `DatabaseConnections`도 별도로 확인한다.

설정 예시(로컬 M1에서 개인 AWS 계정에 시험 발행):

```bash
export AWS_PROFILE=<개인 AWS 프로필>
export AWS_REGION=ap-northeast-2
export SLASH_OBSERVABILITY_CLOUDWATCH_ENABLED=true
export SLASH_OBSERVABILITY_CLOUDWATCH_ENVIRONMENT=local-test
# 필요할 때만 변경: SLASH_OBSERVABILITY_CLOUDWATCH_NAMESPACE=LambdaOps/Slash
# 기본 발행 간격은 60초. 60초 미만은 허용하지 않는다.
SPRING_PROFILES_ACTIVE=local,m1 ./gradlew bootRun
```

SDK 기본 자격증명 체인을 사용하며 자격증명은 저장소에 쓰지 않는다. 이 기능을 켜는 역할에는 해당 namespace의 `cloudwatch:PutMetricData`만 허용한다. 설정한 리전과 계정에서 지표를 확인한다. Hikari 풀이 생성되기 전에는 `DBConnectionsActive` 시계열이 없다. API 외 배포 환경에서 `SLASH_OBSERVABILITY_QUERY_METRICS_ENABLED=true`를 별도로 설정해야 한다. 이를 빠뜨리고 CloudWatch 발행을 켜면 앱은 시작하지 않는다. M1 밖에서는 장애 주입 경로를 만들지 않는다.

알람 계산은 같은 기간·차원의 `Sum`을 사용한다. `5xx 비율 = ServerErrorCount / RequestCount`, `평균 API 지연(ms) = RequestDurationMsTotal / RequestCount`, `평균 DB 지연(ms) = DBQueryDurationMsTotal / DBQueryCount`. 분모가 0인 조용한 기간과 실제 텔레메트리 누락은 구분해 알람 수식을 작성해야 한다. 집계값에는 원 요청별 분포가 없으므로 p95를 계산하거나 표시하지 않는다.

전송 실패 시 동일 timestamp의 데이터 묶음을 다음 주기에 다시 보내고, 성공한 뒤에만 카운터 기준점을 이동한다. AWS가 데이터를 수락한 뒤 응답만 실패한 경우 중복 가능성은 남는다.

## 개인 AWS 계정 발행 실측 — 2026-10-02

로컬 `local,m1` API에서 `Environment=local-test`로 발행했다. 오류·API 지연·DB 지연 경로를 각 3회 호출해 HTTP 500×3, 200×6을 확인했다. 서울 리전의 `get-metric-statistics`에서 같은 `Service`/`Environment` 차원과 60초 `Sum`으로 다음 값을 읽었다.

| KST 구간 | RequestCount | ServerErrorCount | RequestDurationMsTotal | DBQueryCount | DBQueryDurationMsTotal | DBConnectionsActive |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 13:54 | 0 | 0 | 0 ms | 19 | 143.96 ms | 0 |
| 13:55 | 9 | 3 | 5550.43 ms | 33 | 2879.64 ms | 0 |

DB 집계에는 앱의 주기 작업 쿼리도 들어간다. 따라서 13:55의 DB 평균 약 87.26 ms는 장애 주입 쿼리 3개의 지연을 그대로 나타내지 않는다. 실제 트래픽에서 임계값과 최소 표본 수를 정해야 한다. 로컬 API와 테스트 컨테이너는 실측 후 종료했다. Terraform Alarm의 AWS `apply`와 ALARM/OK 전이, AWS에 배치한 API·DB의 동작은 아직 검증하지 않았다.
