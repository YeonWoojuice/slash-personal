# 일회성 AWS 테스트 환경

2026-10-29 기준. 첫 AWS 시험에서 실제 Cognito·HTTPS API 검증 17개, 정상 요청 91회 모두 200, CloudWatch 지표 6종 수신을 확인했다. 후속 단계별 요청 시험은 **0.5·1·2 rps 단계를 완료했으나, 5 rps 단계에서 응답 1건이 2초 기준을 넘어 안전 중단**됐다. 정상 요청 관찰 709회는 모두 HTTP 200이지만 전체 시험은 FAIL이며 마지막 단계와 사후 조회가 미완료다. 02:30 KST 최종 조회 59/59를 통과해 재시험용 자원 정리를 확인했다. Terraform 관리 자원은 0개다. Cognito·ECR foundation과 기존 LambdaOps는 유지한다. DB 장애 도구의 High 4건, 장애 시험·세 Alarm 전이·M3 종단 검증은 미해결·미검증 상태다. 기존 팀 환경과 `infra/reference`의 state는 사용하지 않는다.

## 구성과 수명

| Terraform 루트 | 포함 자원 | 시험 종료 후 |
| --- | --- | --- |
| `foundation` | ECR 저장소 6개와 lifecycle policy, 개인 Cognito pool·웹 client·LambdaOps operator client·scope·로그인 domain | 다음 시험에 재사용 가능. 이미지 저장·인증 사용료는 별도 |
| `experiment` | VPC, REST API, VPC Link V2, 내부 ALB, API·관측 ECS, RDS PostgreSQL, Valkey, private DNS, IAM·secret·로그, 선택적인 DB 시험 task definition | 결과를 내보낸 뒤 루트 전체 삭제 |

웹은 로컬 `http://localhost:5173`에서 실행한다. foundation과 experiment는 각각 독립적인 **로컬 state**를 사용하며 같은 PC에서 한 사람만 실행한다. CI는 검사만 수행한다. CI OIDC·자동 배포·여러 작업자를 위한 remote state는 이번 범위에 없다.

```text
시험자 PC → AWS 제공 HTTPS 주소 /m2
              ↓ 시험자 IPv4 허용 정책
          Regional REST API
              ↓ VPC Link V2
          내부 HTTP ALB
              ├─ /m2/api/v1/me → stage 제거 → Slash API
              └─ /m2/grafana/ → Grafana

Slash API → private RDS·Valkey
          → CloudWatch 지표 → LambdaOps M2 Alarm (별도 구성)
Prometheus → 내부 API 지표 수집 → Grafana
```

개인 도메인·ACM 인증서는 필요 없다. `api_base_url` 출력은 `https://{id}.execute-api.ap-northeast-2.amazonaws.com/m2` 형태다. PC→Gateway는 HTTPS, VPC 내부는 HTTP다. HTTP API 상품의 resource policy 미지원 때문에 시험자 IP 제한을 지원하는 **REST API**를 사용했다. VPC Link V2가 ALB에 직접 연결하므로 NLB는 추가하지 않는다.

## 실행 범위와 제한

- `api-baseline`만 지원한다. 외부 API는 `GET /api/v1/me`와 `OPTIONS`, 관측 화면은 Grafana만 연다. 내부·관리·그 밖의 업무 경로는 공개하지 않는다.
- `full` 모드는 현재 계약 검사에서 거부한다. REST 경로에는 WebSocket을 연결하지 않으며 Grafana Live도 비활성이다. NLU·inference·PC 작업은 실행하지 않는다.
- 시험자 IPv4 CIDR은 REST 리소스 정책에서 제한한다. ALB에는 VPC Link SG만 접근한다. API/Grafana는 ALB SG, 메트릭 9091은 관측·ALB SG, DB는 API·선택한 시험 SG만 허용한다.
- 앱은 전달 헤더를 신뢰하지 않는다(`SERVER_FORWARD_HEADERS_STRATEGY=none`, `TRUSTED_PROXY_HOPS=0`). IP 제한은 Gateway가 담당하며, API는 기존 Cognito JWT 검증을 유지한다.
- 기본 API는 1 vCPU/3GiB, 관측은 1 vCPU/2GiB, 각각 Fargate task 하나다. 태스크의 public IP 두 개는 이미지·로그·Cognito 등의 HTTPS 외부 연결에 사용한다. NAT Gateway·유료 interface endpoint는 없다.
- RDS는 `db.t4g.small` Single-AZ, 암호화 gp3 20GB다. Valkey는 TLS/AUTH를 사용하는 `cache.t4g.micro` 단일 노드다. 고가용성 구성이 아니다.
- **합성 데이터 전용**이다. DB 백업 0일·최종 snapshot 생략·삭제 보호 없음, Valkey snapshot 없음, 로그 보존 1일이다. destroy하면 DB·캐시·로그가 삭제된다.
- 짧은 시험에서는 API DB 계정이 Flyway를 실행한다. 운영용 DDL 계정 분리나 migration task를 대신하는 설계가 아니다.
- ECS 롤링 배포는 최소 0%·최대 100%로 잠시 중단을 허용한다. 관측 저장소도 일시적이므로 task 교체 전에 필요한 결과를 내보낸다.
- `expires_at`은 종료시각을 기록한 태그다. **자동 삭제 기능은 아니다.**

## 로그인 두 종류

