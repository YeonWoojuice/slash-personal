# Prometheus 3.15.0, official linux/amd64 distroless manifest, checked 2026-10-28.
FROM prom/prometheus:v3.15.0-distroless@sha256:3e84c7d7c1b07a779c0d51ab41982dce05147a6bb49a674e8dec794a7ba25447
COPY --chown=65532:65532 prometheus.yml /etc/prometheus/prometheus.yml
COPY --chown=65532:65532 data/ /prometheus/
USER 65532:65532
WORKDIR /prometheus
ENTRYPOINT ["/bin/prometheus"]
# image.py appends the shared runtime arguments and verified config labels.
