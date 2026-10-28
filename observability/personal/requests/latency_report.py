#!/usr/bin/env python3
"""Join sanitized local client timings with optional application completion logs.

Reads files only. Never sends requests, reads AWS, or infers a cause from a gap.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sys

import run as observer

UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
GATEWAY_ID = re.compile(r'[A-Za-z0-9+/_-]{8,126}={0,2}')
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_LINE_BYTES = 65536
EVENT = 'personal_request_timing'


def number(value):
    try:
        return value if (not isinstance(value, bool) and isinstance(value, (int, float))
                         and math.isfinite(value) and value >= 0) else None
    except OverflowError:
        return None


def timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc).isoformat() if parsed.tzinfo else None
    except (ValueError, OverflowError):
        return None


def identifier(value, pattern=UUID):
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def status(value):
    return value if type(value) is int and 100 <= value <= 599 else None


def app_record(raw):
    """Accept a JSON event, CloudWatch JSONL message, or a Spring prefix + JSON."""
    if isinstance(raw, dict) and isinstance(raw.get('message'), str):
        raw = raw['message']
    if isinstance(raw, str):
        # No arbitrary log/exception text is returned, even when parsing fails.
        start = raw.find('{"event":"' + EVENT + '"')
        if start < 0:
            return None
        try:
            raw = json.loads(raw[start:])
        except (ValueError, TypeError):
            return None
    if not isinstance(raw, dict) or raw.get('event') != EVENT or raw.get('route') != '/api/v1/me':
        return None
    app_id, duration = identifier(raw.get('appRequestId')), number(raw.get('durationMs'))
    recorded_at = timestamp(raw.get('timestamp'))
    if app_id is None or duration is None or recorded_at is None:
        return None
    return {'app_request_id': app_id, 'client_probe_id': identifier(raw.get('clientProbeId')),
            'gateway_extended_request_id': identifier(raw.get('gatewayRequestId'), GATEWAY_ID),
            'status': status(raw.get('status')), 'duration_ms': duration, 'timestamp': recorded_at}


def read_lines(path, *, app_logs=False):
    with path.open('rb') as source:
        if os.fstat(source.fileno()).st_size > MAX_FILE_BYTES:
            raise ValueError('Input too large')
        for line in source:
            if len(line) > MAX_LINE_BYTES:
                raise ValueError('Line too large')
            try:
                text = line.decode('utf-8')
                raw = json.loads(text)
            except (ValueError, UnicodeError):
                if not app_logs:
                    raise ValueError('Invalid request JSONL') from None
                # Spring's existing console pattern wraps the JSON message.
                raw = line.decode('utf-8', errors='replace')
            if app_logs:
                parsed = app_record(raw)
                if parsed is not None:
                    yield parsed
            elif isinstance(raw, dict):
                yield raw


def matching_keys(client):
    correlation = client['correlation']
    keys = {'client_probe_id': client['client_probe_id'],
            'app_request_id': correlation.get('app_request_id'),
            'gateway_extended_request_id': correlation.get('gateway_extended_request_id')}
    return {k: v for k, v in keys.items() if v is not None}


def match_app(client, apps, lookup, client_key_counts):
    keys = matching_keys(client)
    hit_indexes = set()
    for key, value in keys.items():
        hit_indexes.update(lookup.get((key, value), ()))
    hits = [apps[index] for index in sorted(hit_indexes)]
    if not hits:
        return {'state': 'not_found', 'matched_on': [], 'record': None}
    compatible = [app for app in hits if all(app.get(k) in (None, v) for k, v in keys.items())]
    if len(compatible) != 1 or len(hits) != 1:
        return {'state': 'ambiguous_or_conflicting', 'matched_on': [], 'record': None}
    app = compatible[0]
    matched_keys = [k for k, v in keys.items() if app.get(k) == v]
    if not any(client_key_counts[(key, keys[key])] == 1 for key in matched_keys):
        return {'state': 'ambiguous_or_conflicting', 'matched_on': [], 'record': None}
    return {'state': 'matched', 'matched_on': matched_keys,
            'record': app}


def summarize(requests, apps=(), *, top=10):
    # Identical exported events are one observation; different events remain ambiguous.
    apps = list({json.dumps(app, sort_keys=True): app for app in apps}.values())
    lookup = {}
    for index, app in enumerate(apps):
        for key in ('client_probe_id', 'app_request_id', 'gateway_extended_request_id'):
            if app.get(key) is not None:
                lookup.setdefault((key, app[key]), set()).add(index)
    rows = []
    for raw in requests:
        elapsed = number(raw.get('elapsed_ms'))
        sequence = raw.get('sequence')
        if elapsed is None or type(sequence) is not int or sequence < 0:
            continue  # Control/cooldown records are not HTTP observations.
        measurement = observer.sanitize_measurement(raw)
        # The sanitizer returns only this fixed contract, never input extras.
        row = {'sequence': sequence, 'status': status(raw.get('status')),
               'elapsed_ms': elapsed, **measurement}
        completed = {k: v for k, v in row['timing_ms'].items() if number(v) is not None}
        row['largest_completed_client_phase'] = max(completed, key=completed.get) if completed else None
        rows.append(row)
    key_counts = Counter(pair for row in rows for pair in matching_keys(row).items())
    for row in rows:
        row['application'] = match_app(row, apps, lookup, key_counts)
    rows.sort(key=lambda row: row['elapsed_ms'], reverse=True)
    return {
        'scope': 'Offline timing comparison only; no requests, AWS calls or causal conclusion',
        'request_count': len(rows),
        'requests_with_timings': sum(row['largest_completed_client_phase'] is not None for row in rows),
        'legacy_requests_without_timings': sum(row['largest_completed_client_phase'] is None for row in rows),
        'valid_application_events': len(apps),
        'matched_application_requests': sum(row['application']['state'] == 'matched' for row in rows),
        'ambiguous_or_conflicting_requests': sum(row['application']['state'] == 'ambiguous_or_conflicting' for row in rows),
        'slowest_requests': rows[:top],
        'limitations': [
            'Historical total-only records cannot be retroactively split into phases.',
            'response_headers_wait ends after status line and headers; it is not exact time to first byte or app-only time.',
            'Application duration overlaps client phases; do not add it or label a subtraction as network latency.',
            'The largest measured phase narrows the investigation; it does not prove a root cause.',
            'Missing application events do not prove the app was never reached. Export the full time window.',
            'API Gateway internal/integration per-request durations are not enabled by this implementation.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requests', type=Path, required=True)
    parser.add_argument('--app-logs', type=Path)
    parser.add_argument('--output', type=Path, required=True, help='New private output file; must not exist.')
    parser.add_argument('--top', type=observer.bounded_int(1, 50), default=10)
    args = parser.parse_args()
    try:
        report = summarize(list(read_lines(args.requests)),
                           list(read_lines(args.app_logs, app_logs=True)) if args.app_logs else [], top=args.top)
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps({key: value for key, value in report.items()
                          if key not in ('slowest_requests', 'limitations')}))
        return 0
    except (OSError, ValueError, TypeError, KeyError):
        print('Could not read bounded input records or create a new private report file.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
