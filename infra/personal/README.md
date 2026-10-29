# 일회성 AWS 테스트 환경

2026-10-29 기준. 첫 AWS 시험에서 실제 Cognito·HTTPS API 검증 17개, 정상 요청 91회 모두 200, CloudWatch 지표 6종 수신을 확인했다. 후속 단계별 요청 시험은 **0.5·1·2 rps 단계를 완료했으나, 5 rps 단계에서 응답 1건이 2초 기준을 넘어 안전 중단**됐다. 정상 요청 관찰 709회는 모두 HTTP 200이지만 전체 시험은 FAIL이며 마지막 단계와 사후 조회가 미완료다. 02:30 KST 최종 조회 59/59를 통과해 재시험용 자원 정리를 확인했다. Terraform 관리 자원은 0개다. Cognito·ECR foundation과 기존 LambdaOps는 유지한다. DB 장애 도구의 새 이미지는 ECR 게시·Basic 검사에서 검출 0건을 확인했다. 전체 배포 계획은 새 Boot 4 API의 실제 인증 검증·ECR 게시가 남아 차단 상태다. 장애 시험·세 Alarm 전이·M3 종단 검증은 미검증 상태다. 기존 팀 환경과 `infra/reference`의 state는 사용하지 않는다.

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

위 최초 이미지 검사 단계에서는 앱 버전·기존 아키텍처를 변경하지 않았다. 이후 승인한 기존 계열 보완 결과는 아래에 기록한다.

### 기존 계열 Java 보안 보완 — 로컬 검증

변경 전 커밋 `9cd208f`를 별도 내보내 전체 테스트 551개를 통과시킨 뒤 보안 패치를 적용했다. 최초 실행의 1개 실패는 격리 작업 폴더에 SQL 참고 파일이 빠진 문제였으며, 코드 변경 없이 파일과 경로를 바로잡아 551개 모두 통과했다. 테스트 실행기까지 외부 연결이 없는 임시 Docker 네트워크에 넣어 기존 개발용 DB·캐시와 분리했다.

| 대상 | 변경 전 → 실제 선택 버전 | 범위 |
| --- | --- | --- |
| Spring Boot / Security / Framework | 3.5.9 → 3.5.16 / 6.5.7 → 6.5.11 / 6.2.15 → 6.2.19 | 기존 계열 유지. Framework 두 항목은 미해결 |
| Tomcat / Netty | 10.1.50 → 10.1.61 / 4.1.130 → 4.1.137.Final | 임베디드 서버·네트워크 모듈 묶음 정렬 |
| Jackson / Micrometer | 2.19.4 → 2.21.7 / 1.15.7 → 1.15.12 | Jackson은 같은 주버전의 minor 변경, JSON·지표 회귀 검증 |
| PostgreSQL JDBC / jOOQ | 42.7.8 → 42.7.12 / 3.19.29 → 3.19.35 | JDBC 세 사용 경로, jOOQ 런타임·생성기 정렬 |
| HttpCore / HttpClient | 5.3.6 → 5.4.3 / 5.5.1 → 5.5.2 | Core 5.4와 호환되는 Client 조합 |

새 서명·발급자·만료·잘못된 client 검사 7개와 응답 보안 헤더 검사 8개를 추가해 **전체 566개가 통과**했다. 실패·오류·건너뜀은 0개다. 실제 JWT decoder는 로컬 합성 발급자의 공개 키를 읽어 서명을 검사하며 실제 Cognito 로그인 검증은 아니다. 임시 PostgreSQL에서 Flyway 검증·마이그레이션과 jOOQ 재생성을 확인했고 생성 파일 29개는 기존과 동일했다. 생성과 컴파일은 기존 명시적 작업 방식에 맞춰 별도 실행했다. GitHub API job도 임시 PostgreSQL·Valkey를 사용한 전체 검사로 확대했다.

새 로컬 이미지 `slash-personal-api:m2-20261029-javafix1`의 digest는 `sha256:08b0bd91a641298d281e6c1746fa0e3b2b0aa2e0d9ec2a067eea6e59243085c2`다. 같은 Trivy 0.76.1·같은 취약점 DB로 비교했으며 검사 예외나 숨김 규칙을 추가하지 않았다.

| 검사 범위·심각도 | 변경 전 | 변경 후 |
| --- | ---: | ---: |
| OS 패키지 검출 | 0 | 0 |
| Java Critical | 10 | 2 |
| Java High | 41 | 0 |
| Java Medium | 45 | 2 |
| Java Low | 9 | 0 |
| Java 전체 / 고유 CVE | 105 / 104 | 4 / 4 |

