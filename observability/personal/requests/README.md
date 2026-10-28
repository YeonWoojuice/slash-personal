# DB 시험용 요청 실행기

`run.py`는 실제 로그인한 사용자의 `GET /api/v1/me`를 제한된 횟수로 호출하고 응답 상태·구간별 시간·검증한 요청 식별번호를 저장한다. DB 장애를 만들거나 AWS 자원을 시작하지 않는다. 정상 기준선용 k6의 p95 제한을 적용하지 않으므로 3초 후 정상 200이 돌아오는 요청은 실패로 처리하지 않는다.

## 입력과 실행

Python 3.10 이상에서 추가 패키지 없이 실행한다. 실제 배포한 Slash의 HTTPS 주소와 Cognito 설정을 사용한다. 개인 도메인은 origin만 허용한다. 도메인이 없는 시험안의 서울 API Gateway 기본 주소에는 한 개의 stage 경로도 허용한다. 아래 값을 실제 출력으로 설정하되 토큰 값을 명령행이나 채팅에 붙이지 않는다.

```sh
export API_BASE_URL=https://개인API호스트
export COGNITO_ISSUER_URI=https://cognito-idp.ap-northeast-2.amazonaws.com/실제풀ID
export COGNITO_CLIENT_ID=실제클라이언트ID
python3 observability/personal/requests/run.py \
  --seconds 180 --interval 1 --timeout 8 \
  --output /private/tmp/slash-db-delay-첫실행
```

도메인 없는 배포안이 실제 구성된 뒤에는 `API_BASE_URL=https://실제APIID.execute-api.ap-northeast-2.amazonaws.com/m2`처럼 지정할 수 있다. 이때 정확히 `/m2/api/v1/me`를 호출한다. 임의 호스트의 경로, 여러 경로 구간, 다른 리전의 stage URL은 받지 않는다. 이 URL 지원이 API Gateway 배포 완료를 뜻하지는 않는다.

대화형 터미널에서는 토큰 입력을 숨기는 프롬프트가 나타난다. 자동화에는 `API_ACCESS_TOKEN` 환경변수 또는 `--token-file /private/tmp/개인토큰파일` 중 하나만 사용한다. 파일은 본인 소유·권한 600이어야 하며 심볼릭 링크를 받지 않는다. 출력 디렉터리는 매번 새 이름을 쓴다. 토큰 파일은 실험 후 삭제한다.

| 제한 | 값 |
| --- | --- |
| 요청 대상 | HTTPS origin의 `/api/v1/me`, 또는 허용한 Gateway stage의 같은 경로 하나 |
| 기본 관측 구간 | 180초 |
| 최대 관측 구간 | 300초 |
| 발송 간격 | 1~5초, 기본 1초 |
| 동시 요청 | 최대 4건. 밀린 요청을 나중에 몰아서 보내지 않음 |
| 요청 수 | 기본 최대 180건 + 사전 검사 1건, 최대 300건 + 사전 검사 1건 |
| 요청 제한 시간 | 기본 8초, 최대 10초 |
| 리다이렉트 | 따라가지 않음. 다른 호스트로 토큰을 전달하지 않음 |
| TLS | 인증서·호스트 검증. 검증 해제 옵션 없음 |

처음 한 요청이 정상 200이고 기존 `/me` 응답 형태인지 확인한 뒤 관측을 시작한다. 토큰은 access 용도·발급자·client ID·남은 유효기간을 로컬에서 점검한다. 이 점검은 서명 검증이 아니며, 실제 인증 판단은 API가 한다. 토큰의 남은 수명은 `관측 시간 + 요청 제한 시간 × 2 + 30초`보다 길어야 한다.

401/403을 확인하면 신규 요청 발송을 중단한다. 이미 전송 중인 최대 4건은 종료까지 기록한다. 네트워크 오류·다른 HTTP 오류·응답 형식 오류·동시성 한도로 생략한 요청은 결과에 남기며 재시도하지 않는다. 요청 시작부터 하나의 제한 시간을 공유하고 연결 전부터 소켓을 중단 대상으로 등록한다. DNS를 기다리는 시간도 제한하지만 운영체제 조회 자체를 취소하지는 못한다. 끝나지 않은 조회는 최대 4개 daemon 작업으로 제한한다. 인증서 설정 생성·운영체제의 실행 정지·정리까지 정확한 벽시계 종료를 보장하지 않는다.

## DB 작업과 맞추기

