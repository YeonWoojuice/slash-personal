# 일회성 DB 작업 시작과 종료 확인

`run.py`는 **이미 배포한** Terraform `db_test` 출력을 받아 ECS 작업 한 개를 실행하고 종료를 확인한다. 기본 동작은 미리보기이며, `--execute`가 있을 때만 선택한 DB 시험을 시작한다. 기본 모드는 `delay`이며 단일 오류 시험은 `--mode cancel-one`을 명시한다. AWS CLI가 필요하고 SDK 패키지는 추가하지 않는다.

## 배포 후 실행 순서

아래는 AWS 배포·정상 로그인·지표 확인이 끝난 뒤 실행할 절차다. 현재 준비 단계에서는 실행하지 않았다.

1. 실제 Cognito 토큰을 준비하고 [요청 실행기](../requests/README.md)로 정상 `/me` 응답을 확인한다. 토큰 유효기간을 전체 시험보다 길게 확보한다.
2. `enable_db_test_task=true`로 검토한 Terraform 계획을 적용해 작업 정의를 준비한다. 이 단계 자체는 DB 시험을 시작하지 않는다.
3. 출력과 결과는 저장소 밖의 새 파일에 보관한다.

```sh
umask 077
terraform -chdir=infra/personal/experiment output -json db_test > /private/tmp/slash-db-test-config.json
python3 observability/personal/task/run.py --config /private/tmp/slash-db-test-config.json
```

미리보기에서 계정 `642935793048`, 서울, 해당 실험 task definition, 종료 예정 시각을 확인한다. 준비가 끝난 후 터미널 A에서 다음 명령을 실행한다.

```sh
python3 observability/personal/task/run.py \
  --config /private/tmp/slash-db-test-config.json --execute \
  --result /private/tmp/slash-db-task-새실행.jsonl
```

4. `RUNNING`을 확인하고 초기 대기 시간 안에 터미널 B에서 요청 실행기를 시작한다. 토큰은 미리 준비한다. 기본 15초가 짧으면 검토한 task 설정의 시작 대기를 최대 60초로 늘릴 수 있다.
5. DB 로그 `pulse_start`~`pulse_completed`와 요청 시각을 대조한다. `pulse_start`는 접속 시도 시각이며 정확한 잠금 획득 시각이 아니다. SQL 완료·지연된 실제 요청·앱 지표를 함께 확인한다.
6. 작업 `STOPPED`, 컨테이너 exit code 0, 잠금 해제 후 정상 API 응답과 지표를 확인한다. 성공 종료만으로 Alarm 검증이 끝난 것은 아니다.

## 단일 쿼리 취소를 선택하는 경우

`db_test_pulses=1`인 배포 출력과 정상 `/me` 기준선을 먼저 준비한다. 다른 요청 실행기·k6·브라우저 자동 새로고침은 함께 실행하지 않는다.

```sh
python3 observability/personal/task/run.py \
  --config /private/tmp/slash-db-test-config.json --mode cancel-one
# 검토 후, 별도의 실제 시험 단계에서만:
python3 observability/personal/task/run.py \
  --config /private/tmp/slash-db-test-config.json --mode cancel-one --execute \
  --result /private/tmp/slash-db-cancel-새실행.jsonl
```

실제 실행 시 Terraform 출력의 `core_service_arn`으로 서비스와 task를 조회한다. 배포가 완료된 core 서비스에 실행 중인 API task가 정확히 한 개여야 한다. 그 task의 revision·서비스 소속·컨테이너·네트워크 연결·subnet을 확인한 뒤 실제 private IP만 사용한다. 사용자가 임의 IP·SQL·DB 주소를 입력하는 옵션은 없다. 앱 재배포로 IP가 바뀌어 일치하지 않으면 DB 시험이 실패하며, 다른 대상으로 자동 확대하지 않는다.

고정 task definition은 기본 `delay`여야 하고 preset 취소 IP·command·entrypoint가 있으면 거부한다. `cancel-one`의 ECS override는 **모드와 확인한 앱 IP 두 항목뿐**이다. secret·DB 주소·명령은 변경하지 않는다. 실행 로그에 확인한 core task ARN과 IP를 남기되 자격 증명은 남기지 않는다.

`RUNNING` 확인 직후 초기 대기 시간 안에 다른 터미널에서 `requests/cancel_probe.py`를 시작한다. 이때 기본 동시 요청 실행기 `requests/run.py` 대신 전용 관찰기를 사용한다. 후보가 여러 개면 안전하게 취소를 거부하기 때문이다. 성공 판정은 task 종료, `cancel_signalled`, 같은 시각 HTTP 500 한 건, 후속 정상 200을 각각 확인한 뒤 내린다. 한 번의 500은 CloudWatch Alarm 검증 완료가 아니다.

## 제한과 실패 처리

- 현재 AWS 계정이 승인 계정과 일치해야 한다. 만료된 `expires_at`은 실행을 거부한다.
- 같은 task family에 대기/실행 중인 작업이 보이면 중복 시작을 거부한다. 이는 실수 방지 검사이며 여러 실행자가 동시에 시작하는 것을 막는 분산 잠금은 아니다. 한 사람이 한 번씩 실행한다.
- 검토한 digest 이미지·고정 entrypoint를 사용한다. 요청마다 command·DB 주소·secret override를 받지 않는다.
- 한 번에 Fargate task 한 개만 시작한다. run-task 응답 유실·중단 시 고유 `startedBy`로 제한된 횟수만 재조회하며, 두 번째 작업을 자동 시작하지 않는다.
- 시작 대기 포함 최대 900초 또는 `expires_at` 중 먼저 도달하는 시각까지 관찰한다. 컨테이너 안의 실제 DB 작업은 별도로 600초 제한과 종료 유예를 가진다.
- 실패·시간 초과·Ctrl-C/SIGTERM 시 식별된 해당 task에 StopTask를 요청하고 최대 90초 동안 STOPPED를 확인한다. 클라이언트를 강제 종료하거나 네트워크가 끊기면 확인이 남을 수 있다.
- 결과의 `stopped_confirmed=false` 또는 `launch_outcome_unknown`은 수동 확인이 필요하다는 뜻이다. 기록된 task ARN 또는 startedBy로 조회하고, 확인 전 재실행하지 않는다. 로컬 실행기 종료를 AWS 작업 종료로 간주하지 않는다.
- 중지 후 진행 중인 DB 쿼리가 제한 시간까지 잠깐 남을 수 있다. DB 잠금 해제와 다음 정상 응답을 별도로 확인한다.

실행자의 IAM에는 해당 cluster/task에 대한 RunTask·DescribeTasks·ListTasks·StopTask·DescribeTaskDefinition(단일 취소는 DescribeServices도 필요), 작업의 두 역할에 대한 `iam:PassRole`이 필요하다. 사용자 IAM 권한을 이 변경에서 추가하지 않았다. 정의를 만드는 권한과 실제 실행 권한은 후속 AWS 환경에서 확인한다.

기록 파일은 새 파일만 만들며 권한은 600이다. 비밀번호·토큰·환경변수 값은 기록하지 않는다. 단위 테스트는 AWS 응답을 대체하며 실제 작업을 시작하지 않는다.

```sh
python3 -m unittest discover -s observability/personal/task -p 'test_*.py' -v
```
