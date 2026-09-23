# Slash 아키텍처 개선 제안 — 팀 검토용

작성일: 2026-09-23 · 상태: 미합의 제안, 구현·AWS 변경 없음

검토 관점은 **학습·포트폴리오와 비용의 균형**이다. 기존 팀의 기술 선택과 학습 목표를 존중하면서 운영 부담을 줄일 수 있는 후보를 정리한다. Kubernetes와 GPU 운영을 계속할지 여부도 팀 논의 대상이다.

이 문서는 확정 설계나 변경 지시가 아니다. 기존 코드·Terraform·배포 설정·팀 계약은 그대로 유지한다. 아래 구성과 전환 절차는 팀이 해당 제안을 채택하는 경우에만 적용할 검토안이다. 로컬 소스와 설정을 확인했으며 AWS 계정의 실제 리소스·청구서는 조회하지 않았다. 사용자 수, 월 예산, 가용성 목표는 미확정이다.

## 팀에서 먼저 논의할 개선 항목

각 항목은 독립적으로 채택·보류할 수 있다. 전체 구조를 한 번에 바꾸는 것을 전제하지 않는다. 담당 영역은 논의 참여 대상이며 실제 담당자 배정은 아니다.

| 우선순위 | 개선 후보 | 기대 효과 | 영향·선행 확인 | 논의할 담당 영역 | 상태 |
|---|---|---|---|---|---|
| 1 | 실제 비용·사용량과 기존 스케줄 확인 | 변경 없이 절감 우선순위 판단 | 청구 내역, 가동시간, 팀 공용 시간 | 인프라·팀 전체 | 미검토 |
| 1 | 리소스 크기·복제 수 조정 | 상시 비용 축소 | 부하 측정, 가용성 요구, JVM/NLU 메모리 | API·NLU·인프라 | 미합의 |
| 2 | GPU 대신 사용량 기반 모델 호출 | GPU 고정 비용 축소 가능 | 한국어 품질, 모델 학습 목표, 데이터 처리, API 계약 | LLM·API·인프라 | 미합의 |
| 2 | EKS 대신 ECS | 클러스터 운영 부담 축소 | Kubernetes 학습 목표, 기존 CI/CD, WSS 복구 | 인프라·API·NLU·LLM | 미합의 |
| 2 | NAT 없는 앱 네트워크 | NAT 시간·처리량 비용 절감 | public IP 정책, SG, 모든 outbound 의존성 | 인프라·보안 | 미합의 |
| 3 | RDS Single-AZ | standby 비용 축소 | 기존 NFR, 장애 허용 범위, 복원 시험 | API·인프라·팀 전체 | 미합의 |
| 보류 | Valkey 제거 | 저장소 운영 대상 축소 | 인증·TTL·잠금·WSS를 대체해야 함 | API·Agent·인프라 | 현재 유지 권고 |

팀 합의 기록 시 항목별로 채택/보류, 근거, 담당자, 검증 기준, 작업 범위를 남긴다. 현재 승인되거나 담당자가 배정된 항목은 없다.

## 1. 비교용 경량 구성안

비교 후보는 **CloudFront/S3 + Cognito + ALB + ECS Fargate + RDS PostgreSQL + 소형 공유 Valkey**다. 서버 요약은 상시 GPU 대신 Bedrock 온디맨드 호출을 검토한다. 모델은 리전 지원·한국어 품질·단가 검증이 필요하다. 이하 세부 내용은 이 후보를 채택했을 때의 설계 가정이다.

