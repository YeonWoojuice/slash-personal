# Slash Personal

Slash 팀 프로젝트를 바탕으로 개인적으로 개선하기 위한 독립 모노레포입니다.
현재는 로컬 소스 스냅샷을 가져온 상태이며, 아키텍처 변경이나 AWS 배포는 수행하지 않았습니다.

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
| infra/reference | 기존 인프라 참고 자료, Terraform 파일은 `.reference`로 비활성화 |
| docs/migration | 출처, 가져온 파일 목록, 분리 점검 결과 |

## 현재 상태

- 원본 7개 저장소와 그 remote는 변경하지 않았습니다.
- 원본 Git 이력은 합치지 않고 현재 파일로 새 이력을 시작합니다.
- 원본 주소·기준 커밋·로컬 변경은 `docs/migration/sources.json`에 기록했습니다.
- 팀 코드의 저작·기여 출처를 유지하며 새 라이선스를 임의로 부여하지 않았습니다.
- 실제 `.env`, 비밀 키, Terraform state, 설치 의존성, 빌드 결과는 가져오지 않았습니다.
- GitHub remote와 개인 AWS 계정은 아직 연결하지 않았습니다.

## 개발 시작 전

각 앱의 README에 있는 설치·테스트 절차를 참고하세요. 기존 문서의 경로와 배포 안내는 원본 기준입니다.
원본과 개인용 서비스를 동시에 실행하면 포트·Docker 컨테이너 이름·Agent 사용자 설정이 충돌할 수 있습니다.
개인용 로컬 환경의 이름과 포트를 분리한 뒤 실행해야 합니다.
웹 로그인은 개인 Cognito 설정이 필요하며 전체 앱의 로컬 통합 실행은 아직 검증하지 않았습니다.

[분리 점검 및 다음 작업](docs/migration/ISOLATION.md)을 먼저 읽어 주세요.
[아키텍처 개선 후보](infra/reference/docs/architecture-improvement-proposals.md)는 참고 자료이며 구현된 구성이 아닙니다.