| 용도 | Cognito client·callback | 검증 대상 |
| --- | --- | --- |
| Slash 시험 요청 | 기존 웹 client, `http://localhost:5173/callback` | Slash의 access token·client·issuer 검사와 `/me` |
| LambdaOps 장애 조회 | 별도 operator client, `http://localhost:8765/callback` | `lambdaops/incidents.read` scope를 가진 토큰으로 목록·상세 조회 |

같은 개인 pool을 재사용한다. operator client 분리는 사용자별 관리자 권한이나 소유권 필터를 만드는 기능이 아니다. 현재 개인 pool의 초대 사용자는 operator 로그인을 이용할 수 있다. 새 인증 체계를 추가하지 않고 M3의 기존 JWT 설정에 foundation 출력을 연결한다. [로그인·조회 검증 도구](../../observability/personal/auth/README.md)를 따른다.

## 배포 전 준비와 계획

Terraform 1.5 이상, AWS CLI, Docker, 개인 AWS 자격증명이 필요하다. 승인된 대상은 `642935793048`, 서울 `ap-northeast-2`이며 현재 확인한 IAM 사용자는 `Yeonu`다. 적용 직전에도 계정과 실행 주체를 확인한다. state에는 secret이 들어가므로 디렉터리 권한을 보호하고 state·plan·실제 tfvars·토큰을 커밋하지 않는다.

```sh
aws sts get-caller-identity
umask 077
cd infra/personal/foundation
cp terraform.tfvars.example terraform.tfvars
# account_id=642935793048, name=slash-lab 등 실제 입력
terraform init
terraform validate
terraform plan -out=/private/tmp/slash-foundation.tfplan
terraform show /private/tmp/slash-foundation.tfplan
# 생성 목록 검토가 끝난 뒤에만 apply
```

foundation은 **생성 17·변경 0·삭제 0으로 적용 완료**했으며, 재계획 결과 추가 변경은 0개다. 기존 15개 계획에 Cognito resource server와 operator client 2개를 추가한 구성이다. ECR 6개 중 이번에 게시한 이미지는 API·Prometheus·Grafana·DB 시험 이미지 네 개다. NLU/inference 이미지는 게시하거나 실행하지 않는다. 이전 계획과 이미지 준비 결과는 [당시 근거](../../docs/observability/results/2026-10-28-deployment-preparation.json)에 남겨 두며, 코드가 바뀐 이전 계획을 적용하지 않는다.

실제 Cognito 출력과 ECR 저장소 주소를 확보했다. Cognito domain은 ACTIVE이며 초대 사용자의 첫 로그인과 code+PKCE 토큰 발급에 성공했다. 사용자의 `CONFIRMED` 상태와 이메일 소유 확인은 별개다. 현재 `email_verified=false`이므로 이메일 검증 완료로 기록하지 않는다.

API·Prometheus·Grafana·DB 시험 이미지 4개를 ECR에 게시했다. Grafana·Prometheus·DB 보완 이미지는 `m2-20261028-highfix1`, 로그인 검증에서 발견한 오류 처리를 수정한 API는 `m2-20261028-authfix1`이다. 최신 참조는 [기존 이미지 근거의 `current_image_selection`](../../docs/observability/results/2026-10-28-image-publication.json)에 연결했다. ECR Basic은 지원 OS 패키지 검사이며 앱 전체의 안전을 보장하지 않는다.

| 이미지 | 보완한 내용 | 재검사 결과 | 로컬 확인 |
| --- | --- | --- | --- |
| API | 없는 경로를 500 대신 기존 404 오류로 처리 | 새 이미지 검출 0건 | 실제 Cognito·로컬 API의 정상/반복 조회·인증 거부·지표 격리 등 21개 확인 |
| Grafana 12.4.0 | zlib·musl 등 6개 설치 패키지 갱신 | High 5→0, 전체 검출 0건 | 로그인·정적 파일·보안 쿠키·대시보드·실제 Prometheus 조회 |
| Prometheus 3.15.0 | 공식 distroless 기반으로 BusyBox·셸 제거, 설정을 빌드 시 포함 | High 4→0, 전체 검출 0건 | DNS 수집·TSDB 쓰기와 재시작·loopback·비루트 등 11개 확인 |
| DB 시험 클라이언트 | PostgreSQL 서버·libxml2·GnuPG 제거, 설치 패키지 142→101개 | High 12→4, Medium 9·Low 3 | TLS·대상 제한·정확한 쿼리 선택·강제 종료 등 15개 테스트 |

DB의 남은 High는 glibc 2건·zlib 1건·Cyrus SASL 1건이다. 검토 시 Debian 13 stable 수정 패키지가 없었으며 unstable 패키지를 섞지 않았다. 해당 SASL 플러그인 부재와 일부 직접 호출 부재는 확인했지만 전체 위험 해소로 해석하지 않는다. zlib 적용 버전 설명의 불일치도 미확인으로 남겼다. [DB 이미지의 항목별 근거](../../observability/personal/db-test/README.md)에 따라 수정판과 실제 적용 조건을 다시 확인한다. 위험을 자동 수락하거나 검사 항목을 숨기지 않았다.

Prometheus 설정은 [이미지 준비 도구](../../observability/personal/prometheus/README.md)로 빌드한다. 게시 후 같은 ECR digest를 확인하고 `image.py contract`로 이름·설정 해시를 검증해 만든 입력 파일을 계획에 함께 전달한다. 이미지와 대상 이름·설정이 다르면 계획이 거부된다. 로컬 image ID만으로 게시 완료를 판단하지 않는다.

