#!/bin/sh
set -eu
script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
child=''
event() {
  printf '{"event":"%s","pulse":%s,"at":"%s"}\n' "$1" "$2" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
cleanup() {
  if [ -n "$child" ]; then
    kill -TERM "$child" 2>/dev/null || true
    wait "$child" 2>/dev/null || true
    child=''
  fi
}
stop() { event stopped 0; cleanup; exit 143; }
trap stop TERM INT
trap cleanup EXIT
run_child() {
  "$@" >/dev/null 2>&1 &
  child=$!
  result=0
  wait "$child" || result=$?
  child=''
  return "$result"
}
event waiting 0
run_child sleep "$DB_TEST_START_DELAY_SECONDS"
i=1
while [ "$i" -le "$DB_TEST_PULSES" ]; do
  # This is a connection attempt, not proof that a lock was acquired.
  event pulse_start "$i"
  if [ "$DB_TEST_MODE" = cancel-one ]; then
    if ! run_child timeout --signal=TERM --kill-after=2s 15s \
        psql -X --no-password --quiet --set="expected_ip=$DB_TEST_EXPECTED_APP_IP" \
        --file="$script_dir/db-query-cancel-one.sql"; then
      event cancel_refused_or_failed "$i"
      exit 1
    fi
    # Signal acceptance is not proof of an HTTP 500; correlate the HTTP probe.
    event cancel_signalled "$i"
  else
    if ! run_child timeout --signal=TERM --kill-after=2s 15s \
        psql -X --no-password --quiet --file="$script_dir/db-query-delay.sql"; then
      event pulse_failed "$i"
      exit 1
    fi
  fi
  event pulse_completed "$i"
  if [ "$i" -lt "$DB_TEST_PULSES" ]; then
    run_child sleep "$DB_TEST_INTERVAL_SECONDS"
  fi
  i=$((i + 1))
done
event completed "$DB_TEST_PULSES"