1. 먼저 실제 Cognito 로그인과 정상 `/me` 200을 확인한다.
2. 일회성 DB 작업을 시작하고 ECS의 `RUNNING` 상태를 확인한다.
3. DB 작업의 초기 대기 시간 안에 이 요청 실행기를 시작한다. 요청 실행기의 사전 검사와 관측 시작 시간을 확인한다.
4. DB 작업 로그의 접속 시도(`pulse_start`)·SQL 완료(`pulse_completed`) 구간을 요청 기록과 비교한다. 접속 시도는 정확한 잠금 획득 시각이 아니므로 SQL 완료와 실제 지연 응답을 함께 확인한다. 작업 상태 `RUNNING`만으로 잠금 시작 시각을 판단하지 않는다.
5. 시작이 늦어 첫 잠금과 사전 검사가 겹치거나 장애 구간과 요청이 겹치지 않았다면 그 사실을 기록한다. 관측 구간과 DB 작업의 시작 지연·반복 횟수를 다음 실행에서 맞춘다.
6. 종료 후 DB 작업의 성공 종료·잠금 해제·다음 정상 응답을 확인한다. 요청 실행기 종료가 DB 작업을 중지하지는 않는다.

현재 DB 작업의 기본 한 번 실행은 3초 지연 동작을 확인하기 위한 것이다. 여러 60초 구간의 Alarm 전이를 확인하려면 별도로 제한한 DB 반복 설정과 충분한 요청 수가 필요하다.

## 결과와 종료 코드

- `requests.jsonl`: 요청 번호, 사전 검사/관측 구분, UTC 시작·종료 시각, HTTP 상태, 전체·구간별 시간, 분류된 오류와 허용한 요청 식별번호를 저장한다. 동시성 한도로 건너뛴 요청에는 `capacity_skipped`를 기록한다.
- `summary.json`: 발송·오류·생략 수와 설정을 저장한다. 파일 권한은 600, 디렉터리는 700이다.
- 응답 본문, 사용자 정보, JWT, 인증 헤더는 저장하거나 출력하지 않는다.
- 종료 0: 실행한 요청에서 관측 오류가 없었음. CloudWatch나 Alarm 성공을 의미하지 않는다.
- 종료 1: 사전 검사/인증/요청 오류 또는 생략 발생. 종료 2: 입력·출력 설정 오류. 종료 130: 사용자가 중단함. 중단 전 요청 기록은 남지만 summary가 없을 수 있다.

```sh
python3 -m unittest discover -s observability/personal/requests -p 'test_*.py' -v
```

오프라인 테스트는 HTTPS·토큰·응답 형식 제한, 리다이렉트 차단, 비밀 값 미기록, 인증 실패 중단, 동시 요청 상한, 결과 권한을 검증한다. 실제 Cognito·ALB·Spring 앱과의 호출은 배포 후 환경 검증이다.

2026-10-28 로컬 확인: 오프라인 테스트 19개 통과(기본 관찰 14개 + 단일 5xx 관찰 5개, stage 경로 제한 포함). 별도 임시 HTTPS 서버에서 정상 200, 외부 리다이렉트 미추적, 느린 본문의 제한 시간 종료(0.2초 설정 시 약 0.203초), 신뢰되지 않은 인증서 거부를 확인했다. 임시 서버와 인증서 파일은 정리했으며 AWS API·실제 로그인 토큰은 사용하지 않았다.

## 단일 5xx 관찰 모드

`cancel_probe.py`는 명시적 `cancel-one` DB 작업과 함께 사용하는 별도 실행기다. 기본 `run.py`는 계속 모든 HTTP 오류를 실패로 취급한다. 단일 5xx 관찰기도 네트워크 오류나 임의 5xx를 성공으로 바꾸지 않는다.

```sh
python3 observability/personal/requests/cancel_probe.py \
  --seconds 30 --timeout 8 \
  --token-file /private/tmp/slash-access-token.txt \
  --output /private/tmp/slash-cancel-observation-첫실행
```

위 URL·issuer·client ID 설정을 그대로 사용하며, 토큰을 숨겨서 입력하거나 환경변수로 전달하는 방법도 동일하다. 실제 task가 `RUNNING`이 된 뒤 초기 대기 시간 안에 시작한다. 최초 정상 사용자 조회는 DB 작업 시작 전 미리 완료한다. 요청 실행기를 여러 개 동시에 실행하지 않는다.

| 구간 | 통과 조건 | 실패 조건 |
| --- | --- | --- |
| 사전 검사 | 기존 `/me` 형식의 정상 200 | 첫 요청부터 500·인증 오류·응답 형식 오류 |
| 관찰 | 한 번에 요청 1건, 기본 30초·최대 60초 내 500 한 건 | 500 미관측, 401/403, 502 등 다른 상태, timeout·TLS·연결 오류 |
| 후속 검사 | 1초 대기 후 기존 `/me` 형식의 정상 200 | 두 번째 500 또는 다른 오류 |