### 로그인 검증 전 Terraform 검토와 후속 결과

실제 Cognito 출력, 게시된 ECR digest 4개, 현재 시험자 IPv4 `/32`를 사용해 계획을 실행했다. **생성 후보 100개·변경 0개·삭제 0개가 계산됐지만, 인증 사전 검증 조건에서 계획이 실패했다.** 적용 가능한 최종 계획이 아니며 `apply`·서버 생성·AWS 장애 시험은 실행하지 않았다. [기존 준비 근거의 `experiment_review_after_high_remediation`](../../docs/observability/results/2026-10-28-deployment-preparation.json)에 계획 종료 코드와 차단 원인을 기록했다. 실제 IP·tfvars·원본 계획 출력은 공개하지 않는다.

`cloud_contract_verified=false`를 유지했다. 기존 JWT 단위 테스트·가짜 OIDC의 401 검사는 **실제 Cognito 토큰을 사용하는 Slash `/me` 성공**을 증명하지 않는다. LambdaOps operator client의 조회 성공도 Slash 웹 client 검증을 대신하지 않는다. 후속 작업에서 실제 Slash용 토큰으로 로컬 personal API의 정상·반복 200, 잘못된 토큰 401, 지표 격리까지 21개 항목을 확인했다. [실제 로그인 결과](../../observability/personal/auth/README.md)에 근거를 기록했다. 이후 아래 2026-10-29 정상 동작 계획에서 실제 인증 근거를 확인하고 조건 값을 true로 반영했다. 이전 차단 계획은 당시 기록이며 재사용하지 않는다. 배포 후 ECS의 실제 경로 검증은 별도로 수행한다.

### 정상 동작용 계획 검토 — 2026-10-29

실제 Cognito 웹 client, 수정 API와 Prometheus·Grafana의 ECR digest, 현재 시험자 IPv4 `/32`로 **저장 가능한 Terraform 계획을 만들었다. 생성 97·변경 0·삭제 0이며, 이 중 AWS 자원 선언은 94개이고 나머지 3개는 비밀번호 생성·계약 검사다.** 서버 97대를 의미하지 않는다. `fmt -check`·`validate`와 계획의 사전 조건이 통과했다. 기존 로그인 검증 21개와 API 이미지 일치를 확인한 뒤 `cloud_contract_verified=true`로 설정했다.

| 구분 | 이번 계획 | 목적 |
| --- | --- | --- |
| API 실행 | Fargate 1개, 1 vCPU/3GiB | 실제 Cognito 로그인과 정상 `/me` 확인 |
| 관측 실행 | Fargate 1개, 1 vCPU/2GiB, Prometheus·Grafana | 내부 지표 수집과 화면 확인 |
| DB·캐시 | RDS PostgreSQL 1개, Valkey 1개 | 합성 사용자 데이터 저장과 앱 연결 |
| 접속·네트워크 | REST API, VPC Link V2, 내부 ALB, VPC·SG 등 | 시험자 IP로 접속을 제한하고 내부 자원을 격리 |
| 지표 전송 | CloudWatch 지표 6종과 제한된 task 권한 | AWS 실행 환경의 정상 기준선 확인 |
| DB 장애 도구 | `enable_db_test_task=false`, 이미지 입력도 제외 | 미해결 High 4건이 있는 시험 도구의 배포를 막음 |

API·Prometheus·Grafana의 게시된 linux/amd64 manifest와 기존 완료된 ECR Basic 검사 결과(각 검출 0건)를 다시 조회했다. 새 검사를 실행한 것은 아니며 앱 전체의 취약점이 없다는 뜻도 아니다. Prometheus 이미지의 대상 이름·설정 해시 계약도 통과했다. High 4건의 해결 상태는 바꾸지 않는다.

[계획·교차 검토 근거](../../docs/observability/results/2026-10-29-baseline-deployment-plan.json)에 실행 입력의 의미와 생성 목록을 정리했다. 실제 IP·tfvars·원본 계획·secret은 공개하지 않는다. 계획 통과는 AWS의 실제 기동·IP 차단·RDS 접속·지표 수신 검증과 구분한다. LambdaOps의 DSQL·Lambda·SQS와 M2 Alarm은 이번 계획에 포함하지 않는다.

계획의 종료 시각은 비용 비교용 4시간 가정이며 실행 예약이 아니다. 실제 배포 승인 후 시험자 IP·종료 시각·계정·이미지 상태를 다시 확인하고 새 계획을 만든다. `expires_at`은 자동 삭제나 비용 상한을 보장하지 않는다. 이 계획 검토 시점에는 실제 서버 생성과 장애 시험을 실행하지 않았다. 이후 배포·정상 검증과 삭제 중단 결과는 아래 실제 AWS 검증 기록에 구분해 남긴다.

```sh
cd ../experiment
cp terraform.tfvars.example terraform.tfvars
# 실제 Cognito 출력, API/Prometheus/Grafana digest 세 개, 시험자 IPv4/32, 종료 시각 입력
# enable_db_test_task=false, images에서 db-test 제외
# 실제 로컬 로그인 근거 확인 후 cloud_contract_verified=true
# api_stage_name=m2, cors_allowed_origin=http://localhost:5173
terraform init
terraform validate
terraform plan -var-file=/private/tmp/prometheus-image-contract.tfvars.json -out=/private/tmp/slash-experiment.tfplan
terraform show /private/tmp/slash-experiment.tfplan
# 실제 생성 목록·실행 시간·비용을 확인한 뒤에만 apply
```

