# 일회성 DB 지연·단일 오류 시험

합성 데이터만 있는 Slash RDS PostgreSQL의 `public.users`를 3초 잠그는 실행기다. 기본 `delay` 모드는 기존 [SQL](../sql/db-query-delay.sql)을 실행한다. 명시적으로 선택한 `cancel-one` 모드는 자기 잠금에 걸린 앱 조회 한 건만 취소한다. HTTP API나 서버 프로세스를 열지 않으며, 정해진 횟수 후 종료한다. 실행 대상은 Terraform이 선택한 개인 실험 DB여야 한다.

## 입력과 제한

| 환경변수 | 값·범위 | 이유 |
| --- | --- | --- |
| `CONFIRM_DISPOSABLE` | `slash-m2` 필수 | 합성 시험 환경임을 명시 |
| `PGHOST` | 서울 RDS 도메인만 허용 | DSQL·로컬·다른 리전 접속 거부 |
| `PGDATABASE` / `PGPORT` | `slash` / `5432` | 시험 DB 계약 고정 |
| `PGUSER` / `PGPASSWORD` | Terraform과 ECS secret 주입 | 저장소·명령줄에 비밀번호를 넣지 않음 |
| `DB_TEST_MODE` | 기본 `delay`, 명시적 `cancel-one` | 지연 시험과 단일 쿼리 취소를 분리 |
| `DB_TEST_EXPECTED_APP_IP` | `cancel-one`에만 필수 | 실행기가 실제 ECS core task에서 확인한 private IPv4 |
| `DB_TEST_PULSES` | 기본 1, 지연 1~18 / 취소 정확히 1 | 실행 횟수 제한 |
| `DB_TEST_INTERVAL_SECONDS` | 기본 10, 6~30 | 이전 실행 **완료 후** 다음 실행까지 대기 |
| `DB_TEST_START_DELAY_SECONDS` | 기본 15, 0~60 | 요청 실행기를 시작할 준비 시간 |

보수적인 실행 예산 `시작 대기 + 횟수×17 + (횟수-1)×간격`이 600초를 넘는 조합은 거부한다. SQL 프로세스 하나는 15초 뒤 종료 신호, 2초 뒤 강제 종료한다. 전체 실행기도 600초 뒤 종료 신호, 5초 뒤 강제 종료한다. 각 SQL의 잠금 획득·문장·트랜잭션 유휴 제한은 기존 SQL에 정의돼 있다.

`PGSSLMODE=verify-full`, 연결 제한 5초와 이미지에 포함한 서울 RDS CA를 사용한다. 서버 인증서의 신뢰 체인과 호스트 이름을 확인한다. libpq의 별도 서비스 파일·주소 우회 설정은 지운다. 동작 중에는 시작·완료·실패 이벤트와 시각만 출력하며, SQL 결과·비밀번호·토큰은 출력하지 않는다. 실패 원인은 대상 식별자와 시각을 기준으로 DB/네트워크 상태에서 별도로 확인한다.

**중지 신호가 DB 잠금을 즉시 푼다는 보장은 없다.** 클라이언트가 종료되어도 실행 중인 `pg_sleep`가 끝날 때까지 서버 쿼리가 잠시 남을 수 있다. 로컬 검증에서는 약 3초 이내에 해제됐으며, 문장·유휴 제한이 추가로 장기 잠금을 막는다. `pulse_start`는 연결 시도 시각이지 잠금 획득 증거가 아니다. `pulse_completed`는 SQL이 정상 종료한 경우에만 기록한다.

## 단일 5xx 준비 모드

`cancel-one`은 새로운 장애용 HTTP API를 만들지 않는다. 먼저 정상 로그인과 `/me` 조회를 끝낸 사용자가 같은 API를 호출할 때, [고정 SQL](../sql/db-query-cancel-one.sql)이 다음 순서로 움직인다.

| 단계 | 하는 일 | 제한 이유 |
| --- | --- | --- |
| 1 | 시험 연결이 `public.users`의 잠금을 획득 | 자신이 만든 대기만 대상으로 식별 |
| 2 | 최대 6초 동안 앱의 대기 쿼리를 탐색 | 요청이 없으면 실패하고 잠금을 해제 |
| 3 | 아래 조건을 모두 충족한 한 건이 두 차례 관측되는지 확인 | 다른 쿼리·동시 요청·대상 변경이면 취소 거부 |
| 4 | `pg_cancel_backend`를 한 번 호출 | 현재 쿼리만 중단하며 연결 종료 함수는 사용하지 않음 |
| 5 | 트랜잭션을 rollback하고 종료 | 데이터와 잠금을 남기지 않음 |

조건은 현재 DB `slash`, 현재 시험 연결과 같은 DB 사용자, ECS에서 확인한 정확한 앱 private IP, JDBC application name `PostgreSQL JDBC Driver`, `active` + `Lock` 대기, **시험 연결 자신의 PID가 실제 blocker**인 상태, 검토한 `UserRepository.findByCognitoSub` SELECT와의 정확한 일치다. 후보가 둘 이상이거나 다른 SELECT이면 즉시 실패한다. 0건이면 6초 후 실패한다. 값은 바인드되므로 사용자 식별자나 비밀번호가 출력되지 않는다. 앱 쿼리가 변경되면 SQL 조건을 넓혀 실행하지 말고 Java 쿼리 계약 테스트와 함께 재검토한다.

