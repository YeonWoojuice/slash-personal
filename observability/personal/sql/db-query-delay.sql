-- Disposable Slash PostgreSQL only; never the LambdaOps DSQL or production DB.
-- Run via a reviewed one-off task in the experiment VPC, alongside authenticated
-- GET /api/v1/me traffic. This SQL alone is not an application metric sample.
-- One pulse only. No schema/data mutation; transaction end releases the lock.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL application_name = 'slash-m2-db-delay';
SET LOCAL lock_timeout = '1s';
SET LOCAL statement_timeout = '5s';
SET LOCAL idle_in_transaction_session_timeout = '5s';
LOCK TABLE public.users IN ACCESS EXCLUSIVE MODE;
SELECT pg_sleep(3);
ROLLBACK;