요청 간 최소 1초를 쉬고, 대기 중인 요청을 겹쳐 보내지 않는다. 최대 60건의 관찰 요청과 사전·후속 검사 각 1건으로 제한한다. 관찰 구간 끝에 진행 중인 요청과 후속 검사가 더해질 수 있다. 출력 형식과 파일 권한은 기본 실행기와 같고 JWT·본문·사용자 정보를 저장하지 않는다.

종료 0의 `observed_500_then_200`은 이 관찰기에서 해당 순서의 상태를 봤다는 뜻이다. 오류의 원인이 DB 취소였다는 증명은 task `cancel_signalled` 시각·앱 기록과 대조해야 한다. 후속 200은 이 API 요청의 성공이며 전체 서비스 복구 판정이 아니다. CloudWatch 지표·Alarm·M3 Incident 기록은 별도 AWS 환경 검증 항목이다.

추가 오프라인 테스트는 정확한 200→500→200, 500 미관측, 사전 실패, 인증/통신/다른 5xx 실패, 후속 500 거부를 확인한다. AWS에 요청하거나 장애를 발생시키지 않는다.

## 짧은 정상 요청 단계 관측

`step_probe.py`는 AWS 정상 동작을 확인한 뒤, 같은 읽기 API의 요청 간격을 조금씩 줄여 그래프 변화를 관찰하는 별도 모드다. 기존 `run.py`의 DB 지연 관찰 동작과 기준은 바꾸지 않는다. DB 장애 주입·캐시 변경·AWS 자원 생성은 하지 않는다.

| 단계 | 초당 요청 목표 | 요청 간격 | 관측 시간 | 예정 요청 수 |
| --- | --- | --- | --- | --- |
| 1 | 0.5건 | 2초 | 120초 | 60건 |
| 2 | 1건 | 1초 | 120초 | 120건 |
| 3 | 2건 | 0.5초 | 120초 | 240건 |
| 4 | 5건 | 0.2초 | 120초 | 600건 |

사전 정상 요청 1건 → 네 단계의 1,020건 → 사후 정상 요청 1건 → 요청을 보내지 않는 120초 관찰 순서다. 성공한 실행은 총 1,022건이고 요청 단계 8분·마지막 관찰 2분이다. 별도로 수행하는 로그인 검증 요청과 Grafana 화면 요청은 이 숫자에 포함하지 않는다. 단계 사이에 60초 대기를 추가하지 않는다.

```sh
python3 observability/personal/requests/step_probe.py \
  --base-url https://실제APIID.execute-api.ap-northeast-2.amazonaws.com/m2 \
  --issuer https://cognito-idp.ap-northeast-2.amazonaws.com/실제풀ID \
  --client-id 실제웹clientID \
  --token-file /private/tmp/개인토큰파일 \
  --output /private/tmp/slash-step-새실행
```

기존 입력 검사를 재사용하며, 토큰의 남은 수명은 시작 시 642초보다 길어야 한다. 실제 서명·권한 판단은 API가 수행한다. 로그인 도구에서 직접 연결할 때는 `run_probe(origin, token, emit, request=...)`에 메모리의 토큰을 전달할 수 있다. 출력에 토큰·응답 본문·사용자 정보는 저장하지 않는다. `request`에는 기존 `request_once`와 검증된 TLS context를 전달할 수 있으며 인증서 검증을 끄지 않는다.

동시 요청은 최대 4건, 요청 제한 시간은 3초다. 다음 중 하나를 발견하면 **신규 요청을 즉시 중단**하고 이미 보낸 최대 4건의 결과만 수집한다. 실패 후 사후 요청이나 자동 재시도는 하지 않으며, 요청 없는 120초 관찰 구간을 유지한다.

- 200 이외의 HTTP 상태, 통신·TLS·응답 형태 오류
- 완료된 요청의 소요 시간이 2,000ms를 초과하거나, 진행 중인 요청이 2초를 넘김
- 동시성 한도로 예정 요청을 보내지 못함
- 목표 일정에서 누적 지연이 3초를 초과하거나, 요청 단계 시작 후 483초 한도에 도달함

실제 발송 간격은 직전 발송 시각을 기준으로 유지하므로 잠깐 늦어진 요청을 다음 요청과 붙여 보내지 않는다. 운영체제의 작은 실행 지연으로 120초 목표 구간이 약간 늘어날 수 있으며 실제 첫·마지막 발송 시각과 구간 길이를 함께 기록한다. 네 단계 목표 합계는 480초, 신규 발송의 전체 시간 한도는 483초다. 한도를 넘으면 미발송 요청을 채우지 않고 중단한다. 이후 이미 진행 중인 요청 정리와 120초 관찰은 별도이며, 운영체제가 실행기를 멈춰 둔 시간까지 정확한 종료 시간을 보장하지 않는다.

