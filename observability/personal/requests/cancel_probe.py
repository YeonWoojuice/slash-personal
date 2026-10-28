#!/usr/bin/env python3
"""Explicit, serial observation of one HTTP 500 followed by a valid /me 200."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

SPEC = importlib.util.spec_from_file_location('slash_http_observer', Path(__file__).with_name('run.py'))
http = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(http)


def observe_cancel_once(origin, token, seconds, timeout, emit,
                        request=http.request_once, clock=time.monotonic, sleep=time.sleep):
    """Never treat timeouts, auth errors, arbitrary 5xx, or preflight 500 as success."""
    preflight = request(origin, token, timeout, 0, phase='preflight')
    emit(preflight)
    if preflight['status'] != 200 or preflight['error']:
        return {'outcome': 'preflight_failed', 'observed_500': 0}
    deadline = clock() + seconds
    sequence = 0
    while clock() < deadline and sequence < seconds:
        sequence += 1
        record = request(origin, token, timeout, sequence, phase='await_single_500')
        emit(record)
        if record['status'] == 500 and record['error'] == 'http_status':
            # The DB controller rolls its lock back after sending the signal.
            sleep(1)
            post = request(origin, token, timeout, sequence + 1, phase='postcheck')
            emit(post)
            okay = post['status'] == 200 and not post['error']
            return {'outcome': 'observed_500_then_200' if okay else 'postcheck_failed',
                    'observed_500': 1 + int(post['status'] == 500), 'sent': sequence + 2}
        if record['status'] != 200 or record['error']:
            return {'outcome': 'unexpected_response', 'observed_500': 0, 'sent': sequence + 1}
        sleep(min(1, max(0, deadline - clock())))
    return {'outcome': 'expected_500_not_observed', 'observed_500': 0, 'sent': sequence + 1}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default=os.getenv('API_BASE_URL', ''))
    parser.add_argument('--issuer', default=os.getenv('COGNITO_ISSUER_URI', ''))
    parser.add_argument('--client-id', default=os.getenv('COGNITO_CLIENT_ID', ''))
    parser.add_argument('--token-file', type=Path)
    parser.add_argument('--seconds', type=http.bounded_int(1, 60), default=30)
    parser.add_argument('--timeout', type=http.bounded_int(1, 10), default=8)
    parser.add_argument('--output', type=Path, required=True, help='New private output directory.')
    args = parser.parse_args()
    try:
        origin = http.parse_origin(args.base_url)
        token = http.read_token(args.token_file, os.environ)
        http.check_token(token, args.issuer, args.client_id, args.seconds + args.timeout * 3 + 30)
        args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
        fd = os.open(args.output / 'requests.jsonl', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            def emit(record):
                stream.write(json.dumps(record) + '\n'); stream.flush()
            summary = observe_cancel_once(origin, token, args.seconds, args.timeout, emit)
        summary.update({'finished_at': http.utc_now(), 'max_concurrency': 1,
                        'scope': 'HTTP status observation only. Match task cancel_signalled time separately; CloudWatch Alarm and M3 are unverified.'})
        fd = os.open(args.output / 'summary.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(summary, stream, indent=2)
        print(json.dumps(summary))
        return 0 if summary['outcome'] == 'observed_500_then_200' else 1
    except KeyboardInterrupt:
        print('HTTP observation stopped. The separate bounded DB task must be checked independently.', file=sys.stderr)
        return 130
    except (ValueError, OSError):
        print('Check the HTTPS target, intended Cognito token, and new private output directory.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