`enable_workloads=false`여도 apply하면 ALB/RDS/Valkey 등이 생성되어 과금된다. 설정 확인만 할 때는 validate/plan에서 멈춘다. workload 실행에는 `cloud_contract_verified=true`, 실제 Cognito·이미지 계약 확인이 필요하다. `enable_cloudwatch_metrics`는 지표 발행과 task IAM을 함께 켠다. `enable_db_test_task=true`는 시험 task **정의**만 생성하며 작업을 자동 실행하지 않는다.

정상 배포·검증은 아래 기록까지 진행했다. 다음 실행에서는 남은 state와 실제 VPC·subnet·보안 그룹을 먼저 대조하고, 승인된 시험 범위·접속 IP·종료 시각으로 새 계획을 만든다. 현재 API·DB·관측 서버는 삭제되어 기존 주소로 시험을 이어갈 수 없다. 추가 제한적 부하와 실행 영상은 아직 수행하지 않았으며, 이번 0.5 rps 정상 요청 결과를 부하 한계 검증으로 해석하지 않는다. DB 장애 도구의 High 보완·별도 검토 후 세 Alarm과 M3 실환경 검증으로 진행한다.

가짜 값이나 보완 전 이미지 digest가 들어간 plan을 배포 가능한 계획으로 취급하지 않는다.

## 장애 시험과 확인 순서

| 순서 | 수행 내용 | 통과 근거 |
| --- | --- | --- |
| 1 | 허용 IP에서 로그인·`/me`, Grafana·지표 수집 확인 | 정상 토큰 200, 무토큰 401, 잘못된 IP·내부 경로 차단, 실제 지표 수신 |
| 2 | 정상 요청 기준선 측정 | 같은 60초 구간의 요청·DB 수와 평균, 실제 토큰 만료 여유 |
| 3 | 기본 DB 지연 작업과 요청 실행기 실행 | 기존 `/me`의 느린 200, 이후 정상 200, DB 작업 종료 |
| 4 | 명시적 `cancel-one` 시험 한 번 | 정확한 앱 쿼리 하나만 취소, 실제 HTTP 500과 이후 정상 200, 오류 지표 증가 |
| 5 | 실측 기준·최소 표본 수를 적용해 세 Alarm 검증 | 5xx·API 지연·DB 지연의 실제 ALARM/OK 이력 |
| 6 | M3 경로·실제 로그인 확인 | EventBridge→SQS→Lambda→DSQL, 중복·OK·실패 처리, 인증된 Detail 조회 |

위 표의 장애 시험·M2/M3 연결 3~6단계는 후속 계획이며 이번 정상 동작 배포 승인 범위에 포함하지 않는다. DB 시험은 합성 Slash RDS에만 실행한다. LambdaOps DSQL은 대상이 아니다. 기본 지연과 선택적 단일 쿼리 취소 모두 시간·대상·작업 수를 제한한다. 취소 신호 성공만으로 HTTP 500이나 Alarm 발생을 주장하지 않는다. 단발 오류가 최근 세 구간 중 두 구간 초과 조건을 충족한다고 가정하지 않는다.

사용법: [DB 이미지](../../observability/personal/db-test/README.md), [작업 실행·종료](../../observability/personal/task/README.md), [요청 관측](../../observability/personal/requests/README.md), [M2 지표·Alarm 계약](../../docs/observability/M2_CLOUDWATCH.md).

## 종료와 비용

결과를 먼저 저장한 뒤 experiment 전체를 삭제한다. `desired_count=0`이나 RDS stop만으로는 ALB·Valkey·스토리지 등의 비용이 없어지지 않는다.

```sh
terraform plan -destroy -out=/private/tmp/slash-destroy.tfplan
terraform show /private/tmp/slash-destroy.tfplan
terraform apply /private/tmp/slash-destroy.tfplan
terraform state list
```

state 목록과 실제 ECS·ALB·API Gateway·VPC Link·RDS·Valkey·ENI/IP·Cloud Map·secret·로그 잔여물을 함께 확인한다. 실패하면 state를 지우지 말고 원인을 해결한다. foundation은 별도이므로 이미지·Cognito 유지 여부를 따로 결정한다. foundation 삭제는 로그인 사용자도 삭제한다.

2026-10-29 AWS 공식 서울 단가를 다시 조회했다. 주요 실행 자원 합계는 **시간당 $0.22137**이며, 아래 예시는 DB 저장소·지표·secret·로그·요청·전송량을 추가한 정상 동작 시험 추정치다. DB 장애 도구는 실행하지 않는다.

| 생성 시작부터 삭제 완료까지 | 추정 비용(USD, 세전) |
| --- | --- |
| 2시간 | 약 $0.72~1.42 |
| 4시간 | 약 $1.18~1.90 |
| 4시간 시험에 준비·삭제가 1시간 더 걸리는 경우 | 약 $1.41~2.13 |

예시마다 Gateway 전체 요청 1만 건(Grafana·OPTIONS 포함), 로그 0.1~1GB, 인터넷 송신 1GB, 평균 0~1 LCU와 소량의 리전 내 전송을 가정했다. 사용량은 실측이 아니며 무료 제공량·크레딧은 차감하지 않았다. 기존 Cognito·ECR과 LambdaOps 비용·세금은 별도다. RDS CPU 초과 크레딧, 예상보다 많은 로그·전송·재시작도 추가 비용을 낼 수 있다. 로그 1GB를 더 쓰면 수집료만 $0.76이 추가된다.

