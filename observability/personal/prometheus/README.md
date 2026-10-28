# 셸 없는 Prometheus 시험 이미지

공식 Prometheus **3.15.0 distroless linux/amd64** manifest를 고정한다. 앱 버전은 유지하고 BusyBox·셸·base64 실행 파일을 최종 이미지에서 제거한다. CA 인증서는 공식 기반 이미지가 제공하며 UID/GID `65532:65532`로 실행한다. 자체 BusyBox 패치나 새 설정 서버를 운영하지 않는다.

## 설정 원본과 이미지 준비

`config.json.tftpl`이 설정 원본이다. JSON은 Prometheus가 읽을 수 있는 YAML 형식이며, 대상 이름만 렌더링한다. Terraform도 같은 파일을 `templatefile`로 읽는다. `arguments.json`은 이미지와 ECS가 공유하는 실행 인자다. DNS `core.{name}.internal:9091`, `/actuator/prometheus`, 수집 간격 15초, loopback 9090, 보존 6시간·2GB를 유지한다.

저장소 루트에서 실행한다.

```sh
python3 observability/personal/prometheus/image.py build \
  --name slash-lab --image slash-personal-prometheus:m2-highfix-20261028
python3 observability/personal/prometheus/verify.py \
  --name slash-lab --image slash-personal-prometheus:m2-highfix-20261028
```

빌드 도구는 임시 디렉터리에 Dockerfile·렌더링한 설정·빈 데이터 디렉터리만 준비한다. 저장소 루트나 Terraform state·실제 tfvars는 Docker에 전달하지 않는다. 대상 이름과 설정 SHA-256을 이미지 label에 기록한 뒤, 만들어진 이미지의 실제 설정 파일·실행 인자·비루트 사용자를 다시 확인한다. 설정에 비밀값을 넣지 않는다. 이름이나 설정을 바꾸면 새 이미지를 만든다.

## Terraform 연결

게시 후 **ECR에서 확인한 immutable digest**를 로컬에서 확보하고 다음 도구로 계약 파일을 만든다. 이 명령은 게시나 AWS API 호출을 하지 않는다. 해당 digest의 이미지를 로컬 Docker가 가지고 있어야 한다.

```sh
python3 observability/personal/prometheus/image.py contract \
  --name slash-lab --image '실제ECR저장소@sha256:실제digest' \
  --output /private/tmp/prometheus-image-contract.tfvars.json
```

`experiment` 계획에 이 파일을 추가 `-var-file`로 전달하고 `images.prometheus`에도 같은 digest를 넣는다. monitoring 실행 시 이미지 참조·대상 이름·설정 해시 중 하나라도 다르거나 계약 파일이 없으면 Terraform이 거부한다. 이 입력 검사는 배포자가 검증한 이미지 정보를 연결하는 장치이며, 임의로 작성한 계약 파일의 진위를 AWS에서 자동 증명하지 않는다. CI도 같은 빌드·검증 도구를 사용한다.

## 로컬 검증 범위

`promtool check config`, 실제 Docker DNS discovery와 합성 지표 수집, TSDB WAL 쓰기, 대상 서버를 끈 뒤 재시작해 과거 지표 조회, loopback 외부 접근 거부, 비루트 실행과 셸·BusyBox·base64 부재를 확인한다. 별도 Python 컨테이너는 내부 네트워크의 시험 서버·관찰기로만 사용하며 제품 이미지에는 들어가지 않는다. 호스트 포트를 공개하거나 AWS 자격증명을 전달하지 않고 컨테이너·네트워크를 정리한다.

재시작 검사는 같은 컨테이너 파일시스템을 재사용한다. ECS task 교체 후 데이터 보존을 보장하지 않는다. 실제 Cloud Map·ECS·Slash·CloudWatch 동작과 ECR 보안 검사는 별도 검증이다.

공식 근거: [3.15.0 distroless Dockerfile](https://github.com/prometheus/prometheus/blob/v3.15.0/Dockerfile.distroless), [Prometheus 설정](https://prometheus.io/docs/prometheus/latest/configuration/configuration/).
