#!/usr/bin/env python3
"""Bounded /me observation during a disposable DB-delay test; never injects faults."""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import getpass
import http.client
import json
import math
import os
import re
from pathlib import Path
import socket
import ssl
import stat
import sys
import time
from urllib.parse import urlsplit
from typing import NamedTuple
import uuid

from timing_transport import (Deadline, PhaseTimings, TimedHTTPSConnection,
                              response_correlation, sanitize_measurement)

MAX_BODY_BYTES = 65536
CONCURRENCY = 4


class Target(NamedTuple):
    host: str
    port: int
    path: str = '/api/v1/me'


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def parse_origin(value):
    try:
        parsed = urlsplit(value)
        port = 443 if parsed.port is None else parsed.port
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None
                or parsed.query or parsed.fragment or not 1 <= port <= 65535
                or any(c.isspace() for c in value) or '\\' in value):
            raise ValueError
        prefix = ''
        if parsed.path not in ('', '/'):
            if (port != 443
                    or not re.fullmatch(r'[a-z0-9]+[.]execute-api[.]ap-northeast-2[.]amazonaws[.]com', parsed.hostname)
                    or not re.fullmatch(r'/[A-Za-z0-9_-]{1,128}/?', parsed.path)):
                raise ValueError
            prefix = parsed.path.rstrip('/')
        return Target(parsed.hostname, port, prefix + '/api/v1/me')
    except ValueError:
        raise ValueError('Use an HTTPS origin, or one stage on a Seoul execute-api hostname; no credentials, query or fragment.') from None


def read_token(token_file, environment):
    if token_file and environment.get('API_ACCESS_TOKEN'):
        raise ValueError('Choose token file or API_ACCESS_TOKEN, not both.')
    if token_file:
        fd = os.open(token_file, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > 16384):
                raise ValueError('Token file must be owner-only, owned by you, regular, and at most 16 KiB.')
            with os.fdopen(fd, 'r', encoding='utf-8') as stream:
                fd = None
                token = stream.read(16385).strip()
        finally:
            if fd is not None:
                os.close(fd)
    elif environment.get('API_ACCESS_TOKEN'):
        token = environment['API_ACCESS_TOKEN'].strip()
    elif sys.stdin.isatty():
        token = getpass.getpass('Cognito access token (hidden): ').strip()
    else:
        raise ValueError('Supply API_ACCESS_TOKEN or a private --token-file.')
    if not token or len(token) > 16384 or any(c.isspace() for c in token):
        raise ValueError('Invalid access token format.')
    return token


def check_token(token, issuer, client_id, required_seconds, now=None):
    """Sanity-check untrusted claims only. The API verifies signature and authority."""
    if not issuer or not client_id:
        raise ValueError('Set the intended COGNITO_ISSUER_URI and COGNITO_CLIENT_ID.')
    try:
        parts = token.split('.')
        if len(parts) != 3 or not all(re.fullmatch(r'[A-Za-z0-9_-]+', part) for part in parts):
            raise ValueError
        def decode(segment):
            return json.loads(base64.b64decode(segment + '=' * (-len(segment) % 4), altchars=b'-_', validate=True))
        header, claims = decode(parts[0]), decode(parts[1])
        if not isinstance(header, dict) or not isinstance(claims, dict):
            raise ValueError
        clock = time.time() if now is None else now
        exp = claims.get('exp')
        if isinstance(exp, bool) or not isinstance(exp, (int, float)) or not math.isfinite(exp):
            raise ValueError
        if (header.get('alg') != 'RS256' or claims.get('token_use') != 'access'
                or claims.get('iss') != issuer or claims.get('client_id') != client_id
                or exp <= clock + required_seconds):
            raise ValueError
        for key in ('nbf', 'iat'):
            if key in claims:
                value = claims[key]
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or value > clock + (30 if key == 'iat' else 0)):
                    raise ValueError
    except (ValueError, TypeError, UnicodeError):
        raise ValueError('Token claims do not match the intended Cognito access token or its remaining lifetime is too short.') from None


