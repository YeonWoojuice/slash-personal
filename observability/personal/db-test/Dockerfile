# Official PostgreSQL 16 manifest index, checked 2026-10-28.
# Debian includes GNU timeout; no package installation is needed.
FROM postgres:16@sha256:1beaa3084eee2676f20a9cd9928f0bf2c5bf674f8e49f81017912183d377c61c
WORKDIR /opt/db-test
COPY observability/personal/db-test/entrypoint.sh observability/personal/db-test/pulses.sh ./
COPY observability/personal/db-test/rds-ap-northeast-2-bundle.crt ./
COPY observability/personal/sql/db-query-delay.sql observability/personal/sql/db-query-cancel-one.sql ./
RUN chmod 0555 entrypoint.sh pulses.sh && chmod 0444 *.crt *.sql
USER postgres
ENTRYPOINT ["/opt/db-test/entrypoint.sh"]
CMD []
