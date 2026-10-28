#!/bin/sh
# The task definition supplies the only target; never accept arbitrary SQL/args.
set -eu
fail() { printf '%s\n' "DB test refused: $1" >&2; exit 64; }
integer() {
  case "$2" in ''|*[!0-9]*|0?*|????*) fail "$1 must be a bounded integer" ;; esac
  [ "$2" -ge "$3" ] && [ "$2" -le "$4" ] || fail "$1 outside allowed range"
}
[ "$#" -eq 0 ] || fail 'command arguments are not supported'
[ "${CONFIRM_DISPOSABLE:-}" = slash-m2 ] || fail 'explicit disposable-target confirmation required'
[ "${PGDATABASE:-}" = slash ] || fail 'database must be slash'
[ "${PGPORT:-5432}" = 5432 ] || fail 'port must be 5432'
case "${PGHOST:-}" in ''|*[!a-z0-9.-]*) fail 'invalid RDS hostname' ;; esac
case "$PGHOST" in
  ?*.ap-northeast-2.rds.amazonaws.com) ;;
  *) fail 'target must be a Seoul RDS hostname; DSQL/local targets are forbidden' ;;
esac
[ -n "${PGUSER:-}" ] && [ -n "${PGPASSWORD:-}" ] || fail 'database credentials must be injected'
[ "${PGSSLMODE:-verify-full}" = verify-full ] || fail 'TLS hostname verification is required'
DB_TEST_PULSES=${DB_TEST_PULSES:-1}
DB_TEST_INTERVAL_SECONDS=${DB_TEST_INTERVAL_SECONDS:-10}
DB_TEST_START_DELAY_SECONDS=${DB_TEST_START_DELAY_SECONDS:-15}
integer DB_TEST_PULSES "$DB_TEST_PULSES" 1 18
integer DB_TEST_INTERVAL_SECONDS "$DB_TEST_INTERVAL_SECONDS" 6 30
integer DB_TEST_START_DELAY_SECONDS "$DB_TEST_START_DELAY_SECONDS" 0 60

DB_TEST_MODE=${DB_TEST_MODE:-delay}
case "$DB_TEST_MODE" in
  delay) ;;
  cancel-one)
    [ "$DB_TEST_PULSES" = 1 ] || fail 'cancel-one permits exactly one pulse'
    case "${DB_TEST_EXPECTED_APP_IP:-}" in ''|*[!0-9.]*) fail 'verified app IPv4 required' ;; esac
    old_ifs=$IFS; IFS=.; set -- $DB_TEST_EXPECTED_APP_IP; IFS=$old_ifs
    [ "$#" -eq 4 ] || fail 'verified app IPv4 required'
    for octet in "$@"; do integer IPv4 "$octet" 0 255; done
    if ! { [ "$1" -eq 10 ] || { [ "$1" -eq 172 ] && [ "$2" -ge 16 ] && [ "$2" -le 31 ]; } || { [ "$1" -eq 192 ] && [ "$2" -eq 168 ]; }; }; then
      fail 'app IPv4 must be private'
    fi
    export DB_TEST_EXPECTED_APP_IP
    ;;
  *) fail 'unsupported DB test mode' ;;
esac
export DB_TEST_MODE

budget=$((DB_TEST_START_DELAY_SECONDS + DB_TEST_PULSES * 17 + (DB_TEST_PULSES - 1) * DB_TEST_INTERVAL_SECONDS))
[ "$budget" -le 600 ] || fail 'combined worst-case runtime exceeds 600 seconds'
script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
[ -r "$script_dir/rds-ap-northeast-2-bundle.crt" ] || fail 'bundled RDS certificate missing'
unset PGSERVICE PGSERVICEFILE PGHOSTADDR PGPASSFILE PGOPTIONS
export PGPORT=5432 PGSSLMODE=verify-full PGCONNECT_TIMEOUT=5
export PGSSLROOTCERT="$script_dir/rds-ap-northeast-2-bundle.crt"
export PGAPPNAME=slash-m2-db-delay
export DB_TEST_PULSES DB_TEST_INTERVAL_SECONDS DB_TEST_START_DELAY_SECONDS
exec timeout --signal=TERM --kill-after=5s 600s "$script_dir/pulses.sh"