def valid_me(body):
    try:
        data = json.loads(body)['data']
        if not isinstance(data['userId'], str):
            return False
        uuid.UUID(data['userId'])
        return isinstance(data['email'], str) and bool(data['email']) and data['status'] == 'ACTIVE'
    except (ValueError, TypeError, KeyError, UnicodeError):
        return False


def request_once(origin, token, timeout, sequence, phase='trial', context=None):
    record = {'sequence': sequence, 'phase': phase, 'started_at': utc_now(),
              'status': None, 'elapsed_ms': None, 'error': None,
              'client_probe_id': str(uuid.uuid4()), 'correlation': {}}
    start = time.monotonic()
    timings = PhaseTimings()
    deadline = Deadline(start, timeout)
    conn = response = None
    try:
        with timings.measure('client_setup'):
            tls_context = context or ssl.create_default_context()
            if tls_context.verify_mode != ssl.CERT_REQUIRED or not tls_context.check_hostname:
                raise ssl.SSLError('Verified TLS context required')
            conn = TimedHTTPSConnection(origin.host, origin.port, timeout=timeout,
                                       context=tls_context, deadline=deadline, timings=timings)
            deadline.remaining()
        conn.connect()
        with timings.measure('request_send'):
            deadline.set_socket_timeout(conn.sock)
            conn.request('GET', origin.path, headers={
                'Authorization': 'Bearer ' + token, 'Accept': 'application/json',
                'User-Agent': 'slash-m2-db-delay-observer/1', 'Connection': 'close',
                'X-Slash-Probe-Id': record['client_probe_id']})
            deadline.remaining()
        # This includes status-line/header reception, not pure first-byte time.
        with timings.measure('response_headers_wait'):
            deadline.set_socket_timeout(conn.sock)
            response = conn.getresponse()
            deadline.remaining()
        record['status'] = response.status
        record['correlation'] = response_correlation(response)
        if response.status != 200:
            record['error'] = 'http_status'
        else:
            with timings.measure('response_body'):
                # getresponse can detach a Connection: close socket from conn;
                # the deadline registry still holds its live transport.
                body = response.read(MAX_BODY_BYTES + 1)
                deadline.remaining()
            with timings.measure('validation'):
                if len(body) > MAX_BODY_BYTES:
                    record['error'] = 'response_too_large'
                elif not valid_me(body):
                    record['error'] = 'invalid_response_shape'
                deadline.remaining()
            if record['error']:
                timings.validation_failed()
    except (TimeoutError, socket.timeout):
        record['error'] = 'timeout'
    except ssl.SSLError:
        record['error'] = 'tls_error'
    except (OSError, http.client.HTTPException):
        record['error'] = 'connection_error'
    finally:
        deadline.finish()
        try:
            with timings.measure('cleanup'):
                cleanup_failed = False
                for resource in (response, conn):
                    if resource is not None:
                        try:
                            resource.close()
                        except Exception:
                            # Still close the other resource, and never lose
                            # the earlier result or echo a cleanup exception.
                            cleanup_failed = True
                if cleanup_failed:
                    raise OSError('Cleanup failed')
        except OSError:
            if record['error'] is None:
                record['error'] = 'connection_error'
        if deadline.expired.is_set():
            record['error'] = 'timeout'
        record['elapsed_ms'] = round((time.monotonic() - start) * 1000, 3)
        record['finished_at'] = utc_now()
        record.update(sanitize_measurement({**record, 'timing_ms': timings.values,
                                           'phase_at_failure': timings.failed_phase,
                                           'failed_phase_elapsed_ms': timings.failed_elapsed_ms}))
    return record