| 구분 | 목표 | 이유와 대가 |
|---|---|---|
| 컨테이너 실행 | ECS Fargate 서비스 1개 | 노드·Kubernetes 컨트롤러 운영 제거. EC2 직접 운영보다 항상 저렴하다는 뜻은 아님 |
| 실행 단위 | API + NLU + 경량 LLM 어댑터를 같은 태스크의 별도 컨테이너로 배치 | 내부 호출은 localhost. 배포·확장·장애 단위가 묶이는 대가를 수용 |
| 태스크 수 | 평소 1, 확장·롤링 배포 실습 때 2 | 기본 상태에서 무중단·고가용성을 주장하지 않음 |
| DB | RDS PostgreSQL Single-AZ, 기존 db.t4g.small부터 검증 | 백업·복구 관리 유지. Multi-AZ 자동 장애 전환 포기 |
| 공유 상태 | 기존 cache.t4g.micro Valkey 1노드 유지 | 인증·잠금·WSS 라우팅을 보존. 장애 시 해당 기능 중단 가능 |
| AI | Bedrock 온디맨드 + 기존 요약 HTTP 계약 어댑터 | GPU 고정 비용 제거. 토큰 비용·외부 서비스 장애·품질 차이 발생 |
| 네트워크 | public ALB/Fargate, private DB/Valkey | NAT 제거. 앱 직접 접근은 SG로 차단 |
| 배포 | GitHub Actions OIDC → ECR → ECS | Helm·Argo CD·External Secrets Operator 제거 |
| 관측 | CloudWatch Logs/핵심 알람 + 비용 알림 | 별도 관측 플랫폼 없이 운영 근거 확보 |

소형 Valkey는 삭제 대상에서 제외한다. 서비스 개수를 줄이려고 인증·재전송을 모두 재작성하면 전환 비용과 검증 범위가 크게 늘어난다. 장기적으로 제거하려면 5절의 별도 조건을 만족해야 한다.

## 2. 전체 구조

```text
Route 53: 웹/API 도메인 DNS 해석 (HTTP 중계 아님)

브라우저 ── 로그인 ── Cognito
    │
    ├── 정적 웹 ── CloudFront ── private S3 (OAC)
    │
    └── HTTPS REST / 필요 시 WSS ── ALB :443
                                      │
PC Runner ── outbound WSS ─────────────┤
                                      ▼
                         ECS Fargate 서비스 (평소 1 task)
                         ┌───────────────────────────┐
                         │ API :8080                 │
                         │  ├─ NLU :8001             │
                         │  └─ LLM adapter :8000      │
                         └────────┬─────────┬────────┘
                                  │         └── Bedrock 온디맨드
                                  ├── private RDS PostgreSQL
                                  └── private Valkey

GitHub Actions ── OIDC ── ECR / ECS 배포
로그·지표 ── CloudWatch ── SNS 알림
```

웹과 API는 별도 도메인을 유지한다. API 앞에 CloudFront/API Gateway를 추가하지 않는다. ALB가 REST와 기존 Runner WSS를 함께 처리한다. Cognito는 사용자 인증, API는 사용자·기기·작업 소유권 인가를 맡는다. Runner의 Ed25519 인증은 그대로 유지한다.

## 3. 소스에서 확인한 기준선

| 근거 | 확인 내용 | 설계 영향 |
|---|---|---|
| `modules/eks/variables.tf`, `environments/dev/eks/main.tf` | 기본 t3.medium, desired 3/min 2/max 4 | EKS 컨트롤플레인과 노드 규모를 제거할 여지 |
| `environments/dev/network/main.tf` | 2 AZ, AZ별 NAT 기본값 사용 | 신규 경량 환경은 NAT 0개 |
| `modules/database/variables.tf`, `environments/dev/database/main.tf` | db.t4g.small, Multi-AZ 기본값, Valkey micro | DB를 Single-AZ로 축소, Valkey는 기존 크기 유지 |
| `environments/dev/llm-runtime/main.tf` | g4dn.xlarge 기본값, On-Demand override | GPU와 75GB 기본 EBS를 목표에서 제거 |
| `../slash-api/.../llm/LlmSummaryRunner.java` | DB 작업 원장 + 비동기 스레드 + LLM HTTP 호출 | 서버 요약을 없애면 현재 기능이 깨짐 |
| `../slash-api/.../llm/LlmJobSweeper.java` | 미시작 작업 재시도·만료 처리 | SQS 없이도 현재의 복구 기반을 활용 가능 |
| `../slash-api/.../pairing/*`, `ws/UserWsTicketStore.java` | Valkey TTL·원자적 소비·nonce 중복 차단 | 단순 메모리 캐시로 대체 불가 |
| `../slash-api/docs/w1-06-wss-routing.md` | 공유 Valkey Pub/Sub + DB 전달 원장 | 배포 중 구·신 태스크 공존 시에도 공유 상태 필요 |

