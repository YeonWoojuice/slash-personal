-- Disposable Slash PostgreSQL only. A separate app request must already be
-- authenticated and match the reviewed UserRepository.findByCognitoSub query.
-- The controller owns the lock and cancels at most one app statement, never a
-- backend connection. Failure rolls back when noninteractive psql exits.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL application_name = 'slash-m2-cancel-controller';
SET LOCAL lock_timeout = '1s';
SET LOCAL statement_timeout = '8s';
SET LOCAL idle_in_transaction_session_timeout = '5s';
SELECT set_config('slash_test.expected_ip', :'expected_ip', true);
LOCK TABLE public.users IN ACCESS EXCLUSIVE MODE;
DO $cancel$
DECLARE
    deadline timestamptz := clock_timestamp() + interval '6 seconds';
    matches integer;
    candidate_pid integer;
    candidate_query text;
    candidate_start timestamptz;
    first_pid integer;
    first_start timestamptz;
    signal_sent boolean;
    expected_query constant text := 'select public.users.id, public.users.public_id, public.users.cognito_sub, public.users.email, public.users.display_name, public.users.status, public.users.timezone, public.users.created_at, public.users.updated_at from public.users where public.users.cognito_sub = $1';
BEGIN
    LOOP
        -- A transaction otherwise retains the prior statistics snapshot.
        PERFORM pg_stat_clear_snapshot();
        SELECT count(*), min(a.pid), min(a.query), min(a.query_start)
          INTO matches, candidate_pid, candidate_query, candidate_start
          FROM pg_stat_activity a
         WHERE a.datname = current_database()
           AND a.usename = current_user
           AND a.client_addr = current_setting('slash_test.expected_ip')::inet
           AND a.application_name = 'PostgreSQL JDBC Driver'
           AND a.backend_type = 'client backend'
           AND a.state = 'active'
           AND a.wait_event_type = 'Lock'
           AND pg_backend_pid() = ANY(pg_blocking_pids(a.pid));
        IF matches > 1 THEN
            RAISE EXCEPTION 'More than one app statement is blocked; cancel refused';
        END IF;
        IF matches = 1 THEN
            IF trim(regexp_replace(replace(candidate_query, '"', ''), '[[:space:]]+', ' ', 'g')) <> expected_query THEN
                RAISE EXCEPTION 'Blocked query differs from reviewed /me SELECT; cancel refused';
            END IF;
            IF first_pid = candidate_pid AND first_start = candidate_start THEN
                -- Recheck the same statement immediately before signalling.
                -- Our lock keeps it from completing normally in between samples.
                PERFORM pg_stat_clear_snapshot();
                SELECT pg_cancel_backend(a.pid) INTO signal_sent
                  FROM pg_stat_activity a
                 WHERE a.pid = candidate_pid AND a.query_start = candidate_start
                   AND a.datname = current_database() AND a.usename = current_user
                   AND a.client_addr = current_setting('slash_test.expected_ip')::inet
                   AND a.application_name = 'PostgreSQL JDBC Driver'
                   AND a.backend_type = 'client backend'
                   AND a.state = 'active' AND a.wait_event_type = 'Lock'
                   AND pg_backend_pid() = ANY(pg_blocking_pids(a.pid))
                   AND trim(regexp_replace(replace(a.query, '"', ''), '[[:space:]]+', ' ', 'g')) = expected_query;
                IF signal_sent IS DISTINCT FROM true THEN
                    RAISE EXCEPTION 'Statement changed or cancellation signal was not accepted';
                END IF;
                EXIT;
            END IF;
            -- A second sample catches simultaneous requests before any signal.
            first_pid := candidate_pid;
            first_start := candidate_start;
        ELSE
            first_pid := NULL;
            first_start := NULL;
        END IF;
        IF clock_timestamp() >= deadline THEN
            RAISE EXCEPTION 'No uniquely identified blocked app statement; cancel refused';
        END IF;
        PERFORM pg_sleep(0.5);
    END LOOP;
END
$cancel$;
ROLLBACK;
