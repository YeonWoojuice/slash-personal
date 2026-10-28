# Slash Personal

Slash 팀 프로젝트를 바탕으로 개인적으로 개선하기 위한 독립 모노레포입니다.
개인용 로컬 관측 환경과 일회성 AWS 테스트용 Terraform을 추가했습니다. Cognito·ECR 기반 자원 17개는 생성·검증했으며, Slash API·DB 실행 환경과 이미지 게시는 아직 준비 단계입니다.

## 구성

| 경로 | 내용 |
|---|---|
| apps/web | React 웹 |
| apps/api | Spring Boot API |
| apps/nlu | 자연어 분석 |
| apps/llm | LLM 서비스 |
| apps/agent | PC Agent |
| docs/original | 기존 프로젝트 문서 |
| docs/legacy-automation | 기존 CI/CD 참고 자료, 자동 실행되지 않음 |
| infra/personal | 필요할 때 생성하고 삭제하는 개인 AWS 테스트 Terraform |
| infra/reference | 기존 인프라 참고 자료, Terraform 파일은 `.reference`로 비활성화 |
| docs/migration | 출처, 가져온 파일 목록, 분리 점검 결과 |

## 현재 상태

- 원본 7개 저장소와 그 remote는 변경하지 않았습니다.
- 원본 Git 이력은 합치지 않고 현재 파일로 새 이력을 시작합니다.
- 원본 주소·기준 커밋·로컬 변경은 `docs/migration/sources.json`에 기록했습니다.
- 팀 코드의 저작·기여 출처를 유지하며 새 라이선스를 임의로 부여하지 않았습니다.
- 실제 `.env`, 비밀 키, Terraform state, 설치 의존성, 빌드 결과는 가져오지 않았습니다.
- GitHub는 `YeonWoojuice/slash-personal`을 사용합니다. 개인 AWS 계정의 서울 리전에 foundation을 생성했습니다. [배포 검증 결과](docs/observability/results/2026-10-28-foundation-provision.json)를 참고하세요.

## 개발 시작 전

각 앱의 README에 있는 설치·테스트 절차를 참고하세요. 기존 문서의 경로와 배포 안내는 원본 기준입니다.
원본과 개인용 서비스를 동시에 실행하면 포트·Docker 컨테이너 이름·Agent 사용자 설정이 충돌할 수 있습니다.
개인용 로컬 환경의 이름과 포트를 분리한 뒤 실행해야 합니다.
웹 로그인은 개인 Cognito 설정이 필요하며 전체 앱의 로컬 통합 실행은 아직 검증하지 않았습니다.

[분리 점검 및 다음 작업](docs/migration/ISOLATION.md)을 먼저 읽어 주세요.
[아키텍처 개선 후보](infra/reference/docs/architecture-improvement-proposals.md)는 참고 자료이며 구현된 구성이 아닙니다.

[일회성 AWS 테스트 환경과 생성·삭제 절차](infra/personal/README.md)를 참고하세요. 앱 클라우드 계약을 검증하기 전에는 workload 실행이 기본 비활성화됩니다.


## LambdaOps M2 시험 준비

이 저장소는 LambdaOps의 장애 수집 기능을 검증하는 Slash 시험 대상이다. Incident 저장·조회 코드는 [LambdaOps](https://github.com/YeonWoojuice/LambdaOps)에 있다.

- [개인 Terraform](infra/personal/README.md): 도메인 없는 HTTPS 접속과 로그인·이미지 저장소·임시 시험 환경.
- [CloudWatch 계약](docs/observability/M2_CLOUDWATCH.md): 같은 서비스·환경의 지표와 세 Alarm 검증 기준.
- [제한된 DB 시험](observability/personal/db-test/README.md), [작업 실행](observability/personal/task/README.md), [요청 기록](observability/personal/requests/README.md), [LambdaOps 로그인·조회 확인](observability/personal/auth/README.md).

`main`에 push하면 GitHub Actions가 Java 인증·계측, Python 도구, 임시 TLS PostgreSQL, Terraform 구성을 검사한다. CI에는 AWS 자격증명·배포·이미지 게시 단계가 없다. 개인 AWS 환경은 별도의 검토한 계획으로 배포한다. 로컬·CI 검사 통과와 실제 AWS 로그인·Alarm·Incident 검증 결과를 구분한다.