이 2초 기준은 이번 관측 도구의 정지 조건이며 운영 SLO나 M2 Alarm 임계값이 아니다. 5rps에서도 응답이 길어져 동시 4건을 넘으면 관측이 중단된다. 그러므로 결과를 서비스 최대 처리량이나 성능 한계로 해석하지 않는다. 지연 값은 시험자 PC의 DNS·연결·TLS·네트워크를 포함하는 클라이언트 관측값이다. 앱이 발행하는 서버 처리시간과 구분한다.

각 단계의 120초 구간은 실행 시작 시각을 기준으로 한다. CloudWatch의 60초 집계 경계와 반드시 일치하지 않으므로 한 지표 구간에 앞뒤 단계 요청이 함께 들어갈 수 있다. 요청 UTC 시각과 지표 시각을 나란히 확인하고, 단계별로 정확히 두 개의 독립 지표 구간이 나온다고 가정하지 않는다. 평균·p95·최대 지연은 참고 관측치이며 단 한 번의 1,020건 시험으로 Alarm·복구·M3 완료를 주장하지 않는다.

출력은 권한 600의 `requests.jsonl`과 `summary.json`이다. 단계별 예정·발송·완료·실패·생략 수, 클라이언트 지연 평균·p95·최대, 정지 원인을 기록한다. 결과 필드를 제한해 임의 오류 메시지·본문이 섞이지 않게 한다. 종료 0은 예정 요청 전부와 사전·사후 검사가 통과한 경우이고, 종료 1은 중단, 2는 입력·출력 오류, 130은 사용자 중단이다. DNS 대기·연결·전송·수신은 한 제한 시간을 공유하지만 인증서 설정 생성이나 운영체제의 실행 정지까지 강제로 끝내는 것은 아니다.

오프라인 검사에서는 요청·시계·실행기를 주입해 1,022건의 전체 스케줄, 오류·지연·동시성 초과 시 중단, 지연된 요청의 몰아 보내기 방지, 민감정보 제외와 파일 권한을 확인한다. 실제 AWS 부하는 실행하지 않는다.

## 지연 구간과 같은 요청의 앱 기록 비교

2026-10-29의 2,054.693ms 요청은 당시 전체 시간만 저장했으므로 원인을 소급 확정할 수 없다. 아래 보강은 이후 요청을 위한 것이며 기존 실행 근거를 덮어쓰지 않는다. 기존 `elapsed_ms`와 오류·중단 기준은 유지하고 `timing_ms`를 추가했다. 매 요청은 여전히 새 HTTPS 연결이며 연결 재사용 성능 시험이 아니다.

| `timing_ms` 필드 | 측정 범위 | 확인할 내용 |
| --- | --- | --- |
| `client_setup` | 인증서 검증 설정과 연결 객체 준비 | 시험 PC의 준비 단계가 지연됐는가 |
| `dns` | 제한된 resolver 슬롯 대기와 호스트 주소 조회 | 주소 조회 대기에서 시간이 소모됐는가 |
| `tcp_connect` | 반환된 주소 후보의 TCP 연결 시도 합계 | 서버까지 연결을 맺는 과정이 늦었는가 |
| `tls_handshake` | 인증서를 검증하며 HTTPS 보안 연결 수립 | TLS 협상 단계가 늦었는가 |
| `request_send` | GET 요청 헤더 전송 | 요청 전송이 지연됐는가 |
| `response_headers_wait` | 전송 후 상태행·응답 헤더를 모두 읽을 때까지 | 응답을 기다리는 구간이 긴가. 정확한 첫 바이트 시간이나 앱 처리시간은 아님 |
| `response_body` | 제한된 크기의 응답 본문 수신 | 헤더 이후 본문 수신이 늦었는가 |
| `validation` | 본문 크기·기존 `/me` 응답 형태 확인 | 로컬 검증에 시간이 걸렸는가. 본문 자체는 저장하지 않음 |
| `cleanup` | 응답·연결 닫기 | 로컬 종료 처리에 시간이 걸렸는가 |