`...`는 `src/main/java/com/likelion/slash`를 뜻한다. README와 8월 아키텍처 문서는 오래된 설명이 섞여 있어 실제 호출 코드와 Terraform을 우선했다. 위 설정값은 실제 실행 대수·청구 내역을 보증하지 않는다.

## 4. 워크로드와 경계

| 기능 | 처리 방식 | 상태·저장 | 실행 위치 |
|---|---|---|---|
| 로그인 | Cognito OAuth, API 토큰 검증 | Cognito 사용자 + DB 업무 권한 | 브라우저/Cognito/API |
| 명령·작업 생성 | 짧은 동기 검증, 작업 ID 반환 | PostgreSQL 작업 원장 | API → NLU |
| 자연어 분석 | 내부 HTTP, 짧은 timeout | 기본적으로 요청 단위 | 같은 태스크의 NLU |
| PC 파일 검색·상태 조회·실행 | WSS TASK → ACK/RESULT | DB 전달 기록 + Runner 중복 방지 | 사용자 PC |
| 서버 텍스트 요약 | 접수 후 비동기 실행 | async_jobs + tasks | API → LLM adapter → Bedrock |
| 브라우저/PC의 로컬 AI | 지원되는 기존 실행 경로 유지 | 서버에는 계약된 결과만 전달 | 브라우저/Runner |
| 화면 상태 갱신 | 현재 클라이언트 계약 유지 | DB 정본 조회 | API |
| 임시 인증 상태·WSS 전달 | TTL·원자 연산·Pub/Sub | 공유 Valkey | API |

PC 파일을 요약 서버에 자동 전송하지 않는다. 서버 요약에 제출된 텍스트만 모델 입력으로 사용한다. 모델 제공자 변경에 따른 데이터 처리 범위는 기능 안내에도 반영한다.

SQS·별도 Worker·EventBridge 이벤트 버스는 기본 구성에 추가하지 않는다. 현재 요약 경로는 DB 원장과 비동기 실행을 사용한다. 긴 작업이 API CPU/메모리·스레드를 압박하거나 큐 지연이 목표를 넘으면 그때 Worker를 분리한다.

## 5. 반드시 보존할 동작

### WebSocket과 공유 상태

연결 소켓은 해당 API 프로세스가 보유한다. 영속 작업 상태는 PostgreSQL, 태스크 간 신호는 공유 Valkey가 맡는다. 태스크별 Valkey sidecar를 두면 구·신 태스크 사이 인증 티켓과 Pub/Sub가 분리되므로 채택하지 않는다.

배포 시 WSS가 끊길 수 있다. heartbeat보다 충분히 긴 ALB idle timeout, 연결 drain, Runner backoff+jitter 재연결, 재인증, 미완료 dispatch 재전송, 결과 중복 차단을 검증한다. DB 원장과 재시도 설계만 보고 exactly-once 실행을 보장한다고 표현하지 않는다.

Valkey 장애 시 인증 검증을 우회하지 않는다. Pub/Sub 유실은 DB 전달 원장과 sweeper가 복구하는지 시험한다. Valkey를 제거하려면 아래를 먼저 구현·검증해야 하므로 1차 전환에서 제외한다.

- 일회용 티켓/페어링 세션: 만료 조건을 포함한 DB 원자적 소비.
- nonce: 유효 시간 확인 + unique 제약에 의한 재사용 차단.
- 시도 제한: 동시 요청에서도 우회되지 않는 카운터.
- dispatch: 소유권·lease·만료·중복 실행 방지.
- 복수 API 간 WSS 신호와 유실 복구. PG LISTEN/NOTIFY만으로 보장 전달을 가정하지 않음.

### 서버 요약