ALB·Valkey는 부분 시간도 한 시간으로 계산한다. private DNS 영역은 생성 후 12시간 내 삭제하는 조건으로 무료를 가정했으며, 이 조건을 넘기면 월 $0.50이 발생한다. `desired_count=0`이나 종료 태그만으로 비용이 멈추지 않는다. [현재 계산 가정·단가·삭제 대상](../../docs/observability/results/2026-10-29-baseline-cost-estimate.json)을 기준으로 검토하고, [이전 부분 비용 예시](../../docs/observability/results/2026-10-28-domainless-cost-estimate.json)는 당시 기록으로 남긴다. 추정치는 실제 청구액이나 지출 상한이 아니다.

## 실제 AWS 정상 검증 — 2026-10-29

| 단계 | 실제 결과와 해석 |
| --- | --- |
| 최초 배포 | 94개 생성 후 ElastiCache 생성이 HTTP 408 `InvalidCredentialsException`으로 실패했다. 당시 캐시는 없었고 재계획·재시도 후 생성됐다. 서비스 연결 역할의 최초 생성 시점은 확인했지만 오류 원인은 확정하지 않았다. |
| 접속 경로 보완 | 실제 `/me`·Grafana 요청이 ALB의 기본 404로 전달됐다. Gateway URI에 stage와 각 backend 경로를 명시하고 Grafana `{proxy}` 매핑을 추가한 뒤 실제 요청이 통과했다. 자동 stage 전달을 가정하지 않는다. |
| 반복 계획 보완 | 실제 생성되지 않은 빈 Cloud Map health 설정을 제거해 DNS 검색 동작을 유지했다. Gateway 오류 템플릿과 전체 ARN의 별도 접근 정책을 명시해 AWS 정규화와의 차이를 없앴다. 최종 적용 후 재계획은 `No changes`였다. |
| 실행 상태 | API·관측 ECS 서비스 각 1개가 RUNNING, ALB target group 2개가 healthy였다. ECS 컨테이너 health 값은 UNKNOWN이므로 HEALTHY로 기록하지 않는다. RDS PostgreSQL 18.3의 migration·앱 기동은 성공했으며 버전 호환 경고는 남았다. |
| 실제 로그인·접근 제한 | Cognito 웹 client로 AWS `/me` 첫·반복 200, 잘못된 인증 401, 공개 관리 경로 403 등 17개 확인 항목이 통과했다. 다른 출발지 IP의 실제 거부 시험은 수행하지 않았다. |
| 정상 요청 | 0.5 rps로 180초 동안 trial 90회와 사전 확인 1회, 총 91회가 모두 200이었다. 인증·경로 확인 요청은 이 91회와 별개다. 장애 주입과 성능 한계 시험은 아니다. |
| 관측 | Grafana·Prometheus 연결과 CloudWatch 여섯 지표를 확인했다. namespace·차원·60초 집계는 기존 계약을 유지했다. |
| 삭제 중단 후 상태 | 01:29 KST 읽기 조회에서 ECS 실행 task 0, RDS·Valkey·ALB·REST API·VPC Link 없음, ENI 0을 확인했다. Cloud Map·private DNS·시험 로그·secret도 제거됐다. 사용자 요청으로 추가 삭제를 중단했고 VPC·private subnet 2개·보안 그룹 2개는 남아 있다. |

[실행 결과와 화면 근거](../../docs/observability/results/2026-10-29-baseline-runtime/index.json)를 함께 보관한다. 토큰·프로필·원문 IP·secret은 공개 근거에서 제외한다. 화면 캡처는 검증 결과를 보조하며 실제 AWS 콘솔 화면과 검증 결과를 표시한 화면을 구분한다.

초기 CloudWatch 스냅샷은 01:14 KST 구간까지 `RequestCount` 합계 77을 담았다. 후속 읽기 조회에서는 01:15 구간의 23회가 추가로 보여 최종 합계 100, 5xx 합계 0을 확인했다. 초기 77은 유실 건수나 최종 집계가 아니다. 정상 관찰기 91회와 추가 인증·경로 검사의 집계 범위가 다르며 개별 요청과 지표를 완전히 대응시킨 것은 아니다. `/actuator` 요청은 발행 집계에서 제외하므로 health check를 차이의 원인으로 설명하지 않는다. `DBQueryCount`에는 주기 작업도 포함되고, `DBConnectionsActive=0`은 발행 순간의 표본이다. 개별 요청 대조·비허용 IP 시험은 후속 검증이다. 추가 단계별 요청과 실행 영상은 아래의 별도 실행에 기록한다.

위 상태는 첫 시험 직후의 기록이며 experiment 전체 삭제 완료나 계정 비용 0원을 뜻하지 않는다. 이후 별도 승인을 받아 잔존 네트워크와 Terraform state를 대조하고 아래 재배포를 진행했다. 기존 Cognito·ECR·LambdaOps는 유지했다.

## 추가 재배포·단계별 요청·영상 — 실행 결과