완료한 구간만 숫자를 기록하고 미시작·미완료는 `null`로 남긴다. 통신 예외가 발생한 구간은 `phase_at_failure`와 `failed_phase_elapsed_ms`로 따로 표시한다. 0ms와 미측정은 다르다. 구간 사이의 계측·스케줄링 비용이 있어 합계가 전체 시간과 정확히 같지는 않다. `step_probe.py`도 이 필드를 검증해서 전달하며 2초 정지 기준을 낮은 구간 값으로 대체하지 않는다.

| 연결 번호 | 기록 위치와 용도 |
| --- | --- |
| `client_probe_id` | 실행기가 요청마다 생성한 UUID. 요청 `X-Slash-Probe-Id`와 앱 `clientProbeId`를 연결 |
| `correlation.app_request_id` | 앱이 생성해 응답 `X-Slash-Request-Id`로 돌려주는 UUID. 앱 `appRequestId`와 연결 |
| `correlation.gateway_extended_request_id` | 응답 `x-amz-apigw-id`. Terraform이 Gateway의 `extendedRequestId`를 앱 헤더로 매핑하면 앱 `gatewayRequestId`와 연결 |
| `correlation.gateway_request_id` | 응답 `x-amzn-requestid`의 검증된 UUID. 클라이언트가 요청 ID를 덮어쓸 수 있어 주 연결 번호로 사용하지 않음 |

앱의 `personal_request_timing` 로그는 `personal` 프로필과 `PERSONAL_REQUEST_TIMING_ENABLED=true`에서만 켠다. 기본값은 꺼짐이며 시험 Terraform은 API 컨테이너에만 켜도록 구성했다. 앱 포트의 `GET /api/v1/me`만 기록한다. JSON 필드는 `event`, `timestamp`, `route`, `clientProbeId`, `appRequestId`, `gatewayRequestId`, `status`, `durationMs`의 8개다. 인증 필터 전부터 downstream 처리 종료까지 측정해 401/403도 포함하며, 미처리 예외로 최종 상태를 모르면 `status=null`이다. Tomcat 대기열·앞선 필터·네트워크·응답 전송 전체 시간은 포함하지 않는다. 식별번호는 관측용이며 인증·소유권 증거가 아니다. 요청 ID를 메트릭 라벨로 추가하지 않는다.

`latency_report.py`는 저장한 파일만 읽는다. 앱 로그는 위 JSON 메시지를 한 줄에 하나씩 저장하거나 CloudWatch의 `{"message":"Spring 접두사와 JSON 메시지"}` 형식 JSONL로 넘긴다. 로그를 넣지 않아도 클라이언트 구간을 볼 수 있다.

```sh
python3 observability/personal/requests/latency_report.py \
  --requests /private/tmp/slash-step-새실행/requests.jsonl \
  --app-logs /private/tmp/slash-app-timing.jsonl \
  --output /private/tmp/slash-latency-report.json
```

도구는 느린 요청 최대 10개와 가장 긴 완료 구간, 같은 ID로 찾은 앱 시간·상태를 권한 600의 새 파일에 저장한다. ID가 충돌하거나 여러 앱 기록이 일치하면 하나를 임의 선택하지 않는다. 과거 전체 시간만 있는 요청은 `legacy_requests_without_timings`로 구분한다. 입력 원문 헤더·본문·예외·사용자 필드는 결과로 복사하지 않는다. AWS 호출이나 새 HTTP 요청은 하지 않는다.

**해석 예:** TLS 시간이 크면 보안 연결 구간을 조사한다. 응답 헤더 대기가 크면 같은 요청의 앱 시간과 나란히 확인한다. 앱 시간이 짧다고 나머지 시간을 전부 네트워크 지연으로 단정하지 않는다. 앱 시간은 클라이언트 시간 안에 겹치는 별도 범위이므로 합산하지 않는다.

Gateway 자체의 요청별 `responseLatency`·`integrationLatency`는 이번에 켜지 않았다. 서울 계정의 REST `cloudWatchRoleArn`이 미설정이므로 공용 로그 역할을 별도로 설계해야 한다. 일반 ALB access log도 원문 IP·URI 등을 포함하므로 활성화하지 않았다. 실제 Gateway 헤더 전달·앱 로그 연결은 새 API 이미지와 설정을 배포한 뒤 검증할 항목이다. 이번 보강만으로 AWS 재배포·원인 확정·M2/M3 완료를 표시하지 않는다.

근거: [Python HTTP 응답 읽기](https://docs.python.org/3/library/http.client.html), [Python 소켓과 주소 조회](https://docs.python.org/3/library/socket.html), [AWS Gateway 요청 ID](https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-variables-for-access-logging.html), [요청 헤더 매핑](https://docs.aws.amazon.com/apigateway/latest/developerguide/rest-api-parameter-mapping-sources.html), [REST 로그 역할](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-logging.html).
