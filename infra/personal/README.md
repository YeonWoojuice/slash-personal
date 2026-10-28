# 일회성 AWS 테스트 환경

2026-10-29 기준. LambdaOps M2·M3의 실제 이벤트 경로를 검증하기 위한 Slash 시험 환경이다. **foundation의 Cognito·ECR 자원 17개를 생성했고 실제 로그인과 LambdaOps 조회 API의 기본 인증을 검증했다.** ECR에는 시험 이미지 4개를 게시했다. 후속 보완에서 Grafana 패키지 갱신, Prometheus의 셸 제거, DB 시험 이미지의 클라이언트 전용 구성을 적용해 High를 21건에서 4건으로 줄였다. 후속 실제 Cognito·로컬 Slash 검증 21개가 통과했다. DB 시험 도구를 제외한 정상 동작용 Terraform 계획은 생성 97·변경 0·삭제 0으로 성공했다. High 4건은 미해결로 유지하며 해당 도구의 이미지·작업 정의·전용 권한을 이번 계획에서 제외했다. Slash 실행 환경인 experiment와 부하·장애 시험은 아직 실행하지 않았다. 기존 팀 환경과 `infra/reference`의 state는 사용하지 않는다.

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

계획의 종료 시각은 비용 비교용 4시간 가정이며 실행 예약이 아니다. 실제 배포 승인 후 시험자 IP·종료 시각·계정·이미지 상태를 다시 확인하고 새 계획을 만든다. `expires_at`은 자동 삭제나 비용 상한을 보장하지 않는다. 실제 서버 생성과 장애 시험은 아직 실행하지 않았다.

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

정상 동작용 계획 검토를 마쳤으며 다음 순서로 진행한다.

1. 생성 자원·실행 시간·비용·삭제 범위를 확인하고 실제 서버 생성 승인을 받는다.
2. 승인 시점의 시험자 IP·종료 시각·계정·이미지 상태로 새 계획을 만들고 범위가 같은지 확인한 뒤 적용한다.
3. 정상 로그인·`/me`·IP와 내부 경로 차단·Grafana·CloudWatch 수신을 확인하고 결과를 저장한다.
4. 계획한 종료 시각 전에 정리를 시작해 experiment를 삭제하고 잔여 과금 자원을 확인한다. 이후 DB 장애 도구의 High 보완·별도 검토를 거쳐 장애 시험과 M2·M3 실환경 검증으로 진행한다.

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

## 검증의 범위

Terraform validate·포맷·인프라 경계 검사, 로컬 Java·Python 시험, 임시 TLS PostgreSQL 동작 검사를 실행한다. Grafana의 `/m2/grafana/` 로그인·정적 파일·보안 쿠키는 로컬 이미지로 확인했다. GitHub CI도 AWS 자원 생성 없이 같은 종류의 검사를 수행한다.

foundation 생성과 실제 Cognito code+PKCE 로그인을 확인했다. 활성화한 **LambdaOps HTTP API → 조회 Lambda → DSQL** 경로에서 빈 목록 200(`items` 0개), 무토큰·잘못된 토큰 401, 같은 client의 읽기 scope 없는 토큰 403, 미존재 상세 404를 확인했다. 실제 존재하는 Incident의 상세 200은 아직 검증하지 않았다. LambdaOps의 M2 Alarm·수집 연결도 아직 활성화하지 않았다.

Slash의 REST API·ECS·RDS·ALB는 experiment에 속하며 아직 배포하지 않았다. Slash의 stage 경로 전달·IP 정책·ECR pull·AWS에서의 정상 `/me`·CloudWatch·Alarm·부하와 장애 시험은 후속 환경 검증이다. 실제 Cognito와 로컬 personal API의 `/me`·지표 격리는 별도 검증을 통과했다. LambdaOps 조회 API 인증 성공을 Slash 앱 로그인이나 장애 시험 성공으로 대신하지 않는다. M2·M3는 아직 In Progress다.

공식 근거: [REST/HTTP 기능 비교](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-vs-rest.html), [VPC Link V2와 ALB](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-private-integration.html), [stage 전달](https://docs.aws.amazon.com/apigateway/latest/developerguide/private-integration.html), [ALB URL rewrite](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/rule-transforms.html), [IP 정책](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-resource-policies-examples.html), [Cognito 기본 domain](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-assign-domain-prefix.html), [API Gateway 요금](https://aws.amazon.com/api-gateway/pricing/).