기존 LLM adapter의 `/internal/v1/llm/summary`와 `{summary, model}` 계약을 유지하고 Ollama 호출 구현을 Bedrock adapter로 교체한다. API/웹 계약 변경을 줄이기 위해 이 작은 컨테이너는 유지한다. `/ready`의 Ollama 모델 조회 로직도 함께 교체해야 한다.

모델 ID, 리전, 최대 입력·출력 토큰, timeout, 동시성 상한을 설정으로 둔다. 한국어 품질·응답 시간·실패 변환을 기존 요약 샘플로 검증한다. 지원 모델·접근 권한·리전 내 처리 가능 여부를 확인하기 전 특정 모델을 확정하지 않는다. cross-region inference는 자동으로 켜지 않는다.

사용자별 호출 제한, 전역 동시성 제한, 일별 토큰 예산을 앱에서 집행한다. AWS Budgets 알림 자체는 실시간 지출 차단기가 아니다. 재시도 횟수를 제한하며, DB 결과 중복 차단이 모델 재호출 비용까지 없애지는 않는다.

작업 claim/lease, 재시도 상한, 오래 RUNNING인 작업, 이전 실행자의 늦은 결과 반영을 점검한다. 기존 sweeper가 있다고 복구 검증 완료로 취급하지 않는다.

## 6. 네트워크와 리소스 크기

VPC 하나에 2 AZ의 public subnet과 private data subnet을 둔다. ALB는 public 2 AZ, Fargate는 public subnet + public IP를 사용한다. data subnet에는 인터넷 기본 경로가 필요 없다. Single-AZ RDS여도 DB subnet group은 2 AZ로 준비한다.

| 보안그룹 | inbound |
|---|---|
| ALB | 인터넷 TCP 443, 필요 시 80→443 리다이렉트 |
| App | ALB SG에서 API 8080만 |
| PostgreSQL | App SG에서 5432만 |
| Valkey | App SG에서 6379만, TLS+AUTH 유지 |

NLU 8001과 LLM adapter 8000은 외부에 열지 않는다. task 내 localhost로 호출한다. RDS/Valkey는 private IP로 접근하고, ECR·Secrets Manager·CloudWatch·외부 API는 IGW를 통해 접근한다. 유료 Interface Endpoint를 서비스마다 추가하지 않는다. public IP 비용은 남는다.

초기 측정용 태스크는 **Linux x86_64, 1 vCPU / 3 GiB**, desired count 1로 시작한다. 기존 이미지와 Python native 라이브러리 호환성을 먼저 지킨다. JVM heap/native memory, Kiwi 로딩, LLM adapter를 합쳐 메모리를 측정한 뒤 2 GiB 또는 ARM64를 평가한다. 이 수치는 벤치마크 결과가 아니다.

API·NLU·LLM adapter는 별도 이미지/프로세스로 유지하지만 동일 task revision으로 배포한다. 하나의 essential container 장애가 전체 task 교체로 이어지는 결합을 수용한다. NLU가 주 병목이면 별도 ECS service로 분리한다.

RDS는 Single-AZ, 초기 20GB gp3, 백업 7일, 삭제 보호·최종 snapshot을 유지한다. 같은 DB를 여러 환경이 섞어 쓰지 않는다. 신규 환경은 기존 DB snapshot 복원과 데이터 일관성 검증 후 전환한다. 처음부터 운영 DB를 새 VPC로 옮기거나 Terraform에서 재생성하지 않는다.

## 7. 후보 채택 시 제거·유지 검토 목록

| 조치 | 대상 |
|---|---|
| 상시 구성 제거 | EKS control plane/노드그룹, Karpenter, ALB Controller, Argo CD, Helm 배포, External Secrets Operator, 상시 GPU/Ollama EC2, NAT Gateway |
| 축소 | API/NLU 상시 복제 수, RDS Multi-AZ, 상시 원격 환경 수 |
| 유지 | S3/CloudFront/OAC, Route 53/ACM, Cognito, ALB, PostgreSQL, 공유 Valkey, ECR, Secrets Manager, CloudWatch, Terraform S3 state |
| 추가하지 않음 | API Gateway/관리형 WebSocket, Lambda로 Spring 분해, SQS/별도 worker, DynamoDB, 서비스 메시, 별도 관측 클러스터 |
| 선택 실습 | ECS 2 tasks 확장, 장애 주입·복구, 일시적인 EKS 실습 환경 |

