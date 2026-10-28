import base64
import io
import json
import os
from pathlib import Path
import ssl
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import run

ORIGIN = run.Target('api.example.test', 443)
ISSUER = 'https://cognito-idp.ap-northeast-2.amazonaws.com/ap-northeast-2_example'
CLIENT = 'client-example'
BODY = json.dumps({'data': {'userId': '67d9086c-b119-4c3c-bcaf-d9fed74b0c17',
                           'email': 'synthetic@example.test', 'status': 'ACTIVE'}}).encode()


def token(**changes):
    claims = {'iss': ISSUER, 'client_id': CLIENT, 'token_use': 'access', 'exp': time.time() + 3600}
    claims.update(changes)
    encode = lambda x: base64.urlsafe_b64encode(json.dumps(x).encode()).rstrip(b'=').decode()
    return encode({'alg': 'RS256'}) + '.' + encode(claims) + '.test-signature'


def result(sequence, status=200, error=None, phase='trial'):
    return {'sequence': sequence, 'status': status, 'error': error, 'phase': phase, 'elapsed_ms': 3000}


class Inputs(unittest.TestCase):
    def test_origin_is_https_only_and_no_credentials_or_redirect_path(self):
        self.assertEqual(run.parse_origin('https://api.example.test/'), ORIGIN)
        for url in ['http://api.example.test', 'https://user:password@api.example.test',
                    'https://api.example.test/anything', 'https://api.example.test?token=secret',
                    'https://api.example.test/#frag', 'https://api.example.test:bad', 'https://api.example.test:0',
                    'https://api.example.test\\@elsewhere', 'https://api.example.test\n']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                run.parse_origin(url)

    def test_only_seoul_execute_api_allows_one_stage_segment(self):
        host = 'abc123def4.execute-api.ap-northeast-2.amazonaws.com'
        for suffix in ['/m2', '/m2/']:
            target = run.parse_origin('https://' + host + suffix)
            self.assertEqual(target, run.Target(host, 443, '/m2/api/v1/me'))
        for url in ['https://' + host + '/a/b', 'https://' + host + '/..',
                    'https://' + host + '/%2F', 'https://' + host + ':8443/m2',
                    'https://' + host + '.evil.test/m2',
                    'https://abc123def4.execute-api.us-east-1.amazonaws.com/m2']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                run.parse_origin(url)

    def test_access_token_claims_and_lifetime_are_checked(self):
        run.check_token(token(), ISSUER, CLIENT, 220)
        for changes in [{'token_use': 'id'}, {'iss': 'different'}, {'client_id': 'different'},
                        {'exp': time.time() + 100}, {'exp': True}, {'exp': float('nan')},
                        {'nbf': time.time() + 3600}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                run.check_token(token(**changes), ISSUER, CLIENT, 220)
        with self.assertRaises(ValueError):
            run.check_token('malformed', ISSUER, CLIENT, 220)
        with self.assertRaises(ValueError):
            run.check_token(token().rsplit('.', 1)[0] + '.non-ascii-한글', ISSUER, CLIENT, 220)

    def test_private_token_file_and_source_ambiguity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'token'
            path.write_text('synthetic-token')
            path.chmod(0o600)
            self.assertEqual(run.read_token(path, {}), 'synthetic-token')
            with self.assertRaises(ValueError):
                run.read_token(path, {'API_ACCESS_TOKEN': 'another'})
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                run.read_token(path, {})
            link = Path(directory) / 'link'
            link.symlink_to(path)
            with self.assertRaises(OSError):
                run.read_token(link, {})

    def test_response_shape_has_no_false_positive_for_error_or_wrong_type(self):
        self.assertTrue(run.valid_me(BODY))
        for body in [b'{}', b'{"data":null}', b'{"data":{"userId":123}}', b'not-json',
                     BODY.replace(b'ACTIVE', b'DELETED')]:
            self.assertFalse(run.valid_me(body))


class Http(unittest.TestCase):
    def connection(self, status=200, body=BODY):
        conn = Mock()
        conn.getresponse.return_value.status = status
        conn.getresponse.return_value.read.return_value = body
        return conn

    def test_slow_200_is_observation_not_failure_and_contains_no_identity(self):
        conn = self.connection()
        with patch('run.http.client.HTTPSConnection', return_value=conn) as constructor, \
                patch('run.time.monotonic', side_effect=[0, 3]):
            record = run.request_once(ORIGIN, 'secret-token', 8, 1)
        self.assertEqual(record['elapsed_ms'], 3000)
        self.assertIsNone(record['error'])
        self.assertNotIn('secret-token', json.dumps(record))
        self.assertNotIn('synthetic@example.test', json.dumps(record))
        conn.request.assert_called_once()
        args, kwargs = conn.request.call_args
        self.assertEqual(args, ('GET', '/api/v1/me'))
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer secret-token')
        context = constructor.call_args.kwargs['context']
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_gateway_stage_keeps_fixed_me_suffix(self):
        conn = self.connection()
        target = run.parse_origin('https://abc123def4.execute-api.ap-northeast-2.amazonaws.com/m2')
        with patch('run.http.client.HTTPSConnection', return_value=conn) as constructor:
            record = run.request_once(target, 'secret-token', 8, 1)
        self.assertIsNone(record['error'])
        self.assertEqual(conn.request.call_args.args, ('GET', '/m2/api/v1/me'))
        self.assertEqual(constructor.call_args.args, (target.host, 443))

    def test_redirect_is_recorded_without_following_or_reading_body(self):
        conn = self.connection(302, b'secret redirect body')
        with patch('run.http.client.HTTPSConnection', return_value=conn):
            record = run.request_once(ORIGIN, 'secret-token', 8, 1)
        self.assertEqual(record['status'], 302)
        self.assertEqual(record['error'], 'http_status')
        conn.request.assert_called_once()
        conn.getresponse.return_value.read.assert_not_called()

    def test_network_exceptions_never_echo_untrusted_messages(self):
        for exc, code in [(ssl.SSLError('secret-token'), 'tls_error'),
                          (TimeoutError('secret-token'), 'timeout'),
                          (OSError('secret-token'), 'connection_error')]:
            conn = self.connection()
            conn.connect.side_effect = exc
            with patch('run.http.client.HTTPSConnection', return_value=conn):
                record = run.request_once(ORIGIN, 'secret-token', 8, 1)
            self.assertEqual(record['error'], code)
            self.assertNotIn('secret-token', json.dumps(record))

    def test_body_limit_and_shape_are_enforced(self):
        for body, expected in [(b'x' * (run.MAX_BODY_BYTES + 1), 'response_too_large'),
                               (b'{}', 'invalid_response_shape')]:
            with patch('run.http.client.HTTPSConnection', return_value=self.connection(body=body)):
                record = run.request_once(ORIGIN, 'secret-token', 8, 1)
            self.assertEqual(record['error'], expected)


class Schedule(unittest.TestCase):
    def test_failed_preflight_never_starts_trial(self):
        records = []
        request = Mock(return_value=result(0, 401, 'http_status', 'preflight'))
        summary = run.observe(ORIGIN, 'token', .1, .01, 1, records.append, request)
        self.assertEqual(summary['outcome'], 'preflight_failed')
        request.assert_called_once()

    def test_auth_failure_stops_new_requests(self):
        records = []
        def request(origin, token, timeout, sequence, phase='trial'):
            return result(sequence, 200 if phase == 'preflight' else 403,
                          None if phase == 'preflight' else 'http_status', phase)
        summary = run.observe(ORIGIN, 'token', .2, .01, 1, records.append, request)
        self.assertEqual(summary['outcome'], 'auth_failed')
        self.assertEqual(summary['sent'], 1)

    def test_concurrency_and_scheduled_count_are_bounded_without_backlog(self):
        records = []
        mutex = threading.Lock()
        active = peak = 0
        def request(origin, token, timeout, sequence, phase='trial'):
            nonlocal active, peak
            if phase != 'preflight':
                with mutex:
                    active += 1
                    peak = max(peak, active)
                time.sleep(.08)
                with mutex:
                    active -= 1
            return result(sequence, phase=phase)
        summary = run.observe(ORIGIN, 'token', .1, .01, 1, records.append, request)
        self.assertLessEqual(peak, run.CONCURRENCY)
        self.assertEqual(summary['planned'], 10)
        self.assertEqual(summary['sent'] + summary['skipped'], 10)
        self.assertGreater(summary['skipped'], 0)
        self.assertEqual(summary['outcome'], 'request_errors')

    def test_cli_writes_private_sanitized_results_and_no_token(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'new-run'
            jwt = token()
            def observer(origin, token, seconds, interval, timeout, emit):
                emit(result(0, phase='preflight'))
                emit(result(1))
                return {'outcome': 'observed', 'sent': 1, 'failed': 0, 'skipped': 0}
            argv = ['run.py', '--base-url', 'https://api.example.test', '--issuer', ISSUER,
                    '--client-id', CLIENT, '--output', str(output)]
            with patch('sys.argv', argv), patch.dict(os.environ, {'API_ACCESS_TOKEN': jwt}), \
                    patch('run.observe', side_effect=observer), patch('sys.stdout', new_callable=io.StringIO) as stdout:
                self.assertEqual(run.main(), 0)
            for path in output.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertNotIn(jwt, path.read_text())
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            self.assertNotIn(jwt, stdout.getvalue())


if __name__ == '__main__':
    unittest.main()