잔존 state를 재사용해 01:55 KST에 **생성 92·유지 6, 기존 자원 변경·삭제 0**으로 재배포했다. 같은 이미지 3개·시험자 IPv4 제한을 유지했다. 이후 배포 여부를 판정하는 해시를 AWS 응답 객체 대신 설정 파일과 입력값으로 계산하도록 보완했고, 최종 재계획은 `No changes`였다. Cognito·ECR·기존 LambdaOps와 DB 장애 도구는 이 배포 범위에 포함하지 않았다.

각 단계의 목표는 120초이며, 단계 요청 최대 1,020회와 사전·사후 확인 각 1회로 제한했다. 동시 요청 최대 4개·요청 timeout 3초를 유지하고 오류·응답 2초 초과·실행 용량 부족이면 중단하도록 실행했다. 밀린 요청을 몰아 보내지 않았으며 누적 일정 지연 3초·신규 발송 483초 제한도 유지했다.

| 목표 요청 속도 | 완료 / 계획 | 평균 응답 | p95 응답 | 최대 응답 | 결과 |
| --- | ---: | ---: | ---: | ---: | --- |
| 0.5 rps | 60 / 60 | 70.205 ms | 122.852 ms | 133.504 ms | 완료 |
| 1 rps | 120 / 120 | 97.000 ms | 144.203 ms | 1,115.110 ms | 완료 |
| 2 rps | 240 / 240 | 75.010 ms | 127.018 ms | 1,048.362 ms | 완료 |
| 5 rps | 288 / 600 | 81.430 ms | 121.752 ms | 2,054.693 ms | 기준 초과로 중단·미완료 |

p95는 관측 응답의 95%가 이 값 이하였다는 뜻이다. 표의 시간은 클라이언트에서 측정해 TLS 연결·네트워크 시간을 포함하며, 서버 내부 처리 시간과 다르다. 마지막 단계는 일부 구간만 관측했으므로 이 표만으로 서버 병목이나 5 rps 처리 한계를 단정하지 않는다.

추가 읽기 조회에서 지연이 발생한 02:11 KST(17:11 UTC) 60초 구간의 API 대상 ALB 응답 시간은 평균 4.070 ms·최대 31.310 ms·249표본이었다. ECS API CPU 최대는 4.390%, 메모리 최대는 12.337%였고 RDS CPU는 4.883%, 연결 수는 2개였다. [추가 지연 검토 근거](../../docs/observability/results/2026-10-29-step-demo/client-latency-review.json)에서 서버 포화를 뒷받침하는 근거는 확인하지 못했다. 다만 집계 지표와 개별 클라이언트의 2.05초는 측정 범위가 다르므로 두 값을 빼서 네트워크 지연으로 판단할 수 없으며 원인은 미확정이다.

후속 계획은 클라이언트 연결·DNS·TLS·API Gateway의 소요 시간과 요청별 추적을 보강하는 것이다. 추가 시험은 실행하지 않았다.

`sequence=699` 요청이 HTTP 200으로 끝났지만 2,054.693 ms가 걸려 새 요청을 중단했다. 진행 중이던 요청까지 수집한 **단계 요청 708회와 사전 확인 1회, 총 709회가 모두 HTTP 200**이었다. HTTP 오류는 없었지만 시간 기준 실패가 1건이고 사후 조회는 발송하지 않았다. 결과는 **15/17 확인 항목 통과·전체 FAIL**이다. 안전 중단 동작 확인과 전체 시나리오 통과를 구분하며, 한도를 높이거나 재실행하지 않았다.

요청 종료 후 120초 수집 대기를 마쳤고 CloudWatch 여섯 지표를 수신했다. 스냅샷 `RequestCount` 합계는 716, 5xx는 0이다. 정상 관찰 709회와 앱까지 도달한 별도 인증 요청 7회를 합한 수와 일치한다. 별도 관리 경로 요청 2회는 Gateway 403으로 앱에 도달하지 않았다. 집계 숫자의 일치를 확인한 것이며 개별 요청별 추적을 통한 완전 대응은 아직 검증하지 않았다.

실제 브라우저 화면을 1초 간격으로 캡처해 **40초 영상**으로 저장했다. 요청 시작·Grafana 그래프·지표 수신 화면을 연결했고 구간 사이 시간 생략과 조기 중단을 표시했다. 로그인 화면이나 비밀값을 넣지 않았으며 대표 장면 3개를 검토했다. [요청·지표·영상 근거](../../docs/observability/results/2026-10-29-step-demo/index.json)에 첫 정상 시험과 구분해 보관한다.

종료 기준은 기존 2026-10-29 04:45:03 KST에서 연장하지 않았다. 02:30 KST에 저장된 삭제 계획 98개 항목 적용과 [후속 실제 조회 59/59](../../docs/observability/results/2026-10-29-step-demo/cleanup-verification.json)를 확인했다. 시험용 실행 자원·DB/백업·캐시·API·네트워크·로그·Secrets를 정리했고 Terraform 관리 자원은 0개다. Cognito·ECR과 기존 LambdaOps는 유지하며 수집 연결은 Disabled다. 중지된 작업 이력과 과거 CloudWatch 지표는 남을 수 있으며 계정 전체 비용 0을 뜻하지 않는다. DB 장애 주입·세 Alarm 전이·M3 Incident 종단 검증은 수행하지 않았다.

## 지연 관측 설정 보강 — 아직 배포하지 않음