기존 Kubernetes 코드와 실습 결과는 이력으로 보존한다. 전환이 끝난 뒤 구 배포 workflow와 스케줄러를 중지하여 제거한 리소스가 재생성되지 않게 한다. AWS 리소스 종료는 state·데이터·의존성 확인 뒤 별도 실행 단계다.

## 8. 배포와 Terraform 경계

CI: 테스트 → 이미지 build/scan → ECR immutable commit tag/digest 게시.
CD: GitHub OIDC → ECS task definition revision 등록 → service 갱신 → 안정화 확인 → smoke test. ECS deployment circuit breaker/rollback을 구성한다. Secrets Manager는 ECS secret 주입을 사용하며 실행 역할과 앱 task role을 분리한다. 앱 역할에는 선택 모델 호출에 필요한 범위만 부여한다.

스키마 변경은 별도 일회성 ECS migration task로 실행한다. 앱 롤백과 DB 롤백은 다르므로 expand/contract migration을 사용한다. image digest와 task revision으로 롤백 가능하게 한다.

원격 환경은 당분간 `demo` 하나, 개발은 Docker Compose로 한다. 다음은 **새 구조 제안**이며 기존 state 경로를 즉시 변경하지 않는다.

```text
bootstrap/                    # state, 공통 ECR/OIDC 등
modules/
  network/                    # 2 AZ public + private data, NAT 없음
  edge/                       # 정적 웹, 도메인, 인증서
  auth/                       # Cognito
  app/                        # ALB, ECS service/task, IAM, log groups
  data/                       # PostgreSQL, Valkey, secrets
  observability/              # 알람, 대시보드, 예산
environments/demo/            # 하나의 root에서 위 모듈 조합
```

기존 여러 state에서 하나로 통합하는 작업은 초기 ECS 전환과 분리한다. 기존 root 간 이전에는 백업·import/state 이전 계획이 필요하다. 다른 state 사이 이동을 단일 `moved` 블록으로 해결한다고 가정하지 않는다. 첫 전환은 기존 network/data/auth/edge를 재사용하고 새 app state를 추가해 변경 범위를 제한한다.

## 9. 비용과 가용성

비용 비교는 서울 리전, 동일 가동 시간, 세금·환율·크레딧을 구분해서 작성한다. 기존 설정에 운영시간 스케줄이 있으므로 모두 730시간 돌았다고 가정해 절감액을 과장하지 않는다.

```text
신규 월 비용 = Fargate 가동시간 × (vCPU 단가 × 1 + GiB 단가 × 3)
            + ALB 시간요금 + LCU
            + RDS Single-AZ 실행시간 + 스토리지/추가 백업
            + Valkey 1노드
            + public IPv4 시간요금 (ALB 포함)
            + Bedrock 입력/출력 토큰
            + CloudFront/S3/전송 + Cognito + DNS/Secrets/Logs 등

절감 후보 = 기존 EKS control plane/노드 + NAT 시간/처리량
          + GPU 실행시간/EBS + DB standby + 중복 환경
          - 새 ECS 실행비와 모델 호출비 등
```

EKS standard support의 $0.10/cluster-hour는 730시간 기준 약 $73다. 이는 control plane만의 예시이며 실제 버전/지원 단계와 계정 청구를 확인해야 한다. 전체 월 금액과 절감률은 아직 산출하지 않았다.

ALB·Valkey는 앱을 꺼도 비용이 남고, DB 정지 중에도 스토리지 비용이 남는다. RDS 정지는 장기 무료 보관 방식으로 취급하지 않는다. 상시 공개 데모를 끄는 스케줄은 기본에 넣지 않는다.