새 이미지 자체를 개인 프로필로 실행한 로컬 검사 28개도 통과했다. 합성 발급자의 서명 토큰으로 `/me` 200·사용자 중복 생성 없음, 무토큰·위조 서명 401, 없는 경로 404, 앱·관리 포트 격리를 확인했다. 실제 WebSocket 101 연결과 접속표 재사용 거부(4401), 응답 ID·지연 JSON 4건의 일대일 연결과 민감값 미포함도 확인했다. 사용자 UID 100·읽기 전용 파일시스템·호스트 포트 미노출 조건이다. 실제 Cognito나 AWS Gateway 검증은 아니며 지연 값도 AWS 성능 결과로 해석하지 않는다. 검증용 컨테이너·네트워크·임시 DB와 합성 키·토큰은 정리했다.

기존 Critical·High의 패키지별 검출 51개 중 49개가 새 이미지에서 더 이상 검출되지 않는다. 전체 앱의 무취약성·악용 불가능성을 입증하는 수치는 아니다. 검사 대상은 실행 이미지의 OS·Java이며 Gradle 플러그인의 별도 빌드 클래스패스 보안까지 통과했다고 표시하지 않는다.

남은 Critical은 스캐너 기준 `CVE-2026-47884`·`CVE-2026-47890` 두 건이다. 공식 공급자 분류는 각각 Medium·Low이고 특정 XSLT 뷰·SSE 뷰 조각 조건에 해당한다. 소스 검색에서 해당 사용 근거를 찾지 못했지만 비영향으로 확정하지 않았다. 무료 수정판은 Framework 7.0.9, 6.2.20은 유료 지원판이다. Boot 3.5.16도 마지막 무료 OSS 릴리스이므로 적용 조건과 Boot 4 전환 범위를 먼저 검토한다. Framework 일부 모듈만 7계열로 교체하지 않았으며 유료 서비스도 추가하지 않았다. [XSLT 공지](https://spring.io/security/cve-2026-47884/), [SSE 공지](https://spring.io/security/cve-2026-47890/), [Boot 지원 종료 안내](https://spring.io/blog/2026/06/25/spring-boot-3-5-16-available-now/).

Medium은 HttpClient 5.5.2와 Log4j API 2.24.3 각 1건이며 별도 보완 항목으로 유지한다. DB 장애 도구의 기존 High 4건도 이번 API 보완과 별개다. [변경 전후·의존성·검사 근거](../../docs/observability/results/2026-10-29-java-security-remediation.json)를 연결한다. 새 이미지는 로컬 검증 후보로 보관하며 ECR 추가 게시·선택 이미지 승격·Terraform apply·AWS 서버 생성·실제 부하 및 장애 시험은 하지 않았다. 새 이미지의 실제 Cognito 검증과 AWS 지연 원인은 여전히 미검증이며 M2·M3는 In Progress다.

### Boot 4.1 전환 — 로컬 후보 검증

사용자가 승인한 큰 버전 전환은 별도 `codex/slash-boot4` 작업 폴더에서 진행했다. 위 기존 계열 보완 결과는 당시 기록이며, 최신 로컬 후보는 `slash-personal-api:m2-20261029-boot412`다. LambdaOps 저장소의 조회 UI·Cognito·CORS·시험 Incident·영상 작업은 이 변경에 포함하지 않는다.

| 구성 | 이전 → 현재 후보 | 검증 내용 |
| --- | --- | --- |
| Boot / Framework / Security | 3.5.16 / 6.2.19 / 6.5.11 → 4.1.2 / 7.0.10 / 7.1.2 | 기술별 모듈·테스트 패키지·보안 필터 순서 연결 |
| Tomcat / Jackson | 10.1.61 / 2.21.7 → 11.0.27 / 3.1.7 | HTTP·WebSocket·한국 시각·null·오류 응답 유지 |
| jOOQ / Flyway | 3.19.35 / 런타임 11.7.2 → 3.21.9 / 12.4.0 | 실행/생성기 정렬, SQL 구조 유지, 기존 이력 검증 |
| HttpClient / Log4j API | 5.5.2 / 2.24.3 → 5.6.5 / 2.25.5 | Boot 관리 버전 적용 후 이미지 검사 |
| Java / Gradle | 21 / 8.14.5 유지 | 로컬 테스트·실행 파일·이미지 생성 |

기존 테스트 566개를 보존하고 구 JSONB 결과 조회·이전 Redis 봉투 수신·ACK 직렬화 실패 격리 3개를 추가했다. **PostgreSQL 16과 18에서 각각 569개가 통과**했고 실패·오류·건너뜀은 0개다. 최초 실패 3개는 테스트의 구독 컨테이너 선택과 발행 전 구독 준비 순서로 보완했다. 실제 전달의 제한 시간과 기대값은 완화하지 않았다. 새 DB를 만들 때와 Flyway 11로 만든 기존 이력을 Flyway 12가 읽을 때 모두 성공했으며 SQL migration 10개의 이력이 일치한다.

jOOQ 3.21 OSS의 공식 PostgreSQL 최소 버전은 18이다. 따라서 16의 성공은 관측한 호환성 결과로만 기록한다. 코드 생성과 새 이미지 실행 검사는 18.6에서 수행했다. CI는 일회성 PostgreSQL 18을 사용하고, [별도 로컬 구성](../../apps/api/docker-compose.boot4.yml)은 기존 16 볼륨과 다른 이름·포트·볼륨을 사용한다. [실행 방법](../../apps/api/README.md#로컬-실행)을 따른다. 기존 데이터를 자동 이전하거나 기본 compose를 교체하지 않았다. 과거 AWS 기록의 RDS는 18.3이었으며 이번에는 AWS 상태를 조회·변경하지 않았다. [jOOQ 지원 표](https://www.jooq.org/download/support-matrix)

새 이미지 manifest는 `sha256:99575923af1d78a6d7cc54f461072a0a1347b9c2ae441538f93f3e6ecd39256b`다. 동일한 Trivy 0.76.1·취약점 DB를 사용해 **OS 73개·Java 151개 패키지에서 검출 0건**을 확인했다. 이전 후보의 Critical 2·Medium 2도 더 이상 검출되지 않는다. 검사 예외를 추가하지 않았으며, Gradle 플러그인·코드 생성기의 별도 의존성 전체를 보안 통과로 표시하지 않는다.

정확히 이 이미지를 실행한 검사 28개가 통과했다. 로컬 합성 JWT·401/404·보안 헤더·관리 포트 격리·WebSocket 연결과 접속표 재사용 거부·시간 로그 4건의 일대일 연결을 확인했다. 임시 컨테이너·네트워크·DB와 합성 키·토큰은 정리했다. [전환·테스트·이미지 검사 근거](../../docs/observability/results/2026-10-29-boot4-security-remediation.json)에 결과와 한계를 기록한다.

현재 상태는 **로컬 전환 후보 검증 완료**다. 새 이미지의 실제 Cognito·AWS 검증, ECR 게시, 배포 선택 승격, Terraform 실행과 장애 시험은 남아 있다. DB 장애 도구의 기존 High 4건과 과거 2.05초의 원인도 별도 미해결 항목이다. 기존 Alarm·Incident 계약과 M2·M3의 환경 검증 상태는 바꾸지 않는다. 다음 단계는 실제 로그인 검증 일정 분리 → ECR 후보 게시·검사 → 배포 계획 검토이며, 실제 서버 생성은 별도 승인 범위다.

### DB 장애 도구 High 보완 — 로컬 후보 검증

위 Boot 전환 이후 DB 시험 도구를 별도 `codex/slash-db-highfix` 작업 폴더에서 보완했다. Debian 13 안정판의 수정 패키지가 확인되지 않아, 지원 중인 Alpine 3.24의 클라이언트 전용 구성으로 변경했다. `psql`은 18.6이며 PostgreSQL 서버·RDS 엔진·기존 데이터는 변경하지 않았다. 고정 SQL·실행 스크립트·서울 RDS CA는 기존과 동일하다.

| 이전 ECR High | 새 로컬 후보의 처리 |
| --- | --- |
| glibc 2건 | musl 기반으로 변경해 glibc 의존성을 포함하지 않음 |
| Cyrus SASL 1건 | LDAP·SASL 의존성이 없는 공식 libpq 사용 |
| zlib 1건 | `CVE-2026-85091` 수정 패치가 포함된 `1.3.2-r1` 적용 |

변경 전 기존 테스트 15개가 통과했다. 시작 대기·쿼리 취소 대기 중 종료 검사를 더한 17개도 최종 이미지로 PostgreSQL 16·18에서 각각 통과했으며 실패·오류·건너뜀은 0개다. UID/GID 999·읽기 전용 실행·GNU timeout·TLS 호스트 검증·정확한 쿼리 한 건만 취소하는 계약을 유지한다. GitHub의 DB 검사도 두 서버 버전을 사용한다. 최종 실행 결과와 이미지 식별자는 [보완 근거](../../docs/observability/results/2026-10-29-db-tool-security-remediation.json)를 따른다.

같은 Trivy 0.76.1·취약점 DB로 비교하면 이전 이미지의 패키지별 검출은 High 46·Medium 71·Low 84·Unknown 4건이고, 새 후보는 **33개 OS 패키지에서 검출 0건**이다. 이전 ECR High 4건은 이 Trivy에서 Medium 7개 패키지 검출로 표시되므로 두 도구의 수치를 같은 기준으로 합치지 않는다. glibc·SASL은 제거한 의존성, zlib는 적용한 수정 패키지로 구분한다. 검사 예외나 숨김 규칙은 추가하지 않았다.

새 태그는 `slash-personal-db-test:m2-20261029-highfix2`다. 현재 결과는 로컬 후보에 한정하며 기존 ECR 이미지·`current_image_selection`·`enable_db_test_task=false` 설정은 유지한다. ECR 게시·재검사, ECS/RDS 실행·실제 HTTP 500·Alarm 전이는 미검증이다. Terraform apply·AWS 서버 생성·실제 장애 시험은 실행하지 않았다. LambdaOps의 화면·Cognito·DEMO 데이터·Notion은 이번 변경에 포함하지 않는다.

### DB 도구 ECR 게시와 배포 계획 — 2026-10-29

위 로컬 보완 이후 승인된 ECR 게시·검사를 완료했다. 계정 `642935793048`·서울 `slash-lab/db-test`의 새 불변 태그 `m2-20261029-highfix2`가 로컬 검증 이미지와 일치한다. manifest는 `sha256:82b02a988204e1b463dace5e32b1c5c4155db19ea07e2164e025fc2efc01ba84`이며, 게시 직후 자동 Basic 검사가 11:02:25 KST에 완료되어 검출 0건을 확인했다. 태그 덮어쓰기·기존 이미지 삭제·API 이미지 게시 없이 DB 도구의 선택 기록만 갱신했다. 임시 ECR 인증 파일도 삭제했다.

배포에 앞서 원본 상태를 복사한 별도 폴더에서 Terraform 계획을 실행했다. `init`·`validate`는 통과했고, DB 도구 자체의 계약 검사도 통과했다. 전체 `plan`은 **`cloud_contract_verified=false`인 인증·지표 검증 조건**으로 종료 코드 1에서 중단됐다. 새 Boot 4 API는 실제 Cognito 검증과 ECR 게시 전이므로 이 값을 임의로 통과시키지 않았다. 계산용 API 참조는 실제 게시된 이전 이미지 `f7390b8c…`이며, Java 보안 승인을 받은 배포 후보가 아니다. 미게시 Boot 4 digest를 ECR에 존재하는 것처럼 입력하지 않았다.

부분 계획은 생성 101개(AWS 98·로컬 3), 변경·삭제 0개다. 전체 계약 검사·API/관측/DB 작업 정의 3개·API/관측 서비스 2개가 아직 평가되지 않았다. 이를 포함한 전체 107개(AWS 103·로컬 4)는 코드에서 예상한 설정 수이며, 통과한 최종 계획이나 서버 수가 아니다. [계획·독립 검토 근거](../../docs/observability/results/2026-10-29-db-tool-deployment-review.json)에 계산 범위를 구분했다.

| DB 도구에 추가되는 설정 | 개수 | 역할 |
| --- | ---: | --- |
| ECS 작업 정의 | 1 | 0.25 vCPU·512 MiB·X86_64로 실행할 일회성 도구 명세. 정의 생성만으로 실행되지 않음 |
| IAM 역할·정책 | 3 | 실행 역할·빈 task 역할, 해당 이미지·로그·시험 DB 비밀값 읽기 범위 |
| 보안 그룹·접근 규칙 | 4 | 도구 인바운드 없음, 시험 RDS 5432와 HTTPS 접근 |
| 로컬 Terraform 계약 검사 | 1 | 명시적 활성화·digest·최대 실행 시간 확인 |

DB 도구의 9개 설정 중 작업 정의를 제외한 8개가 부분 계획에 계산됐다. 앞으로 전체 시험 환경에는 API Fargate 1개(1 vCPU·3 GiB), 관측 Fargate 1개(1 vCPU·2 GiB), RDS PostgreSQL `db.t4g.small`·20GB gp3, Valkey `cache.t4g.micro`, 내부 ALB·REST API·VPC Link와 네트워크 설정이 필요하다. 읽기 전용 조회에서 현재 서울 RDS의 PostgreSQL 기본 버전은 사용 가능한 18.3으로 확인했다. 엔진 버전은 코드에 고정되어 있지 않으므로 최종 계획에서 다시 확인한다. DB 도구는 기본 지연 1회·시작 대기 15초이며 별도 실행 요청 전에는 시작되지 않는다. LambdaOps·Cognito·Alarm·NAT·VPC endpoint 신규 생성은 이 계획에 없다.

| 비용 구분 | 서울 기준 예상액(USD·세전) |
| --- | ---: |
| 이번 DB 이미지 보관 | 10,322,807 bytes를 모두 신규 공간으로 한 달 보관한다고 가정하면 약 $0.0011/월 |
| 이번 ECR Basic 검사 | 추가 검사 요금 없음 |
| 향후 DB 도구 실행 1분 / 10분 | 약 $0.000320 / $0.003199, 컴퓨팅·공인 IPv4 기준 |
| 향후 전체 Slash 기반 | 주요 시간 요금 약 $0.22137/시간, 저장·지표·로그·요청·LCU 등 별도 |

공식 Price List API의 19개 단가를 재조회했으며 이전 비용 검토와 같았다. DB 작업 요금은 이미지 다운로드부터 종료까지의 시간에 적용되며 최소 60초다. 10분 예시는 지출 상한이 아니고 로그·비밀값 조회·재시도는 별도다. 이미지 공유 계층과 실제 보관 기간에 따라 추가 저장비는 줄어든다. 위 금액은 계정 전체 비용을 뜻하지 않는다. [ECR 요금](https://aws.amazon.com/ecr/pricing/), [Basic 검사 안내](https://aws.amazon.com/about-aws/whats-new/2024/08/new-version-amazon-ecr-basic-scanning/), [Fargate 요금](https://aws.amazon.com/fargate/pricing/), [IPv4 요금](https://aws.amazon.com/vpc/pricing/).

이번 읽기 전용 조회에서 Slash 시험용 VPC·RDS·활성 ECS 클러스터·캐시·ALB는 0개였고 원본 experiment state도 변경 없이 관리 항목 0개다. ECR 게시 외에 서버 생성·Terraform apply·ECS 작업 실행·부하·장애 시험은 하지 않았다. 시험자 주소는 현재 단일 `/32`를 비공개로 반영했으며 종료 태그는 검토용이다. 실제 일정이나 자동 삭제 기능으로 취급하지 않는다. `capstone-구현-설계2`의 LambdaOps 화면·로그인·DEMO 데이터·영상과 Notion은 수정하지 않았다.

다음 순서는 새 Boot 4 API의 실제 Cognito·지표 격리 검증 → 해당 API 이미지 ECR 게시·검사 → 이미지·시험자 주소·실행/정리 시간·RDS 버전을 반영한 전체 계획 재검토다. 실제 서버 생성과 장애 시험은 그 이후의 별도 실행 단계다.

## 검증의 범위

Terraform validate·포맷·인프라 경계 검사, 로컬 Java·Python 시험, 임시 TLS PostgreSQL 동작 검사를 실행한다. Grafana의 `/m2/grafana/` 로그인·정적 파일·보안 쿠키는 로컬 이미지로 확인했다. GitHub CI도 AWS 자원 생성 없이 같은 종류의 검사를 수행한다.

foundation 생성과 실제 Cognito code+PKCE 로그인을 확인했다. 활성화한 **LambdaOps HTTP API → 조회 Lambda → DSQL** 경로에서 빈 목록 200(`items` 0개), 무토큰·잘못된 토큰 401, 같은 client의 읽기 scope 없는 토큰 403, 미존재 상세 404를 확인했다. 실제 존재하는 Incident의 상세 200은 아직 검증하지 않았다. LambdaOps의 M2 Alarm·수집 연결도 아직 활성화하지 않았다.

Slash의 REST API→VPC Link V2→내부 ALB→ECS·RDS 경로에서 정상 로그인·요청과 지표 수신을 검증했다. 비허용 IP의 실제 차단, 세 Alarm의 ALARM/OK 전이, 장애 시험, M3 이벤트 처리와 실제 Incident 상세 200은 미검증이다. 로컬 21개·첫 AWS 17개·후속 단계별 시험 15/17 결과는 서로 다른 실행 근거이며 혼합해 집계하지 않는다. M2·M3는 아직 In Progress다.

공식 근거: [REST/HTTP 기능 비교](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-vs-rest.html), [VPC Link V2와 ALB](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-private-integration.html), [stage 전달](https://docs.aws.amazon.com/apigateway/latest/developerguide/private-integration.html), [ALB URL rewrite](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/rule-transforms.html), [IP 정책](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-resource-policies-examples.html), [Cognito 기본 domain](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-assign-domain-prefix.html), [API Gateway 요금](https://aws.amazon.com/api-gateway/pricing/).
