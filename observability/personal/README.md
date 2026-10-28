# 개인 AWS API 관측 실험

2026-10-28 기준. 첫 시험 대상은 Cognito 인증을 거친 Slash의 `GET /api/v1/me`다. Cognito·ECR foundation은 실제 생성했으며, Slash 실행 환경 배포·이미지 게시·장애 실행은 아직 하지 않았다. 전체 리소스·계획·비용·삭제 절차는 [개인 Terraform](../../infra/personal/README.md)을 기준으로 한다.

## 연결

| 구성 | 역할·접근 범위 |
| --- | --- |
| REST API → VPC Link V2 → 내부 ALB | AWS 기본 HTTPS 주소 제공. 시험자 IPv4 정책 적용. 개인 도메인 불필요 |
| Slash API | ECS에서 `personal` profile 실행. 앱 8080, 내부 management 9091 |
| Prometheus | 별도 관측 task에서 Cloud Map `core.<name>.internal`을 10초마다 발견하고 9091 `/actuator/prometheus`를 15초마다 수집 |
| Grafana | 같은 관측 task의 `127.0.0.1:9090`에 접속. 외부에는 `/m2/grafana/`로 제공 |
| CloudWatch | `LambdaOps/Slash`, `Service=slash-api`, `Environment=dev`, 60초 발행. 명시적으로 켜야 실행 |

Prometheus 웹 서버는 loopback에만 연결한다. Grafana는 로그인·Secure 쿠키를 사용하며 암호는 Secrets Manager에서 ECS로 주입한다. 태스크는 인터넷에서 8080/9091/3000 포트로 직접 접근할 수 없다. VPC 내부 API·지표 통신은 HTTP다.

`personal`은 다른 profile과 함께 실행할 수 없고 Cognito 설정 누락, 임시 인증, 장애 API 활성화를 기동 실패로 처리한다. `/internal`, `/actuator`, 기타 업무 API는 외부에서 열지 않는다. full 기능·NLU·AI inference·WebSocket은 이번 시험 범위에 없다.

## 준비한 도구

| 경로 | 하는 일 | 기본 제한 |
| --- | --- | --- |
| [db-test](db-test/README.md) | RDS에 TLS로 연결하는 일회성 이미지 | 외부 포트 없음, 합성 DB만 허용, 시간 제한 |
| [task](task/README.md) | 미리 정한 ECS DB 시험 작업 한 개 시작·종료 확인 | 기본은 미실행 미리보기, 명시적 실행 필요 |
| [requests](requests/README.md) | 로그인한 `/me` 요청 상태·시간 기록 | HTTPS, 토큰·응답 본문 저장 안 함, 요청 수·시간 제한 |
| [auth](auth/README.md) | LambdaOps용 code+PKCE 로그인·읽기 API 검증 | private 토큰 파일, 목록·상세 200/401/403 확인 |
| [k6/me-baseline.js](k6/me-baseline.js) | 정상 성능 기준선 | 5 RPS × 5분. 장애 관측 성공 판정에 사용하지 않음 |

기본 DB 시험은 `users` 잠금을 3초 보유해 실제 `/me` 조회를 기다리게 한다. `cancel-one`은 명시적으로 선택한 경우에만 정확한 앱 IP·DB 사용자·쿼리·자신의 잠금 대기 관계를 확인해 현재 문장 하나를 취소한다. 연결 종료나 데이터 변경은 하지 않는다. 취소 신호와 실제 HTTP 500·이후 200은 별도로 확인한다. LambdaOps의 DSQL은 시험 대상이 아니다.

## 실제 배포·시험 순서

1. 계정 `642935793048`·서울 리전에 foundation 17개 자원을 생성했고 재계획 변경 0개를 확인했다. 다음 실행에서도 같은 계정·상태 파일을 사용한다.
2. API·Grafana·Prometheus·DB 시험 이미지를 ECR에 게시하고 manifest digest를 확보한다. 로컬 이미지 ID를 대신 쓰지 않는다.
3. 실제 Cognito 출력, 시험자 IPv4/32, 종료시각, 이미지 digest를 experiment 입력에 넣고 새 계획을 검토한다.
4. 배포 후 `api_base_url`을 사용한다. 기본 stage는 `m2`다. 웹은 localhost:5173의 code+PKCE callback을 사용하며 토큰은 저장소·로그·채팅에 남기지 않는다.
5. 정상 토큰 `/me` 200, 무토큰 401, IP 제한·공개 경로 차단, Grafana 로그인, Prometheus와 CloudWatch의 실제 수집을 확인한다.
6. 기준선 → 제한된 지연 → 단일 오류 시험 순서로 진행한다. 세 Alarm의 최소 표본·임계값은 실측으로 결정한다.
7. LambdaOps의 실제 이벤트 처리와 로그인된 목록·상세 조회를 검증한다. [M2 계약](../../docs/observability/M2_CLOUDWATCH.md)의 완료 기준을 유지한다.
8. 요청 결과·작업 종료·지표·Alarm 이력을 내보낸 뒤 experiment 전체를 삭제하고 잔여 자원을 확인한다. foundation은 별도다.

관측 task의 TSDB·Grafana 변경은 일시적이다. task 재시작·삭제 전에 필요한 결과를 내보낸다. `expires_at`은 자동 삭제 기능이 아니며 ECS 작업만 멈춰도 ALB/RDS/Valkey 등은 과금될 수 있다.

## 로컬 검증과 환경 검증

로컬에서 personal 설정·JWT·계측, Terraform 구성, 요청·작업·로그인 도구와 임시 TLS PostgreSQL의 제한 동작을 확인한다. Grafana의 `/m2/grafana/` health·로그인·정적 파일·Secure 쿠키도 로컬에서 확인했다. CI는 AWS 자격증명이나 배포 단계를 갖지 않는다.

실제 Cognito 로그인·ECR pull·Gateway stage 전달·IP 차단·ECS/RDS·CloudWatch·세 Alarm 전이·M3 전체 흐름은 아직 환경 검증 대상이다. 예전 2026-10-07 개인 도메인/ACM 기반 계획은 현재 도메인 없는 구성으로 대체했다. 당시 로컬 실측 파일은 별도 기존 결과로 남긴다.

참고: [Prometheus DNS discovery](https://prometheus.io/docs/prometheus/latest/configuration/configuration/), [Grafana reverse proxy](https://grafana.com/tutorials/run-grafana-behind-a-proxy/).