Single task + Single-AZ RDS + 단일 Valkey는 고가용성 구성이 아니다. 예전 문서의 최소 2 Pod/NFR-07 충족 주장과 함께 사용할 수 없다. 이번 demo 환경의 가용성 수준을 별도로 명시한다. 운영 서비스로 확대할 때 task 2개 이상과 데이터 계층 이중화를 각각 검토한다.

학습용 최초 시험 부하는 **동시 Runner 10개, REST 5 RPS, 요약 동시 1개**로 제안한다. 실제 수요나 보장 용량이 아니다. 30분 시험 후 p95 지연·오류율·메모리·재연결·작업 유실을 기록하고 용량을 조정한다.

## 10. 팀 합의 후 사용할 전환 순서와 완료 조건 초안

1. **현황 확정:** 실제 AWS 리소스, state 소유권, 비용, 가동 스케줄, OIDC/배포 주체를 읽기 전용으로 대조한다. 기존 DB 백업과 복원 시험을 한다.
2. **LLM 전환:** adapter 내부를 Bedrock로 교체하고 readiness·오류·예산 제한·한국어 품질을 검증한다. 그 전에는 GPU를 제거하지 않는다.
3. **ECS 병행 구축:** 기존 VPC의 public subnet에서 앱을 시작하고 기존 RDS/Valkey에 App SG 접근을 추가한다. Cognito/사용자·기기 ID는 보존한다. 새 ALB의 시험 도메인으로 기능을 검증한다.
4. **전환 시험:** Cognito 로그인, 페어링·nonce 재사용 거부, 파일 검색, 서버 요약, 재시작 중 ACK/RESULT, 두 task 사이 전달, DB·Valkey·모델 장애를 시험한다. 서로 다른 DB를 쓰는 두 backend가 같은 실제 기기 작업을 동시에 소비하지 않게 한다.
5. **API 전환:** 새 작업 접수를 제어하고 진행 작업·기존 WSS를 drain한 뒤 DNS/접속 경로를 전환한다. DNS 변경만으로 기존 WSS가 이동하지 않음을 반영한다. 초기 전환은 같은 DB를 사용해 롤백을 단순화한다.
6. **비용 축소:** 안정화 후 구 EKS/GPU를 종료한다. NAT는 구 private workload 및 migration 작업의 outbound 의존성이 없어진 뒤 제거한다. RDS Single-AZ 변경은 별도 유지보수 단계로 분리한다.
7. **최종 정리:** 구 스케줄러·CI/CD·IAM·ALB·볼륨·EIP·로그 보존을 점검하고 비용을 다시 측정한다. state 통합과 불필요한 subnet 정리는 마지막에 한다.

실행 단계 완료 조건: 기능 회귀 통과, 원장 유실 없음, 재연결·중복 방지 검증, 복원·롤백 실증, 경량 환경의 비용 명세 확보. 이 문서 작성 시에는 아직 실행하지 않았다.

포트폴리오에는 이전/이후 구성, 비용 비교의 가정, 부하 결과, 연결 종료 후 복구 기록, 배포 실패 rollback, DB 복원 시간, 보안그룹/IAM 경계를 제시한다. 도구 개수보다 선택 근거와 검증 결과를 보여 준다.

## 11. 공식 근거

- [ECS/Fargate 네트워크](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html): public subnet + public IP와 IGW 경로.
- [동일 task의 컨테이너 구성](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/container-considerations.html): 함께 배치할 때의 실행·배포 결합 검토.
- [ALB WebSocket 지원](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-listeners.html): 기존 연결 방식 유지 근거.
- [EKS 요금](https://aws.amazon.com/eks/faqs/), [Fargate 요금](https://aws.amazon.com/fargate/pricing/), [VPC 요금](https://aws.amazon.com/vpc/pricing/): 고정 비용과 사용량 과금 구분.
- [Bedrock 요금](https://aws.amazon.com/bedrock/pricing/): 온디맨드 모델의 사용량 과금. 실제 모델별 입력/출력 단가를 적용해야 함.

공식 문서는 2026-09-23 조회했다. 모델·가격·리전 지원은 구현 시점에 재확인한다.