2,054.693ms 요청 이후 클라이언트 구간별 측정과 앱 완료 로그를 추가했다. Terraform은 개인 API 컨테이너에 `PERSONAL_REQUEST_TIMING_ENABLED=true`를 넣고, GET `/me`의 `X-Slash-Gateway-Request-Id`를 `context.extendedRequestId`로 매핑한다. 기존 proxy 경로·인증·IP 제한·여섯 지표는 유지하며 새 AWS 자원이나 IAM 권한은 추가하지 않았다. 앱은 기본 꺼짐이고 개인 프로필·앱 포트·지정 GET 경로에서만 관찰한다.

요청·보고서 69개, 앱 회귀 47개, 인프라 검사 35개와 Terraform 형식·구성 검사가 통과했다. [실제 로컬 TLS 지연 주입 근거](../../docs/observability/results/2026-10-29-latency-instrumentation.json)와 [측정 범위·사용법](../../observability/personal/requests/README.md#지연-구간과-같은-요청의-앱-기록-비교)을 따른다. 2.05초의 과거 원인과 새 계측의 AWS 동작은 검증하지 않았다.

읽기 전용 조회로 서울 REST Gateway의 `cloudWatchRoleArn` 미설정을 확인했다. 이 계정 공용 설정을 일회성 experiment가 소유하거나 정리 시 삭제하지 않도록, Gateway access log 역할과 요청별 latency 기록은 별도 계획에 남긴다. 앱 JSON은 기존 ECS stdout 로그 경로를 사용하며 원문 IP·URI 등을 포함하는 ALB access log는 켜지 않았다.

위 계측 구현 시점에는 이미지 게시·AWS apply·부하 재시험을 실행하지 않았다. 이후 이미지 생성·검사·게시 결과는 아래에 구분한다. 이전 API 이미지에는 새 필터가 없으며, 새 이미지의 실제 헤더·앱 로그 연결은 아직 환경 검증 전이다.

### 새 API 이미지 검사·배포 검토 — 게시 완료, 배포 보류

2026-10-29 CI가 통과한 `e705095`의 API 소스만 내보내 `linux/amd64` 이미지를 만들었다. 개인 환경 계측 클래스 포함, 기본 비활성화, 비관리자 사용자 UID 100을 확인했다. ECR `slash-lab/api:m2-20261029-latency1`에 게시한 digest는 `sha256:f7390b8c49d1a13398978da95530c98ef4402ecbd4fde383219d7bd674bbe479`이며 로컬 검사 이미지와 일치한다. 이미지를 보관한 것이며 실행 서버를 배포한 것은 아니다.

| 검사 | 범위 | 실제 결과 |
| --- | --- | --- |
| ECR Basic | 지원 운영체제 패키지 | COMPLETE, 검출 0건 |
| Trivy 0.76.1 | Alpine 패키지 73개 | 검출 0건 |
| Trivy 0.76.1 | Java 패키지 124개 | Critical 10·High 41·Medium 45·Low 9 |
| 독립 검토 | 원본 결과·공급자 공지 | 총 105개 패키지 검출, 고유 CVE 104개, 영향 패키지 26개 |

Trivy는 공개 취약점 DB를 먼저 받은 뒤 애플리케이션 이미지를 네트워크 없이 검사했다. AWS 자격증명·Docker 소켓을 전달하지 않았다. 같은 Netty CVE가 HTTP·HTTP2 두 패키지에 잡혀 전체 건수와 고유 CVE 수가 다르다. 위 심각도는 **스캐너 판정**이다. Spring MVC 두 항목은 공급자 판정이 각각 Medium·Low로 다르며 원본 결과와 공급자 조건을 함께 보관한다. 실제 악용 가능성은 검증하지 않았고, 심각도 차이를 근거로 숨기거나 해결 처리하지 않는다. 이전 OS 검사에 포함되지 않았던 Java 범위를 검사한 결과이며 이번 계측 코드가 취약점을 새로 만들었다는 뜻은 아니다.

새 후보를 `current_image_selection`으로 승격하지 않았다. 기존 선택은 과거 실행 근거로만 유지하며 이전 API도 Java 보안 검증을 통과한 대안으로 간주하지 않는다. DB 장애 도구의 기존 High 4건도 미해결이며 이번 baseline 구성에서 제외했다. [이미지·전체 발견 목록·독립 검토 근거](../../docs/observability/results/2026-10-29-api-image-security-review.json)를 참고한다.

새 digest로 `enable_workloads=true`, `cloud_contract_verified=false`를 유지한 Terraform 검토를 실행했다. 구성 검사는 통과했지만 **새 이미지의 실제 로그인·지표 격리 확인이 없어 plan은 기존 사전 조건에서 종료 코드 1로 차단**됐다. 부분적으로 생성 93개(AWS 선언 91개·로컬 난수 2개), 변경·삭제 0개가 계산됐다. 전체 코드 구성은 98개로 예상되지만 계약 검사와 ECS 작업 정의 2개·서비스 2개는 차단 이후 계산되지 않았다. 이를 성공한 최종 계획이나 서버 98대로 표시하지 않는다. 별도로 Java 보안 검토도 미통과다.

| 배포 승인 이후 생성할 주요 구성 | 수량·사양 | 역할 |
| --- | --- | --- |
| API Fargate | 작업 1개, 1 vCPU·3 GiB | Slash 요청 처리·구간 시간 로그 |
| 관측 Fargate | 작업 1개, 1 vCPU·2 GiB | Prometheus·Grafana |
| RDS PostgreSQL | 1개, db.t4g.small·gp3 20GB | Slash 시험용 DB. LambdaOps의 기존 DSQL과 별개 |
| Valkey | 1개, cache.t4g.micro | Slash 캐시, 저장·전송 암호화 |
| REST API·VPC Link V2·내부 ALB | 각각 1개 | 도메인 없는 HTTPS 진입과 내부 API 연결 |
| 네트워크·권한·관측 | VPC 1·서브넷 4·보안 그룹 7, 역할·로그·비밀값 등 | 접근 제한·실행 권한·기록 보관 |

이 표는 현재 코드의 구성 의도이며 통과한 최종 계획이 아니다. NAT Gateway·VPC 인터페이스 엔드포인트·DB 장애 작업·신규 Cognito/ECR·LambdaOps/Alarm 자원은 포함하지 않는다. 시험자 주소는 이전 비공개 `/32`를 검토에만 사용했으며 현재 주소 재확인 전이다. 검토용 종료 태그는 실제 실행 일정이 아니며 자동 삭제 기능도 아니다. 실제 배포 전에 IP·종료 시각·이미지와 계획을 다시 확인한다. 이번 작업은 apply·서버 생성·부하 및 장애 시험을 실행하지 않았고 experiment state는 0개다.

| 생성부터 삭제 완료까지 총시간 | 향후 정상 시험 예상 비용(USD, 세전) |
| --- | ---: |
| 1시간 | $0.49–1.18 |
| 2시간 | $0.72–1.42 |
| 6시간 | $1.64–2.37 |

서울 공식 가격 API의 19개 단가를 재조회했다. API·관측 작업, RDS·Valkey·ALB·공인 IPv4 2개의 기본 합계는 약 $0.22137/시간이다. 위 총액은 DB 저장·지표 최대 6개·비밀값 3개, 실행당 REST 요청 1만 건·로그 0.1–1GB·유료 외부 전송 1GB·평균 0–1 LCU 등을 포함한다. 시험 2시간에 준비·정리 1시간을 더하면 약 $0.95–1.66이다. 기존 Cognito·ECR·LambdaOps, 초과 RDS CPU 크레딧·세금은 별도이며 지출 상한이 아니다. 부분 시간 과금과 DNS 영역 보관 조건은 [계산 근거의 후속 검토](../../docs/observability/results/2026-10-29-baseline-cost-estimate.json)에 기록했다.

이번 게시 이미지의 ECR 크기는 131,123,066 bytes다. 전체가 신규 저장된다는 보수적 가정으로 월 약 $0.014 이하($0.10/GB·월)이며 공유 계층이 있으면 추가 저장비가 줄어든다. ECR Basic 검사는 추가 요금이 없다. 새 서버 운영비는 발생시키지 않았으나 기존 계정 전체 비용이 0이라는 뜻은 아니다. [ECR 요금](https://aws.amazon.com/ecr/pricing/), [Basic 검사 안내](https://aws.amazon.com/about-aws/whats-new/2024/08/new-version-amazon-ecr-basic-scanning/).

다음 순서는 같은 버전 계열의 보안 패치·호환성 검토 → 이미지 재생성·OS/Java 재검사 → 실제 Cognito·지표 격리 재확인 → 새 배포 계획 검토다. Spring Framework 일부 항목은 무료 수정판이 7 계열이므로 Boot 3.5 패치만으로 모두 해결된다고 가정하지 않는다. 필요한 전환 범위는 별도 검토하고 부분 라이브러리만 무리하게 혼합하지 않는다. 이번에는 앱 버전·기존 아키텍처를 변경하지 않았다.

## 검증의 범위

Terraform validate·포맷·인프라 경계 검사, 로컬 Java·Python 시험, 임시 TLS PostgreSQL 동작 검사를 실행한다. Grafana의 `/m2/grafana/` 로그인·정적 파일·보안 쿠키는 로컬 이미지로 확인했다. GitHub CI도 AWS 자원 생성 없이 같은 종류의 검사를 수행한다.

foundation 생성과 실제 Cognito code+PKCE 로그인을 확인했다. 활성화한 **LambdaOps HTTP API → 조회 Lambda → DSQL** 경로에서 빈 목록 200(`items` 0개), 무토큰·잘못된 토큰 401, 같은 client의 읽기 scope 없는 토큰 403, 미존재 상세 404를 확인했다. 실제 존재하는 Incident의 상세 200은 아직 검증하지 않았다. LambdaOps의 M2 Alarm·수집 연결도 아직 활성화하지 않았다.

Slash의 REST API→VPC Link V2→내부 ALB→ECS·RDS 경로에서 정상 로그인·요청과 지표 수신을 검증했다. 비허용 IP의 실제 차단, 세 Alarm의 ALARM/OK 전이, 장애 시험, M3 이벤트 처리와 실제 Incident 상세 200은 미검증이다. 로컬 21개·첫 AWS 17개·후속 단계별 시험 15/17 결과는 서로 다른 실행 근거이며 혼합해 집계하지 않는다. M2·M3는 아직 In Progress다.

공식 근거: [REST/HTTP 기능 비교](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-vs-rest.html), [VPC Link V2와 ALB](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-private-integration.html), [stage 전달](https://docs.aws.amazon.com/apigateway/latest/developerguide/private-integration.html), [ALB URL rewrite](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/rule-transforms.html), [IP 정책](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-resource-policies-examples.html), [Cognito 기본 domain](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-assign-domain-prefix.html), [API Gateway 요금](https://aws.amazon.com/api-gateway/pricing/).
