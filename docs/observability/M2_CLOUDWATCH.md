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

## 근거 연결을 위한 식별 매핑 — 설계 기준

기존 Metric 이름·차원·발행 방식은 유지한다. 아래 표는 후속 M4 조사에서 출처가 다른 데이터를 같은 대상으로 연결할 때 확인할 기준이다. 공통 로그 필드·Trace 수집·정규화 코드가 이미 구현됐다는 뜻은 아니다.

| 공통 의미 | 현재 출처와 매핑 기준 | 검증·제한 |
| --- | --- | --- |
| 서비스 | CloudWatch `Service=slash-api`, Prometheus `service=slash-api` | 실제 배포의 서비스와 일치해야 한다. |
| 환경 | 이번 AWS 시험의 CloudWatch는 `Environment=dev`, personal profile의 Prometheus는 `environment=personal` | 이 배포의 설정·리소스 식별자로 대응 관계를 확인한다. `personal`이라는 값만 보고 모든 데이터를 dev로 바꾸지 않는다. |
| 계정·리전 | 승인된 계정과 `ap-northeast-2`, 조회한 리소스 ARN·실행 환경 | 지표에 차원을 더하지 않고 조회 대상의 메타데이터로 검증한다. |
| 시각 | Metric의 60초 집계 구간, 원본 로그 시각, 배포 발생 시각 | UTC로 비교하되 집계 구간과 개별 사건 시각의 차이를 보존한다. |
| 요청·Trace | 원본 Log의 실제 요청 ID, 계측된 Trace ID·Span ID | 값이 없으면 미확인으로 남긴다. Metric Dimension에는 넣지 않는다. |
| 배포 버전 | Prometheus의 `version`, 실제 배포·이미지 digest·변경 링크 | 기본값 `unknown`은 버전 근거가 아니다. 배포 시각이 겹친다는 이유만으로 원인으로 확정하지 않는다. |
| 원본 근거 | Namespace·Metric·단위·집계 또는 로그 위치·조회 조건 | 데이터 없음과 조회 실패를 구분하고 토큰·개인정보를 제외한다. |