def observe(origin, token, seconds, interval, timeout, emit, request=request_once):
    preflight = request(origin, token, timeout, 0, phase='preflight')
    emit(preflight)
    if preflight['status'] != 200 or preflight['error']:
        return {'outcome': 'preflight_failed', 'sent': 0, 'failed': 0, 'skipped': 0}
    planned = math.ceil(seconds / interval)
    start = time.monotonic()
    submitted = failures = skipped = 0
    auth_failed = False
    pending = set()
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        for sequence in range(1, planned + 1):
            due = start + (sequence - 1) * interval
            while True:
                done, pending = wait(pending, timeout=min(.1, max(0, due - time.monotonic())),
                                     return_when=FIRST_COMPLETED) if pending else (set(), set())
                for future in done:
                    record = future.result()
                    emit(record)
                    failures += bool(record['error'])
                    auth_failed |= record['status'] in (401, 403)
                if auth_failed or time.monotonic() >= due:
                    break
                if not pending:
                    time.sleep(max(0, min(.1, due - time.monotonic())))
            if auth_failed:
                break
            if len(pending) >= CONCURRENCY or time.monotonic() >= start + seconds:
                skipped += 1
                emit({'sequence': sequence, 'phase': 'trial', 'started_at': utc_now(),
                      'status': None, 'elapsed_ms': None, 'error': 'capacity_skipped'})
                continue
            pending.add(pool.submit(request, origin, token, timeout, sequence))
            submitted += 1
        for future in pending:
            record = future.result()
            emit(record)
            failures += bool(record['error'])
            auth_failed |= record['status'] in (401, 403)
    return {'outcome': 'auth_failed' if auth_failed else ('request_errors' if failures or skipped else 'observed'),
            'planned': planned, 'sent': submitted, 'failed': failures, 'skipped': skipped}


def bounded_int(low, high):
    def parse(value):
        try:
            parsed = int(value)
            if not low <= parsed <= high:
                raise ValueError
            return parsed
        except ValueError:
            raise argparse.ArgumentTypeError(f'Use an integer from {low} to {high}.') from None
    return parse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default=os.getenv('API_BASE_URL', ''))
    parser.add_argument('--issuer', default=os.getenv('COGNITO_ISSUER_URI', ''))
    parser.add_argument('--client-id', default=os.getenv('COGNITO_CLIENT_ID', ''))
    parser.add_argument('--token-file', type=Path)
    parser.add_argument('--seconds', type=bounded_int(1, 300), default=180)
    parser.add_argument('--interval', type=bounded_int(1, 5), default=1)
    parser.add_argument('--timeout', type=bounded_int(1, 10), default=8)
    parser.add_argument('--output', type=Path, required=True, help='New private output directory; must not exist.')
    args = parser.parse_args()
    try:
        origin = parse_origin(args.base_url)
        token = read_token(args.token_file, os.environ)
        check_token(token, args.issuer, args.client_id, args.seconds + args.timeout * 2 + 30)
        args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
        events = args.output / 'requests.jsonl'
        fd = os.open(events, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            def emit(record):
                stream.write(json.dumps(record) + '\n')
                stream.flush()
            summary = observe(origin, token, args.seconds, args.interval, args.timeout, emit)
        summary.update({'finished_at': utc_now(), 'seconds': args.seconds, 'interval_seconds': args.interval,
                        'timeout_seconds': args.timeout, 'max_concurrency': CONCURRENCY,
                        'scope': 'HTTP observation only; not evidence of CloudWatch Alarm or M3 completion'})
        fd = os.open(args.output / 'summary.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(summary, stream, indent=2)
        print(json.dumps(summary))
        return 0 if summary['outcome'] == 'observed' else 1
    except KeyboardInterrupt:
        print('Stopped by operator; completed request records remain in the output directory.', file=sys.stderr)
        return 130
    except (ValueError, OSError):
        # Never format arbitrary exceptions: token, response or URL may be embedded.
        print('Input or output validation failed. Check HTTPS API address, Cognito settings, token lifetime/file permissions, and a new output directory.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
