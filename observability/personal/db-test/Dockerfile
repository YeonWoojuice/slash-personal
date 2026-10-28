# Official Debian 13 manifest index, checked 2026-10-28.
# Install the PostgreSQL 16 client, not a local database server.
FROM debian:trixie-slim@sha256:89c1ea91e897f0fe0a3731595330bc45b8bdef4047464a07116f891a94054b31

# Pin the official PGDG signing key bytes; APT verifies repository signatures.
# https://www.postgresql.org/download/linux/debian/
ADD --checksum=sha256:0144068502a1eddd2a0280ede10ef607d1ec592ce819940991203941564e8e76 \
    https://www.postgresql.org/media/keys/ACCC4CF8.asc /usr/share/keyrings/pgdg.asc
RUN set -eux; \
    chmod 0644 /usr/share/keyrings/pgdg.asc; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates=20250419+deb13u1; \
    printf '%s\n' \
      'Types: deb' \
      'URIs: https://apt.postgresql.org/pub/repos/apt' \
      'Suites: trixie-pgdg' \
      'Components: main' \
      'Signed-By: /usr/share/keyrings/pgdg.asc' \
      > /etc/apt/sources.list.d/pgdg.sources; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      postgresql-client-16=16.15-1.pgdg13+2 \
      postgresql-client-common=293.pgdg13+1 \
      libpq5=18.6-1.pgdg13+2; \
    rm -rf /var/lib/apt/lists/*; \
    groupadd --gid 999 postgres; \
    useradd --uid 999 --gid postgres --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin postgres; \
    psql --version; \
    timeout --version

WORKDIR /opt/db-test
COPY observability/personal/db-test/entrypoint.sh observability/personal/db-test/pulses.sh ./
COPY observability/personal/db-test/rds-ap-northeast-2-bundle.crt ./
COPY observability/personal/sql/db-query-delay.sql observability/personal/sql/db-query-cancel-one.sql ./
RUN chmod 0555 entrypoint.sh pulses.sh && chmod 0444 *.crt *.sql
USER postgres
ENTRYPOINT ["/opt/db-test/entrypoint.sh"]
CMD []
