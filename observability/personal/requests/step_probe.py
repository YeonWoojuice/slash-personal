#!/usr/bin/env python3
"""Fixed, bounded normal /me rate steps; no fault injection or capacity claim."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import argparse
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time

import run as observer

STAGES = ((0.5, 120), (1, 120), (2, 120), (5, 120))
CONCURRENCY = 4
TIMEOUT_SECONDS = 3
MAX_ELAPSED_MS = 2000
COOLDOWN_SECONDS = 120
MAX_SCHEDULE_DRIFT_SECONDS = TIMEOUT_SECONDS
SCHEDULE_LIMIT_SECONDS = sum(seconds for _, seconds in STAGES) + MAX_SCHEDULE_DRIFT_SECONDS
POLL_SECONDS = 0.02
REQUIRED_TOKEN_SECONDS = SCHEDULE_LIMIT_SECONDS + COOLDOWN_SECONDS + 3 * TIMEOUT_SECONDS + 30
ERROR_CODES = {'http_status', 'timeout', 'tls_error', 'connection_error',
               'response_too_large', 'invalid_response_shape', 'request_exception', 'invalid_result'}


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.isoformat() if parsed.tzinfo else None
    except ValueError:
        return None


def _record(raw, sequence, phase, stage=None):
    """Copy only validated observation fields, never response bodies or exceptions."""
    if not isinstance(raw, dict):
        raw = {}
    status, elapsed, error = raw.get('status'), raw.get('elapsed_ms'), raw.get('error')
    if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
        status = None
    if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0:
        elapsed, error = None, 'invalid_result'
    elif error is not None and (not isinstance(error, str) or error not in ERROR_CODES):
        error = 'invalid_result'
    return {'sequence': sequence, 'phase': phase, 'stage': stage,
            'started_at': _timestamp(raw.get('started_at')),
            'finished_at': _timestamp(raw.get('finished_at')),
            'observed_at': observer.utc_now(), 'status': status,
            'elapsed_ms': elapsed, 'error': error}


def _problem(record):
    if record['error']:
        return record['error']
    if record['status'] != 200:
        return 'http_status'
    if record['elapsed_ms'] > MAX_ELAPSED_MS:
        return 'latency_limit'
    return None


def run_probe(origin, token, emit, *, request=observer.request_once,
              clock=time.monotonic, sleep=time.sleep, executor_factory=ThreadPoolExecutor):
    """Accept a token in memory; every request uses the parsed fixed /me path.

    Request, clock and executor injection support offline tests. Production
    schedule, concurrency, timeout and stop limits are fixed constants.
    """
    rows = [{'stage': i + 1, 'rps': rate, 'seconds': seconds,
             'planned': int(rate * seconds), 'sent': 0, 'completed': 0,
             'failed': 0, 'skipped': 0, 'latencies': [],
             'first_dispatch_offset_seconds': None, 'last_dispatch_offset_seconds': None}
            for i, (rate, seconds) in enumerate(STAGES)]
    summary = {'scope': 'Bounded normal observation only; not a capacity, Alarm or M3 completion test',
               'started_at': observer.utc_now(), 'planned_step_requests': sum(x['planned'] for x in rows),
               'max_concurrency': CONCURRENCY, 'timeout_seconds': TIMEOUT_SECONDS,
               'latency_stop_ms': MAX_ELAPSED_MS, 'stages': rows,
               'schedule_limit_seconds': SCHEDULE_LIMIT_SECONDS,
               'max_schedule_drift_seconds': MAX_SCHEDULE_DRIFT_SECONDS,
               'schedule_elapsed_seconds': None, 'active_elapsed_seconds': None,
               'postflight_dispatch_offset_seconds': None,
               'stop_reason': None, 'preflight_passed': False, 'postflight_passed': False,
               'cooldown_seconds': COOLDOWN_SECONDS, 'cooldown_completed': False}
    def call(sequence, phase, stage=None):
        try:
            raw = request(origin, token, TIMEOUT_SECONDS, sequence, phase=phase)
        except Exception:
            raw = {'error': 'request_exception', 'elapsed_ms': 0}
        return _record(raw, sequence, phase, stage)
    def note(record):
        emit(record)
        problem = _problem(record)
        if record['stage'] is not None:
            row = rows[record['stage'] - 1]
            row['completed'] += 1
            row['failed'] += bool(problem)
            if record['elapsed_ms'] is not None:
                row['latencies'].append(record['elapsed_ms'])
        if problem and summary['stop_reason'] is None:
            summary['stop_reason'] = problem
        return problem
    preflight = call(0, 'preflight')
    summary['preflight_passed'] = note(preflight) is None
    if summary['preflight_passed']:
        pending = {}
        base = clock()
        sequence, stage_offset = 0, 0
        last_dispatch = None
        hard_deadline = base + SCHEDULE_LIMIT_SECONDS
        def consume():
            for future in list(pending):
                if future.done():
                    pending.pop(future)
                    note(future.result())
            if summary['stop_reason'] is None and any(clock() - launched > MAX_ELAPSED_MS / 1000 for launched in pending.values()):
                summary['stop_reason'] = 'inflight_latency_limit'
                emit({'phase': 'control', 'observed_at': observer.utc_now(), 'error': 'inflight_latency_limit'})
        with executor_factory(max_workers=CONCURRENCY) as pool:
            for row in rows:
                interval = 1 / row['rps']
                for index in range(row['planned']):
                    due = base + stage_offset + index * interval
                    # Preserve the minimum dispatch interval even after a small OS pause.
                    dispatch_at = max(due, last_dispatch + interval if last_dispatch is not None else due)
                    while clock() < dispatch_at and summary['stop_reason'] is None:
                        consume()
                        if summary['stop_reason'] is None:
                            sleep(min(POLL_SECONDS, max(0, dispatch_at - clock())))
                    consume()
                    if summary['stop_reason'] is not None:
                        break
                    reason = ('schedule_time_limit' if clock() >= hard_deadline else
                              'capacity_skipped' if len(pending) >= CONCURRENCY else
                              'schedule_skipped' if clock() - due > MAX_SCHEDULE_DRIFT_SECONDS else None)
                    if reason:
                        row['skipped'] += 1
                        summary['stop_reason'] = reason
                        emit({'phase': 'control', 'stage': row['stage'], 'observed_at': observer.utc_now(), 'error': reason})
                        break
                    sequence += 1
                    last_dispatch = clock()
                    offset = round(last_dispatch - base, 6)
                    if row['first_dispatch_offset_seconds'] is None:
                        row['first_dispatch_offset_seconds'] = offset
                    row['last_dispatch_offset_seconds'] = offset
                    pending[pool.submit(call, sequence, 'step', row['stage'])] = last_dispatch
                    row['sent'] += 1
                if summary['stop_reason'] is not None:
                    break
                stage_offset += row['seconds']
            finish = max(base + sum(seconds for _, seconds in STAGES),
                         last_dispatch + 1 / STAGES[-1][0] if last_dispatch is not None else base)
            while clock() < finish and summary['stop_reason'] is None:
                consume()
                if clock() >= hard_deadline:
                    summary['stop_reason'] = 'schedule_time_limit'
                if summary['stop_reason'] is None:
                    sleep(min(POLL_SECONDS, max(0, finish - clock())))
            # A sleep may resume beyond finish and skip the loop-body deadline check.
            if clock() >= hard_deadline and summary['stop_reason'] is None:
                summary['stop_reason'] = 'schedule_time_limit'
            summary['schedule_elapsed_seconds'] = round(clock() - base, 6)
            for future in list(pending):
                note(future.result())
            pending.clear()
            summary['active_elapsed_seconds'] = round(clock() - base, 6)
        # Draining in-flight work can also cross the deadline. Do not issue another GET.
        if clock() >= hard_deadline and summary['stop_reason'] is None:
            summary['stop_reason'] = 'schedule_time_limit'
        if summary['stop_reason'] is None:
            summary['postflight_dispatch_offset_seconds'] = round(clock() - base, 6)
            summary['postflight_passed'] = note(call(sequence + 1, 'postflight')) is None
    # Passive window: no request, retry or token refresh during cooldown.
    token = None
    emit({'phase': 'cooldown_start', 'observed_at': observer.utc_now(), 'seconds': COOLDOWN_SECONDS})
    deadline = clock() + COOLDOWN_SECONDS
    while clock() < deadline:
        sleep(min(0.25, max(0, deadline - clock())))
    summary['cooldown_completed'] = True
    for row in rows:
        first, last = row['first_dispatch_offset_seconds'], row['last_dispatch_offset_seconds']
        row['dispatch_window_seconds'] = round(last - first + 1 / row['rps'], 6) if first is not None else None
        values = sorted(row.pop('latencies'))
        row['latency_ms'] = {'count': len(values), 'avg': round(statistics.mean(values), 3) if values else None,
                             'p95': values[math.ceil(len(values) * .95) - 1] if values else None,
                             'max': max(values) if values else None}
    summary['sent_step_requests'] = sum(x['sent'] for x in rows)
    summary['failed_step_requests'] = sum(x['failed'] for x in rows)
    summary['skipped_step_requests'] = sum(x['skipped'] for x in rows)
    complete = (summary['preflight_passed'] and summary['postflight_passed'] and
                summary['stop_reason'] is None and summary['sent_step_requests'] == summary['planned_step_requests'] and
                summary['failed_step_requests'] == summary['skipped_step_requests'] == 0)
    summary['outcome'] = 'observed' if complete else 'stopped'
    summary['finished_at'] = observer.utc_now()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default=os.getenv('API_BASE_URL', ''))
    parser.add_argument('--issuer', default=os.getenv('COGNITO_ISSUER_URI', ''))
    parser.add_argument('--client-id', default=os.getenv('COGNITO_CLIENT_ID', ''))
    parser.add_argument('--token-file', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        origin = observer.parse_origin(args.base_url)
        token = observer.read_token(args.token_file, os.environ)
        observer.check_token(token, args.issuer, args.client_id, REQUIRED_TOKEN_SECONDS)
        args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
        fd = os.open(args.output / 'requests.jsonl', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            def emit(record):
                stream.write(json.dumps(record) + '\n')
                stream.flush()
            summary = run_probe(origin, token, emit)
        token = None
        fd = os.open(args.output / 'summary.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(summary, stream, indent=2)
            stream.write('\n')
        print(json.dumps(summary))
        return 0 if summary['outcome'] == 'observed' else 1
    except KeyboardInterrupt:
        print('Stopped by operator; completed records remain. No new requests will be sent.', file=sys.stderr)
        return 130
    except (ValueError, OSError):
        print('Input/output validation failed. Check the approved HTTPS target, Cognito token lifetime and a new private output directory.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