SQL은 한 시험 연결에서 잠금·검사·취소를 수행하고, 별도 앱 연결의 조회를 대상으로 삼는다. 앱 연결은 종료하지 않는다. 문장 제한 8초와 외부 프로세스 제한이 추가로 실행을 제한한다. 실행 중단 후에도 잠깐 남은 DB 작업이 끝날 수 있으므로 잠금 해제와 정상 응답을 확인한다.

`cancel_signalled`는 PostgreSQL이 취소 신호를 받았다는 뜻이다. **HTTP 500이나 CloudWatch Alarm 발생 증거가 아니다.** [단일 오류 관찰기](../requests/README.md)에서 정상 200 → 500 한 건 → 정상 200을 확인하고 같은 시각의 task 로그와 비교해야 한다. 기존 Spring 예외 처리기가 SQL 취소 예외를 500으로 바꾸는 것은 로컬 테스트로 확인한다. 실제 AWS 앱 호출·지표 수신·Alarm 전이는 아직 검증하지 않았다. 한 번의 500은 여러 평가 구간을 사용하는 Alarm의 발생을 보장하지 않는다.

공식 동작: [PostgreSQL 서버 신호 함수](https://www.postgresql.org/docs/16/functions-admin.html#FUNCTIONS-ADMIN-SIGNAL). `pg_cancel_backend=true`는 신호 전송 성공이며 쿼리 종료나 HTTP 결과의 증거와 구별한다.

## 이미지 준비

저장소 루트에서 실행한다.

[전용 제외 설정](Dockerfile.dockerignore)은 저장소 루트를 빌드 컨텍스트로 사용해도 실행 스크립트 2개·공개 CA·SQL 2개만 이미지 입력으로 허용한다. Terraform 상태·`tfvars`·`.terraform`과 그 밖의 파일은 전달 대상에서 제외하며, Dockerfile과 제외 설정 자체는 Docker가 빌드 정의로 별도 전달한다.

```sh
docker build --platform linux/amd64 \
  -f observability/personal/db-test/Dockerfile \
  -t slash-personal-db-test:preparation .
```

공식 PostgreSQL 16의 manifest digest를 고정했다. Debian 이미지에 포함된 GNU `timeout`을 재사용하며 추가 패키지를 설치하지 않는다. 이미지의 실행 사용자는 `postgres`다. AWS에는 검증한 이미지를 개인 ECR에 게시하고 **ECR에서 확인한 digest**를 `images["db-test"]`에 입력한다. 로컬 이미지 ID는 ECR 게시 완료 증거가 아니다.

서버 인바운드 포트는 필요 없다. 기존 환경에 NAT나 VPC endpoint가 없으므로 task는 public subnet/public IP를 통해 이미지·로그에 접근한다. DB 통신은 VPC의 private RDS로만 연결한다. task 실행은 Terraform apply와 분리된 명시적 일회성 실행으로 한다. 자동 재시작 service나 반복 일정을 만들지 않는다.

## 로컬 검증

```sh
python3 -m unittest discover -s observability/personal/db-test/tests -v
```

테스트는 Docker의 `--internal` 네트워크에 임시 PostgreSQL과 자체 시험 인증서를 만든다. 실제 runner 이미지는 localhost/임의 CA 옵션을 제공하지 않는다. 테스트 컨테이너에서만 시험 인증서를 읽기 전용으로 교체한다. AWS 접속은 없으며, 완료 후 DB 컨테이너·볼륨·네트워크·임시 인증서를 정리한다.

- 잘못된 대상·확인값·TLS 설정과 과도한 횟수·기간을 거부한다.
- 실제 SQL 때문에 별도 조회가 기다린 뒤 데이터 변경 없이 종료한다.
- 잠금 획득 충돌 시 실패하며 잔여 트랜잭션을 남기지 않는다.
- 신뢰하지 않는 서버 인증서를 거부한다.
- 실행 중 종료 신호를 보내도 실제 DB 잠금과 세션이 해제된다.
- 정확한 앱 SELECT 한 건만 취소하고, 다른 쿼리·IP·앱 이름·복수 후보·후보 없음은 거부한다.
- 단일 취소 후 데이터가 유지되고 컨트롤러 세션·잠금이 남지 않는다.

실제 RDS 네트워크·ECS secret 주입·CloudWatch 수신·Alarm 전이는 이 로컬 검증에 포함되지 않는다.

## 공개 CA 출처

`rds-ap-northeast-2-bundle.crt`는 AWS가 배포하는 **공개 CA 인증서**이며 비밀 키가 아니다.

- 원본: https://truststore.pki.rds.amazonaws.com/ap-northeast-2/ap-northeast-2-bundle.pem
- 확인일: 2026-10-28
- SHA-256: `913fb5b814f17af79d4c1622584a8d0ceddf5b0d76fe353d0c7d1186cdd6b229`
- 정책: [RDS TLS 인증서](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html), [PostgreSQL verify-full](https://www.postgresql.org/docs/16/libpq-ssl.html).

CA 변경 시 공식 파일과 fingerprint를 함께 갱신하고 이미지를 다시 검증한다.
