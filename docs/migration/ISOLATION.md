# 개인 저장소 분리 기록

## 가져오기

2026-09-23, 로컬 원본 7개 저장소에서 Git 추적 파일의 현재 내용을 복사했다.
추가로 원본 docs의 `api/*.md` 3개와 이번 대화의 아키텍처 개선 제안을 포함했다.
원본의 수정된 docs/README.md도 현재 내용으로 가져왔다.
별도 작업 사본인 slash-nlu-meeting-contract와 output/tmp는 중복·산출물이므로 제외했다.
커밋 이력과 원본 `.git` 디렉터리는 가져오지 않았다.
출처는 sources.json, 파일별 경로와 복사 시점 해시는 import-manifest.json에 있다.

## 배포 격리

- 기존 GitHub 메타데이터는 docs/legacy-automation으로 이동했다.
- 기존 workflow YAML은 `.reference` 확장자를 붙였다. 루트 .github/workflows는 없다.
- infra/reference의 Terraform/HCL 파일에도 `.reference`를 붙였다. 이 경로는 실행용이 아니다.
- 참고 자료에는 기존 계정 ID·도메인·배포 명령이 남아 있다. 개인 배포 설정으로 재사용하지 않는다.
- 원본 환경 변수·AWS credentials·Terraform state를 복사하거나 AWS에 접속하지 않았다.

## 추가 분리가 필요한 실행 설정

아직 앱을 실행하거나 동작을 바꾸지 않았다. 다음을 개인 실행 환경 구성 시 처리해야 한다.

1. apps/api/docker-compose.yml의 고정 컨테이너 이름과 5432/6379 포트: 원본 로컬 실행과 충돌 가능.
2. PC Agent의 OS keyring·config·single-instance 이름: 기존 설치와 공유될 수 있으므로 개인용 이름으로 분리.
3. Agent update_check.py는 팀 GitHub Releases를 조회한다. 개인 저장소 주소 확정 후 교체하거나 비활성화.
4. 웹 SettingsDialog의 Agent 다운로드 링크는 팀 Releases를 가리킨다. 개인 배포판 준비 후 교체.
5. 앱별 문서·테스트·에이전트 지침의 옛 저장소 경로를 새 구조에 맞춰 점검.
6. 개인 Cognito, 도메인, AWS 계정, Terraform state, GitHub OIDC/Secrets는 새로 구성.
7. 루트 CI는 새 작업 디렉터리와 paths filter를 기준으로 추가. 기존 workflow를 그대로 활성화하지 않음.

## 검증 범위

복사 파일의 SHA-256 일치, 중첩 Git 없음, 활성 workflow·Terraform·실제 .env·state 없음과
일부 알려진 credential 패턴을 점검했다. 패턴 검사는 모든 비밀의 부재를 보장하지 않는다.
앱 동작 변경이 없어 서비스 테스트·빌드·AWS 배포는 실행하지 않았다.

원본 파일의 CRLF와 기존 후행 공백은 보존했다. 전체 diff --check에서는 해당 원본 서식이 보고되며, 새로 작성한 분리 문서는 별도로 검사했다.
