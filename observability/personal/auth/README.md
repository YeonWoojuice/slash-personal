# LambdaOps 조회 인증 준비

Slash 웹 로그인과 LambdaOps 장애 조회는 같은 개인 Cognito pool을 사용하되 app client와 scope를 구분한다. 로그인 성공만으로 장애 조회 권한을 확인했다고 기록하지 않는다.

| 용도 | client·권한 | callback |
| --- | --- | --- |
| Slash 웹 | 기존 web client, `openid email profile` | `http://localhost:5173/callback` 유지 |
| LambdaOps 조회 | 별도 public operator client, `openid lambdaops/incidents.read` | `http://localhost:8765/callback` |

Cognito resource server `lambdaops`와 `incidents.read` scope를 추가한다. 발급된 전체 scope는 `lambdaops/incidents.read`다. operator client에는 client secret을 만들지 않으며 authorization code + PKCE(S256)로 로그인한다. 비밀번호는 Cognito 화면에서만 입력한다.

현재 개인 pool은 초대된 사용자만 로그인할 수 있다. **별도 public client는 사용자별 관리자 권한 경계가 아니다.** 이 pool의 로그인 사용자는 operator client가 허용하는 읽기 scope를 요청할 수 있다. 현재 1인 프로젝트의 계정 전체 읽기 범위이며, 다중 사용자·조직별 소유권이나 그룹 승인은 이번 변경에서 도입하지 않는다.

## 배포 후 연결할 값

foundation의 두 출력에는 비밀값이 없다.

| 출력 | 쓰임 |
| --- | --- |
| `lambdaops_auth` | 아래 로컬 로그인 도구의 issuer/client/login domain/callback/scope |
| `lambdaops_m3_auth_tfvars` | LambdaOps dev M3에 전달할 `jwt_issuer`, `jwt_audience`, `read_authorization_scope` |

`jwt_audience`에는 operator client ID를 넣는다. Cognito access token에 `aud`가 없으면 API Gateway JWT authorizer는 `client_id`를 검사한다. `read_authorization_scope`는 API Gateway 경로와 조회 Lambda의 `REQUIRED_READ_SCOPE`에 같은 값으로 전달된다. 백엔드의 일반 기본값 `incidents:read`는 바꾸지 않았으며 이 Cognito 배포에서만 명시적으로 설정한다.

아래 명령은 foundation을 실제로 생성한 뒤 사용한다. 지금은 Cognito·조회 HTTP API가 없어 실제 로그인·프로브를 실행하지 않았다.

```sh
umask 077
terraform -chdir=infra/personal/foundation output -json lambdaops_auth > /private/tmp/lambdaops-auth.json
terraform -chdir=infra/personal/foundation output -json lambdaops_m3_auth_tfvars > /private/tmp/lambdaops-m3-auth.tfvars.json
```

LambdaOps 저장소에서는 기존 `dev.tfvars`와 위 인증 변수 파일을 함께 검토한다. `dsql_schema_ready=true`와 실제 issuer/client가 준비된 뒤 `enable_http_api=true`를 별도로 설정한다. 출력 파일을 얻었다는 이유만으로 API를 자동 활성화하지 않는다. Slash web client ID를 M3 audience에 복사하지 않는다.

## 로컬 로그인

Python 3.9 이상, 추가 패키지 없이 동작한다. foundation에서 만든 pool에 사용자가 실제로 등록되어 있어야 한다. 이 도구는 사용자 생성·초대 메일 발송·비밀번호 설정을 하지 않는다.

```sh
python3 observability/personal/auth/auth.py \
  --config /private/tmp/lambdaops-auth.json login \
  --token-file /private/tmp/lambdaops-read-token --open-browser
```

도구는 loopback `127.0.0.1:8765`에서 최대 5분 동안 callback을 기다린다. `--open-browser`를 빼면 로그인 주소만 표시하므로 사용자가 직접 열 수 있다. callback의 경로·Host·임의 state를 확인하고, code를 같은 PKCE verifier로 HTTPS token endpoint에 교환한다. 리다이렉트를 따라 토큰이나 code를 다른 호스트에 전달하지 않는다.

