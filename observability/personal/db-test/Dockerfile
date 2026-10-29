# Official Alpine 3.24 manifest index, checked 2026-10-29.
# Client-only: this does not upgrade or install a database server.
FROM alpine:3.24@sha256:be2656061b536c1883c4034790e21d0a09c5aaaf51968b89368a3c0371ea2c9a

# Use signed packages from the supported stable release, without LDAP/SASL.
# GNU timeout is required for process-group termination and --kill-after.
RUN set -eux; \
    apk upgrade --no-cache; \
    apk add --no-cache \
      ca-certificates=20261020-r0 \
      postgresql18-client=18.6-r0 \
      libpq=18.6-r0 \
      coreutils=9.11-r0 \
      zlib=1.3.2-r1; \
    # The pinned base reserves GID 999 for an empty ping group.
    test "$(getent group 999)" = 'ping:x:999:'; \
    delgroup ping; \
    addgroup -S -g 999 dbtest; \
    adduser -S -D -H -u 999 -G dbtest -h /nonexistent -s /sbin/nologin dbtest; \
    psql --version; \
    timeout --version; \
    test -z "$(command -v postgres || true)"; \
    test -z "$(command -v initdb || true)"

WORKDIR /opt/db-test
COPY observability/personal/db-test/entrypoint.sh observability/personal/db-test/pulses.sh ./
COPY observability/personal/db-test/rds-ap-northeast-2-bundle.crt ./
COPY observability/personal/sql/db-query-delay.sql observability/personal/sql/db-query-cancel-one.sql ./
RUN chmod 0555 entrypoint.sh pulses.sh && chmod 0444 *.crt *.sql
USER 999:999
ENTRYPOINT ["/opt/db-test/entrypoint.sh"]
CMD []