M2는 집계 지표 5개와 진단 Gauge 1개를 다룬다. 0값·최소 표본·데이터 누락을 구분하고, 평균 지연을 p95로 해석하지 않는다. M4는 먼저 동일 사건의 근거 수집을 확인한 뒤 사실·가설·반대 근거·미확인·다음 조사를 구분하는 AI 보고서를 검증한다. 기존 [M4 계획](https://app.notion.com/p/3ea91c6807b18121b17cf3b7543f23d3)을 연결하며 새 로그 저장소나 Trace 시스템을 이번 작업에 추가하지 않는다.

## 개인 AWS 계정 발행 실측 — 2026-10-02

로컬 `local,m1` API에서 `Environment=local-test`로 발행했다. 오류·API 지연·DB 지연 경로를 각 3회 호출해 HTTP 500×3, 200×6을 확인했다. 서울 리전의 `get-metric-statistics`에서 같은 `Service`/`Environment` 차원과 60초 `Sum`으로 다음 값을 읽었다.

| KST 구간 | RequestCount | ServerErrorCount | RequestDurationMsTotal | DBQueryCount | DBQueryDurationMsTotal | DBConnectionsActive |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 13:54 | 0 | 0 | 0 ms | 19 | 143.96 ms | 0 |
| 13:55 | 9 | 3 | 5550.43 ms | 33 | 2879.64 ms | 0 |

DB 집계에는 앱의 주기 작업 쿼리도 들어간다. 따라서 13:55의 DB 평균 약 87.26 ms는 장애 주입 쿼리 3개의 지연을 그대로 나타내지 않는다. 실제 트래픽에서 임계값과 최소 표본 수를 정해야 한다. 로컬 API와 테스트 컨테이너는 실측 후 종료했다. Terraform Alarm의 AWS `apply`와 ALARM/OK 전이, AWS에 배치한 API·DB의 동작은 아직 검증하지 않았다.

같은 구간에 CloudWatch `GetMetricData`의 Metric Math를 직접 조회해 5xx 비율 33.33%, 평균 API 지연 616.71 ms, 평균 DB 쿼리 지연 87.26 ms를 확인했다. 이 값은 수식 동작 검증이며 Alarm 임계값의 근거로 사용하지 않는다.

## AWS 정상 요청·지표 수신 — 2026-10-29

개인 experiment를 배포해 실제 Cognito 로그인·AWS HTTPS API 검증 17개가 통과했다. 0.5 rps로 180초 동안 trial 90회와 preflight 1회, 총 91회가 모두 200이었다. 인증·경로 프로브는 별도 요청이며, 이번 결과는 정상 동작 기준선이지 부하 한계나 장애 복구 검증이 아니다.

CloudWatch `LambdaOps/Slash`, `Service=slash-api`, `Environment=dev`에서 기존 여섯 지표를 수신했다. 같은 60초 구간의 `Sum`으로 계산한 대표값은 다음과 같다.

| KST 구간 | 요청 수 | 5xx 수 | 평균 API 지연 | DB 쿼리 수 | 평균 DB 지연 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 01:13 | 30 | 0 | 7.98 ms | 55 | 2.50 ms |
| 01:14 | 30 | 0 | 7.59 ms | 55 | 2.69 ms |

평균은 해당 구간의 소요 시간 합계/건수이며 p95가 아니다. 초기 스냅샷의 요청 합계 77은 후속 읽기 조회에서 01:15 구간 23회가 추가되며 최종 100으로 확인됐다. 5xx 합계는 0이었다. 정상 관찰기 91회 외에 추가 인증·경로 검사가 있고 집계 범위가 달라, 개별 요청과 지표의 완전한 대응을 증명한 것은 아니다. 초기 77을 유실 건수로 해석하지 않는다. API가 조용한 구간에도 DB 쿼리가 있어 배경 작업의 영향을 구분해야 한다. `/actuator` 요청은 발행 집계에서 제외되고 `DBConnectionsActive=0`은 발행 순간 표본이다.

최초 ElastiCache 생성은 HTTP 408 `InvalidCredentialsException`으로 실패했으며 재계획·재시도로 생성했다. 오류 원인은 확정하지 않았다. 실제 ALB 404는 Gateway URI의 stage·경로와 Grafana proxy 매핑을 명시해 보완했다. 빈 Cloud Map health 설정·Gateway 기본 오류 템플릿·접근 정책 ARN 정규화 차이를 정리한 뒤 최종 재계획은 `No changes`였다. [실행·검증 근거](results/2026-10-29-baseline-runtime/index.json)와 [배포·정리 기록](../../infra/personal/README.md)을 연결한다.

첫 시험 후 사용자의 삭제 중단 요청이 있었고 01:29 KST 읽기 조회에서 서버·API·DB·캐시 제거와 VPC·private subnet 2개·보안 그룹 2개 잔존을 확인했다. 이 상태는 당시 기록이며 이후 승인받은 재배포로 단계별 요청 시험을 진행했다.

### 후속 단계별 요청의 안전 중단

0.5·1·2 rps 단계는 각각 60·120·240회를 완료했다. 5 rps 단계는 600회 중 288회에서 멈췄다. 클라이언트가 측정한 `sequence=699` 응답이 2,054.693 ms로 2초 기준을 넘었기 때문이다. 단계 요청 708회와 사전 확인 1회는 모두 HTTP 200이지만 시간 기준 실패 1건이 있어 **전체 FAIL, 확인 항목 15/17 통과**로 기록한다. 사후 조회는 발송하지 않았고 마지막 단계는 미완료다. 단계별 평균·p95는 [실행 결과 표](../../infra/personal/README.md#추가-재배포단계별-요청영상--실행-결과)에 정리했다. 이 시간은 TLS·네트워크를 포함하므로 서버 병목이나 5 rps 처리 한계로 단정하지 않는다.

요청 종료 후 120초 수집 대기를 거쳐 기존 여섯 지표를 수신했다. 원본 스냅샷의 `RequestCount` 합계 716은 정상 관찰 709회와 앱에 도달한 별도 인증 요청 7회의 합과 같고, `ServerErrorCount`는 0이다. 별도 관리 경로 2회는 Gateway 403으로 앱까지 도달하지 않았다. 집계 숫자는 맞지만 개별 요청 추적에 의한 완전 대응을 검증한 것은 아니다. 기존 `/actuator` 제외·DB 배경 쿼리·발행 시점 표본의 해석은 유지한다.

실제 브라우저 화면의 1초 간격 캡처를 40초 영상으로 묶고 시간 생략과 조기 중단을 표시했다. [후속 요청·지표·영상 근거](results/2026-10-29-step-demo/index.json)를 첫 시험과 구분한다. 배포 해시를 설정 파일과 입력값 기준으로 보완한 뒤 최종 Terraform 재계획은 `No changes`였다. 02:30 KST [정리 후 실제 조회 59/59](results/2026-10-29-step-demo/cleanup-verification.json)를 통과했다. 시험용 자원과 Terraform 관리 항목은 모두 정리됐으며 Cognito·ECR·기존 LambdaOps와 비활성 수집 상태는 유지했다. 보존 자원이 있으므로 계정 전체 비용 0을 뜻하지 않는다. DB 장애 도구의 High 4건, 비허용 IP의 실제 거부·세 Alarm 전환·M3 종단 경로는 미해결·미검증이다. M2·M3는 In Progress를 유지한다.

### 지연 구간 측정 보강 — 로컬 검증

이후 보강에서는 클라이언트 전체 시간을 준비·DNS·TCP 연결·TLS·전송·응답 헤더 대기·본문 수신·검증·정리로 나눴다. 기존 2초 정지 기준과 요청량은 유지한다. 요청마다 생성한 probe UUID, 앱 응답 UUID, Gateway extended request ID를 허용 목록으로 기록한다. 앱은 개인 환경의 `GET /api/v1/me`에만 인증 필터 전부터 처리 종료까지의 시간과 상태를 JSON으로 남긴다. 토큰·본문·사용자 정보·원문 IP는 기록하지 않고 요청 ID를 지표 라벨로 사용하지 않는다.

| 로컬 검증 | 결과 |
| --- | --- |
| 합성 HTTPS 서버에서 헤더 전 150ms 대기 | `response_headers_wait` 151.008ms |
| 합성 HTTPS 서버에서 본문 전 150ms 대기 | `response_body` 160.289ms |
| 제한 시간·미신뢰 인증서 | 중단 구간과 미완료 `null`을 기록, TLS 검증 유지 |
| 자동 검사 | 요청·보고서 69개, 앱 인증·지표 회귀 47개, 인프라 35개 통과. Terraform 형식·구성 검사 통과 |
| 과거 파일 재분석 | 709건 모두 구간 측정값이 없어 기존 2,054.693ms의 원인은 미확정 |

앱 시간과 클라이언트 시간은 측정 범위가 겹치므로 더하거나 차이를 네트워크 시간으로 단정하지 않는다. 저장한 요청과 앱 로그를 비교하는 `latency_report.py`는 ID가 충돌하면 연결하지 않으며, AWS 호출 없이 과거 전체 시간만 있는 기록도 구분한다. [측정 계약·사용법](../../observability/personal/requests/README.md#지연-구간과-같은-요청의-앱-기록-비교)과 [로컬 검증 근거](results/2026-10-29-latency-instrumentation.json)를 연결한다.

위 계측 구현 시점에는 코드·설정과 로컬 검증까지만 진행했다. 후속 2026-10-29 작업에서 새 API 이미지 `m2-20261029-latency1`을 만들어 ECR에 게시했으며 로컬·원격 digest 일치를 확인했다. 실제 Gateway 헤더 전달과 앱 로그 연결은 여전히 환경 검증 전이다. 서울 REST Gateway 공용 로그 역할이 없어 요청별 Gateway 내부 시간 로그는 켜지 않았고, 일반 ALB access log도 활성화하지 않았다.

| 후속 이미지 검사 | 결과 |
| --- | --- |
| ECR Basic / Trivy OS 73개 | 각각 검출 0건 |
| Trivy Java 124개 | Critical 10·High 41·Medium 45·Low 9, 총 105개 패키지 검출·고유 CVE 104개 |
| 배포 판정 | 보안 보완 전 후보로 보관. 기존 선택 이미지로 승격하지 않음 |
| Terraform 검토 | 구성 검사 통과, 인증 조건에서 plan 차단. 부분 생성 93·변경/삭제 0. 전체 예상 98은 최종 계획 수치가 아님 |
| 실제 실행 | apply·서버 생성·부하 및 장애 시험 없음. experiment state 0 유지 |

Java 검출은 이전 ECR Basic의 운영체제 검사와 범위가 다르다. 위 표는 최초 후보 검사 기록이다. [최초 검사·독립 검토 근거](results/2026-10-29-api-image-security-review.json)와 [자원·비용 계획](../../infra/personal/README.md#새-api-이미지-검사배포-검토--게시-완료-배포-보류)을 연결한다.

이후 승인된 기존 계열 Java 보완에서 변경 전 551개·변경 후 566개 테스트가 모두 통과했다. 새 15개는 실제 로컬 서명 검증과 응답 보안 헤더 검사이며 실제 Cognito 로그인은 아니다. CI의 API job도 임시 DB·캐시를 사용하는 전체 검사로 확대했다. 새 `m2-20261029-javafix1` 이미지를 같은 도구·취약점 DB로 재검사한 결과는 **Java Critical 10→2·High 41→0·Medium 45→2·Low 9→0, OS 0 유지**다.

새 이미지의 실제 로컬 기동 검사 28개도 통과했다. 합성 발급자 JWT의 `/me`·오류 처리·지표 포트 격리·WebSocket 연결과 접속표 재사용 차단, 응답 ID와 지연 JSON 4건의 일대일 연결을 확인했다. 실제 Cognito·Gateway 검증이나 AWS 지연 원인 확인은 아니다. 검증용 컨테이너·네트워크·임시 DB·합성 인증자료를 정리했다.

남은 Spring Framework 두 건은 무료 수정판이 큰 버전 전환을 요구하므로 사용 조건·전환 범위를 별도로 검토한다. 스캐너와 공급자 심각도를 구분하고 실제 악용 가능성 미검증·미해결 상태를 유지한다. 검사 예외를 추가하지 않았다. [패치·테스트·재검사 근거](results/2026-10-29-java-security-remediation.json)에 상세 결과를 기록한다. 새 이미지는 로컬 후보이며 ECR 추가 게시·선택 이미지 승격·AWS 서버 생성·실제 장애 시험은 하지 않았다. DB 장애 도구의 기존 High 4건은 별개로 미해결이다. 기존 여섯 지표·Alarm·Incident 계약과 M2·M3 In Progress 상태는 유지한다.

## AWS 시험 준비 — 2026-10-28

이 절은 당시 개인 ECS 시험 환경의 설정과 실행 방법을 정의한 기록이다. 이후 AWS 배포·정상 지표 수신은 위 2026-10-29 실행에서 확인했으며 Alarm 전이는 아직 별도 환경 검증이다. 기존 `local,m1` 장애 API와 `personal`의 인증·프로필 제한은 유지한다.

### 발행 설정과 IAM을 함께 켜기

`infra/personal/experiment`에 `enable_cloudwatch_metrics`를 추가했다. 기본값은 `false`이며 LambdaOps용 `terraform.tfvars.example`에는 `true`를 명시했다. 실제 사용하려면 개인 tfvars에 값을 옮긴 뒤 계획을 검토한다. 이 값만으로 task를 시작하거나 Alarm을 생성하지 않는다. `enable_workloads` 등 기존 실행 조건을 만족한 후 배포해야 지표가 발행된다.

| 설정 | 이번 시험 값 | 이유 |
| --- | --- | --- |
| 리전 | `ap-northeast-2` | LambdaOps와 같은 서울 리전에서 관측한다. |
| Namespace | `LambdaOps/Slash` | 기존 Alarm이 읽는 지표 묶음과 일치시킨다. |
| 차원 | `Service=slash-api`, `Environment=dev` | 다른 서비스·환경의 데이터가 섞이지 않게 한다. |
| 주기 | 60,000 ms | 기존 60초 `Sum` 기반 Alarm 계약을 사용한다. |
| DB 계측 | `query-metrics.enabled=true` | DB 쿼리 수와 소요 시간 합계를 실제 앱에서 측정한다. |
| Prometheus | 기존 `environment=personal` 유지 | 별도 관측 체계의 태그이며 CloudWatch 차원과 독립적이다. |

Terraform이 ECS 환경변수 `SLASH_OBSERVABILITY_CLOUDWATCH_ENABLED/NAMESPACE/SERVICE/ENVIRONMENT/PUBLISHINTERVALMS`와 `AWS_REGION`을 넣는다. 예약된 값은 `api_environment`의 같은 키보다 우선한다. YAML의 기본값을 직접 켜지 않으므로 개인 앱을 로컬에서 실행하는 것만으로 AWS 전송을 시작하지 않는다. 과거에는 ECS에서 `false`를 강제했지만 이제 전용 변수로 발행과 IAM을 함께 제어한다.

권한은 앱이 AWS SDK를 사용할 때 받는 `core_task`에 부여한다. 이미지를 받거나 로그·비밀번호를 주입하는 `core_execution` 역할과 구분한다.

| 정책 항목 | 허용 범위 |
| --- | --- |
| Action | `cloudwatch:PutMetricData`만 허용 |
| Resource | `*` — 이 작업은 개별 metric ARN으로 범위를 제한하지 않음 |
| Condition | `StringEquals`로 namespace=`LambdaOps/Slash`, 요청 리전=`ap-northeast-2` |
| 생성 조건 | `enable_cloudwatch_metrics=true` |
| 제외 | Alarm 생성·변경, 다른 namespace 전송, DB 관리 권한 |

`Resource=*`의 범위는 조건으로 제한한다. AWS 액세스 키를 앱 환경변수나 저장소에 넣지 않고 ECS task 자격증명을 사용한다. 하나의 task 안의 컨테이너는 task 역할을 공유하므로, 이 권한을 API 컨테이너만의 격리 권한으로 설명하지 않는다. 기본 `api-baseline`은 API 하나만 실행한다.

근거: [CloudWatch namespace 제한](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/iam-cw-condition-keys-namespace.html), [ECS task 역할](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-iam-roles.html).

### 첫 장애 시험: DB 조회 대기

첫 시험 대상은 합성 데이터만 있는 개인 RDS PostgreSQL과 `GET /api/v1/me`다. LambdaOps Incident 저장소인 Aurora DSQL에는 장애 SQL을 실행하지 않는다. 정상 Cognito 토큰으로 `/me`를 먼저 호출해 사용자 생성과 외부 userInfo 호출을 마친 뒤 기준선을 측정한다. 이후 `/me`는 `public.users`를 조회하므로, 이 테이블을 잠깐 잠그면 앱의 실제 DB 쿼리와 API 응답이 함께 늦어진다.

```text
VPC 안의 일회성 DB 작업 → users 잠금 → 3초 후 ROLLBACK
                                  ↑
정상 로그인 /me 요청 → DB 조회 대기 → HTTP 200
                                  ↓
앱의 쿼리·HTTP 타이머 → CloudWatch → 지연 Alarm 판단
```

SQL은 [db-query-delay.sql](../../observability/personal/sql/db-query-delay.sql)에 있다. 데이터나 스키마는 수정하지 않는다. 한 번 실행할 때 잠금 획득 대기는 최대 1초, 정상 보유 시간은 3초다. 문장 제한 5초와 트랜잭션 유휴 제한 5초를 둔다. SQL 파일은 `psql -X --file=db-query-delay.sql`로 비대화형 실행한다. 정상 종료는 `ROLLBACK`, 오류 시 `ON_ERROR_STOP`에 따라 `psql`이 종료되어 연결을 반납한다. 대화형으로 붙여넣어 실행하는 방식은 사용하지 않는다. 실행 클라이언트가 멈춘 경우에도 유휴 제한으로 잠금이 해제되지만, 모든 실패 상황이 정확히 3초 이내에 끝난다는 뜻은 아니다.

AWS 실행 경로는 **입력 포트가 없는 일회성 PostgreSQL client ECS task**로 준비한다. 기존 VPC에서 private RDS로 TLS 접속하며, 전용 실행 역할에 그 실험 DB secret 읽기만 허용하고 비밀번호는 ECS가 주입한다. DB 접속용 보안 그룹도 별도로 제한한다. 실행 이미지는 digest로 고정한다. 후속 준비에서 이 작업의 Terraform·이미지·실행 도구를 작성했다. [배포 준비 현황](../../infra/personal/README.md#배포-전-준비와-계획)을 따른다. 실제 AWS 실행은 아직 검증하지 않았다. 현재 API task에 ECS Exec가 설정됐다고 가정하지 않는다.

| 순서 | 작업 | 남길 근거 |
| --- | --- | --- |
| 1 | `/me` 정상 200과 실제 CloudWatch 지표 수신 확인 | 시간, 요청 수, 정상 API·DB 평균, JWT 만료 여유 |
| 2 | DB 작업 한 개가 잠금을 획득한 뒤 정상 `/me` 요청을 보냄 | 잠금 획득·요청 시작 시각, 대상 DB/task 식별자 |
| 3 | SQL 종료 후 지연된 200과 다음 요청의 정상 200 확인 | 응답 시간, HTTP 상태, 잠금 해제와 작업 종료 |
| 4 | 같은 60초 구간의 API·DB 수와 시간 합계를 대조 | CloudWatch 원본 값, 평균 수식 결과, 앱 지표 |
| 5 | 실측 기준과 최소 표본 수를 정한 뒤, 횟수·총 시간을 제한해 반복 | ALARM/OK 이력 또는 전이하지 않은 이유 |

직접 실행한 `pg_sleep`는 앱 계측 대상이 아니다. 반드시 동시에 `/me`가 DB를 기다려야 한다. 기존 `me-baseline.js`는 정상 기준선용이며 p95 500ms 제한이 있으므로 장애 시험에 그대로 사용해 성공 판정을 내리지 않는다. 장애용 요청 실행기는 별도로 준비하고 요청 수·타임아웃·실패 응답을 기록해야 한다.

### 세 Alarm과 시험 증거의 관계

| Alarm | 시험 방법 | 현재 준비 수준·한계 |
| --- | --- | --- |
| 평균 DB 지연 | 위 잠금으로 실제 `/me` 쿼리를 기다리게 함 | SQL 작성 및 로컬 잠금 동작 확인. 실제 앱/RDS 실행은 후속 검증 |
| 평균 API 지연 | 같은 요청의 HTTP 소요 시간 관측 | DB 지연에 따른 API 지연이다. 독립적인 API 처리 지연 실험은 아님 |
| 5xx 비율 | 후속: 시험 잠금 때문에 기다리는 앱 쿼리 한 건을 선별 취소 | 제한된 취소 실행기·로컬 검증 준비. 실제 AWS 500·오류 지표는 미검증 |

5xx 시험은 DB·앱 DB 사용자·정확한 core task IP·앱 이름·Lock 대기 상태와 `pg_blocking_pids`의 시험 잠금 PID를 함께 확인해 **정확히 한 세션**만 일치할 때 `pg_cancel_backend`로 현재 쿼리만 취소하는 방식으로 구현했다. 0개/복수이면 취소하지 않고 잠금을 해제한다. 기본 JDBC 앱 이름만으로 세션을 고르지 않는다. 취소 신호 성공은 HTTP 500 증거가 아니므로 실제 응답과 `ServerErrorCount` 증가를 따로 검증한다. 기본 지연 SQL과 분리된 `db-query-cancel-one.sql`을 명시적 `--mode cancel-one`에서만 실행한다. 실행 방법과 로컬 검증 범위는 [DB 이미지](../../observability/personal/db-test/README.md)를 참고한다.

세 Alarm의 최종 검증은 모두 필요하다. 단발 3초 지연만으로 완료 처리하지 않는다. 기존 M2 기본값은 최근 세 개의 60초 구간 중 두 구간 초과이며, 최소 요청/쿼리 수는 실측 후 입력한다. DB 집계에는 주기 작업도 포함되어 평균이 희석될 수 있다. publisher는 분 경계에 정확히 맞추는 방식이 아니므로 준비·종료 구간을 구분한다. 요청이 적어서 수식이 0이 되거나 데이터가 누락되어 OK가 된 것을 서비스 복구 증거로 사용하지 않는다.

[PostgreSQL 잠금과 해제](https://www.postgresql.org/docs/16/sql-lock.html), [문장·유휴 제한](https://www.postgresql.org/docs/16/runtime-config-client.html)을 기준으로 작성했다.

### 검증 상태

2026-10-28 로컬 확인 결과다. AWS `apply`, 지표 전송, 부하·장애 주입은 실행하지 않았다.

| 검사 | 결과 | 검증 범위 |
| --- | --- | --- |
| Java 설정·발행·개인 환경 제한 | 19개 통과, 실패·건너뜀 0 | 실제 personal YAML 및 ECS 환경변수 바인딩, AWS client mock, 기존 지표 재전송·관리 포트·프로필 제한 |
| Terraform 인프라 경계 | 11개 통과 | 새 namespace/리전 제한·역할 분리·opt-in과 기존 네트워크·수명 제한 |
| Terraform | `fmt -check`·experiment `validate` 통과 | 잠금 파일의 AWS 6.66.0/random 3.9.1 사용. plan/apply는 미실행 |
| 임시 PostgreSQL 18.4 | 3가지 동작 통과 | 실제 조회 약 2.973초 대기 후 데이터 불변, 잠금 획득 실패 시 종료, 멈춘 연결 약 5.001초 뒤 자동 해제 |
| 임시 DB 정리 | 완료 | 서버 종료 및 테스트 데이터 디렉터리 삭제 |
| 메인·서브 검토 | 완료 | 지표 계약 일치, IAM 범위, 기존 제한 유지 및 검증 한계 확인 |

Java 검사는 `apps/api`에서 `./gradlew test --offline --tests 'com.likelion.slash.observability.*' --tests 'com.likelion.slash.config.PersonalRuntimeConfigTest'`로, 인프라 검사는 저장소 루트에서 `python3 -m unittest discover -s infra/personal/tests -v`로 실행할 수 있다. DB 검증은 별도 임시 DB에 합성 `users` 한 행을 만들고 같은 SQL 파일을 비대화형 `psql`로 실행한 결과다. 앱 HTTP·Cognito·RDS의 검증은 포함하지 않는다.

위 표는 초기 지표 설정 검증 기록이다. 이후 일회성 DB 작업·요청·로그인 도구와 도메인 없는 HTTPS 코드를 준비했다. 후속 작업에서 Cognito/ECR 생성, 이미지 게시, LambdaOps 운영자 로그인·HTTP 조회 인증을 확인했다. API·Grafana OS 패키지 보완으로 Critical 0건을 확인했다. 추가 이미지 보완·재검사로 High는 21건에서 DB 시험 이미지의 4건으로 줄었다. experiment 계획은 생성 후보 100개를 계산했지만 실제 Slash 토큰 검증이 없어 기존 인증 조건에서 차단됐다. 후속 실제 Cognito·로컬 personal API 검증 21개가 통과했고, 없는 경로의 500을 404로 보완한 이미지를 게시했다. [로그인 검증 근거](results/2026-10-28-slash-cognito-local-verification.json)에 결과를 기록했다. 2026-10-29에는 DB 장애 도구를 제외하고 실제 인증 근거·최신 이미지·시험 IP·종료 시각을 반영한 [정상 동작 계획](results/2026-10-29-baseline-deployment-plan.json)을 만들었다. 이 계획 검토 단계는 생성 97·변경 0·삭제 0으로 성공했다. 후속 승인으로 실제 AWS 배포·정상 요청·여섯 지표 수신까지 검증했으며 첫 정상 시험·후속 단계별 요청의 중단 결과와 자원 정리 상태는 위 2026-10-29 기록을 따른다. High 4건은 해결로 표시하지 않으며 DB 장애 도구를 사용하기 전에 별도 보완·검토한다. 정상 기준선을 확보한 뒤 별도 승인한 장애 시험으로 세 Alarm 전이와 M3 저장·조회 경로를 검증한다. M2/M3의 완료 기준은 유지한다.


### 후속 준비: 일회성 작업과 요청 실행기

2026-10-28 `observability/personal/db-test`, `task`, `requests`에 실행기와 검증을 추가했다. DB 작업은 기본 3초 지연 한 번이며, 반복 설정도 전체 시간 제한을 적용한다. 실제 요청은 정상 Cognito 토큰으로 HTTPS `/me`를 호출하고 시각·상태·시간만 기록한다. 새 작업 정의와 전용 SG/IAM은 `infra/personal/experiment/db-test.tf.json`에 있다. 생성과 실행은 분리했다.

로컬 API/Grafana/Prometheus/DB 시험 이미지는 모두 `linux/amd64`로 준비했다. 후속 작업에서 operator client와 scope를 포함한 foundation을 생성 17·변경 0·삭제 0으로 실제 적용했다. Cognito 설정·로그인 폼과 빈 ECR 저장소를 확인했고 재계획도 변경 0개였다. [검증 근거](results/2026-10-28-foundation-provision.json)를 참고한다. 개인 도메인 없이 접속하는 REST API→VPC Link V2→내부 ALB를 코드로 구성했다. 이전 15개 계획은 이 변경 전의 준비 기록이다. 후속 단계에서 이미지 4종을 ECR에 게시하고 실제 Cognito operator 로그인·LambdaOps 빈 목록 200·무토큰 401·읽기 권한 없음 403을 확인했다. [이미지 게시·보안 검사](results/2026-10-28-image-publication.json)의 보완 상태를 실제 배포 전에 확인한다. Slash 웹 client의 실제 Cognito 토큰과 로컬 /me 검증은 완료했다. 후속 Fargate/RDS의 실제 `/me`·CloudWatch 정상 수신은 검증했다. Alarm 전이와 실제 Incident 상세 200은 아직 미검증이다.
