FROM grafana/grafana:12.4.0@sha256:b0ae311af06228bcfd4a620504b653db80f5b91e94dc3dc2a5b7dab202bcde20

# Grafana 12.4.0과 Alpine 3.23을 유지하고, ECR에서 발견한 OS 패키지만 갱신한다.
USER root
RUN apk add --no-cache \
    brotli-libs=1.2.1-r0 \
    curl=8.23.0-r0 \
    libcurl=8.23.0-r0 \
    libcrypto3=3.5.9-r0 \
    libssl3=3.5.9-r0 \
    zlib=1.3.2-r1 \
    musl=1.2.5-r24 \
    musl-utils=1.2.5-r24 \
    libcap2=2.78-r0 \
    nghttp2-libs=1.69.0-r0 \
    c-ares=1.34.9-r0
USER 472

COPY --chown=grafana:root provisioning/ /etc/grafana/provisioning/
COPY --chown=grafana:root dashboards/ /var/lib/grafana/dashboards/