access token만 새 파일에 권한 600으로 저장한다. 기존 파일·심볼릭 링크는 덮어쓰지 않으며 ID token·refresh token·비밀번호는 저장하거나 출력하지 않는다. 토큰은 저장소 밖에 두고 시험 후 삭제한다. 토큰의 종류·발급자·client·scope·남은 유효기간을 로컬에서 확인하지만, 이 확인은 서명 검증을 대신하지 않는다. 실제 API Gateway가 JWT 서명과 권한을 검증한다.

## 권한 없음 토큰과 읽기 검증

403을 정확히 확인하려면 **같은 operator client**에서 읽기 scope를 요청하지 않은 access token을 한 번 더 발급한다. Slash web client의 토큰을 대신 쓰면 audience가 달라 401이 될 수 있어 scope 검증과 구분되지 않는다.

```sh
python3 observability/personal/auth/auth.py \
  --config /private/tmp/lambdaops-auth.json login \
  --without-read-scope --token-file /private/tmp/lambdaops-no-scope-token --open-browser
```

두 토큰과 실제 M3 HTTP API 주소를 사용한다. 개인 API URL 대신 승인한 서울 `execute-api` HTTPS 주소만 받는다. `/incidents`와 지정한 Incident 상세만 GET으로 호출한다.

```sh
python3 observability/personal/auth/auth.py \
  --config /private/tmp/lambdaops-auth.json probe \
  --api-url https://실제M3APIID.execute-api.ap-northeast-2.amazonaws.com \
  --token-file /private/tmp/lambdaops-read-token \
  --no-scope-token-file /private/tmp/lambdaops-no-scope-token \
  --incident-id inc_실제로생성된IncidentID \
  --result /private/tmp/lambdaops-auth-probe-새실행.json
```

실제 ID는 `inc_` 뒤 32자리 소문자 16진수다. 데이터가 없을 때는 `--incident-id`를 생략해 목록만 확인할 수 있으나, 그 결과는 M3의 인증된 Detail 완료 증거가 아니다. 최초 시험에는 실제 생성된 Incident ID를 사용한다. 기존 ID가 대표 ID에 연결된 경우도 정상 상세 조회다. 도구는 `requestedIncidentId`가 요청 ID와 같은지, 대표 `incidentId`의 형식이 맞는지, `redirected`가 두 ID의 차이와 일치하는지, `stateHistory`가 목록인지 확인한다.

| 요청 | 기대 결과 |
| --- | --- |
| 올바른 operator access token·읽기 scope | 목록 200, 실제 존재하는 상세 200 |
| 토큰 없음 | 401 |
| 같은 client의 access token·읽기 scope 없음 | 403 |

최대 6회 GET을 순서대로 호출하고 재시도하지 않는다. HTTPS 검증을 유지하고 redirect를 따르지 않는다. 각 네트워크 요청은 socket 제한 10초·응답 크기 1 MiB 제한을 둔다. 파일과 표준 출력에는 검사 시각·목록/상세 구분·기대/실제 HTTP 상태·통과 여부만 남긴다. 토큰·본문·사용자 정보·Incident 상세 데이터는 기록하지 않는다. 종료 0은 요청한 검사 통과, 1은 실패, 130은 사용자 중단이다.

## 로컬 검증과 한계

```sh
python3 -m unittest discover -s observability/personal/auth -p 'test_*.py' -v
```

오프라인 테스트는 PKCE 기준 벡터, callback state, 같은 client의 scope 차이, 계정·호스트 제한, 토큰 파일 권한, redirect 차단과 최소 응답 형태, 기존 ID의 정상 대표 연결 및 모순된 상세 응답 거부를 확인한다. fixture JWT는 실제 서명된 토큰이 아니다. 실제 Cognito 로그인·API Gateway JWT 검증·인증된 DSQL 상세 조회는 배포 후 별도 환경 검증이다.

공식 근거: [Cognito authorization code·PKCE](https://docs.aws.amazon.com/cognito/latest/developerguide/authorization-endpoint.html), [token endpoint](https://docs.aws.amazon.com/cognito/latest/developerguide/token-endpoint.html), [Cognito resource server scope](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-define-resource-servers.html), [HTTP API JWT authorizer](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html).
