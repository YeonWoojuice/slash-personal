"""Local-only timing attribution and transport boundary tests; no AWS calls."""
from contextlib import contextmanager
import errno
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import run
import timing_transport as transport

APP_ID = '2d1cefa4-6444-46d2-a41d-4ea55c53044d'
GATEWAY_ID = 'e3f20ee9-a6f0-4241-9de4-ffb45aca6678'
EXTENDED_ID = 'ExampleGateway42='
BODY = json.dumps({'data': {'userId': '67d9086c-b119-4c3c-bcaf-d9fed74b0c17',
                           'email': 'synthetic@example.test', 'status': 'ACTIVE'}}).encode()


class Contract(unittest.TestCase):
    def test_unknown_fields_values_and_duplicate_ids_are_not_copied(self):
        unsafe = {'client_probe_id': 'secret', 'timing_ms': {'dns': float('nan'),
                  'tcp_connect': True, 'tls_handshake': -1, 'authorization': 'secret'},
                  'correlation': {'app_request_id': APP_ID + ', ' + APP_ID,
                                  'gateway_request_id': GATEWAY_ID.upper(),
                                  'gateway_extended_request_id': 'eyJsecret.secret.secret',
                                  'token': 'secret'},
                  'phase_at_failure': 'secret', 'failed_phase_elapsed_ms': 3,
                  'headers': {'Authorization': 'secret'}}
        clean = transport.sanitize_measurement(unsafe)
        self.assertNotIn('secret', json.dumps(clean))
        self.assertEqual(set(clean['timing_ms']), set(transport.PHASES))
        self.assertTrue(all(x is None for x in clean['timing_ms'].values()))
        self.assertTrue(all(x is None for x in clean['correlation'].values()))
        self.assertIsNone(clean['client_probe_id'])
        self.assertIsNone(clean['phase_at_failure'])
        self.assertIsNone(clean['failed_phase_elapsed_ms'])

    def test_validated_fields_and_legacy_missing_measurements(self):
        clean = transport.sanitize_measurement({'client_probe_id': APP_ID,
                'timing_ms': {'dns': 1.23456, 'tcp_connect': 0},
                'phase_at_failure': 'tls_handshake', 'failed_phase_elapsed_ms': 80.12345,
                'correlation': {'app_request_id': APP_ID, 'gateway_request_id': GATEWAY_ID,
                                'gateway_extended_request_id': EXTENDED_ID}})
        self.assertEqual(clean['timing_ms']['dns'], 1.235)
        self.assertEqual(clean['timing_ms']['tcp_connect'], 0)
        self.assertIsNone(clean['timing_ms']['tls_handshake'])
        self.assertEqual(clean['failed_phase_elapsed_ms'], 80.123)
        self.assertEqual(clean['correlation']['gateway_extended_request_id'], EXTENDED_ID)
        for raw in ({'elapsed_ms': 2054.693}, None, [], 'secret'):
            legacy = transport.sanitize_measurement(raw)
            self.assertTrue(all(value is None for value in legacy['timing_ms'].values()))
            self.assertIsNone(legacy['client_probe_id'])

    def test_getheader_duplicates_and_injection_are_rejected(self):
        response = Mock()
        response.getheader.side_effect = [APP_ID + ', ' + APP_ID, 'value\r\nsecret', GATEWAY_ID]
        ids = transport.response_correlation(response)
        self.assertEqual(ids, {'app_request_id': None, 'gateway_extended_request_id': None,
                              'gateway_request_id': GATEWAY_ID})

    def test_oversized_integer_durations_are_missing_not_crashes(self):
        result = transport.sanitize_measurement({'timing_ms': {'dns': 10 ** 999},
                     'phase_at_failure': 'tcp_connect', 'failed_phase_elapsed_ms': 10 ** 999})
        self.assertIsNone(result['timing_ms']['dns'])
        self.assertIsNone(result['failed_phase_elapsed_ms'])

    def test_failure_duration_does_not_claim_completed_phase(self):
        ticks = iter([0, .02, .03, .10])
        timer = transport.PhaseTimings(clock=lambda: next(ticks))
        with timer.measure('dns'):
            pass
        with self.assertRaises(TimeoutError), timer.measure('tcp_connect'):
            raise TimeoutError('never logged')
        self.assertEqual(timer.values['dns'], 20)
        self.assertIsNone(timer.values['tcp_connect'])
        self.assertEqual(timer.failed_phase, 'tcp_connect')
        self.assertEqual(timer.failed_elapsed_ms, 70)


class DnsDeadline(unittest.TestCase):
    def test_dns_timeout_returns_without_socket_or_secret_and_bounds_workers(self):
        release = threading.Event()
        entered = threading.Event()
        completed = threading.Event()
        calls = []
        slots = threading.BoundedSemaphore(1)

        def stuck_resolver(*args):
            calls.append(args)
            entered.set()
            try:
                release.wait(2)
                return []
            finally:
                completed.set()

        context = ssl.create_default_context()
        try:
            with patch('timing_transport._DNS_SLOTS', slots), \
                    patch('timing_transport.socket.getaddrinfo', side_effect=stuck_resolver), \
                    patch('timing_transport.socket.socket') as sockets:
                before = time.monotonic()
                first = run.request_once(run.Target('blocked.example.test', 443), 'secret-token', .08, 1, context=context)
                second = run.request_once(run.Target('blocked.example.test', 443), 'secret-token', .08, 2, context=context)
                elapsed = time.monotonic() - before
                self.assertTrue(entered.is_set())
                self.assertEqual(len(calls), 1)
                sockets.assert_not_called()
                self.assertLess(elapsed, .8)
                for result in (first, second):
                    self.assertEqual(result['error'], 'timeout')
                    self.assertEqual(result['phase_at_failure'], 'dns')
                    self.assertIsNone(result['timing_ms']['dns'])
                    self.assertIsNone(result['timing_ms']['tcp_connect'])
                    self.assertGreater(result['failed_phase_elapsed_ms'], 40)
                    self.assertNotIn('secret', json.dumps(result))
        finally:
            release.set()
            self.assertTrue(completed.wait(1))

    def test_resolver_exception_is_sanitized_and_phase_preserved(self):
        with patch('timing_transport.socket.getaddrinfo', side_effect=socket.gaierror('secret-token')):
            result = run.request_once(run.Target('invalid.example.test', 443), 'secret-token', 1, 1)
        self.assertEqual(result['error'], 'connection_error')
        self.assertEqual(result['phase_at_failure'], 'dns')
        self.assertNotIn('secret-token', json.dumps(result))

    def test_setup_overrun_does_not_start_dns_or_http(self):
        context = ssl.create_default_context()
        def slow_context():
            time.sleep(.08)
            return context
        with patch('run.ssl.create_default_context', side_effect=slow_context), \
                patch('timing_transport.resolve') as resolver:
            result = run.request_once(run.Target('unused.example.test', 443), 'secret-token', .03, 1)
        resolver.assert_not_called()
        self.assertEqual(result['error'], 'timeout')
        self.assertEqual(result['phase_at_failure'], 'client_setup')
        self.assertIsNone(result['timing_ms']['client_setup'])
        self.assertGreaterEqual(result['failed_phase_elapsed_ms'], 70)


class TcpCompatibility(unittest.TestCase):
    def test_tcp_nodelay_is_retained_and_only_unsupported_option_is_ignored(self):
        address = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('127.0.0.1', 443))]
        for option_error in (None, OSError(errno.ENOPROTOOPT, 'unsupported'), OSError(errno.EPERM, 'denied')):
            raw = Mock()
            raw.setsockopt.side_effect = option_error
            context = Mock()
            timings = transport.PhaseTimings()
            deadline = Mock()
            deadline.remaining.return_value = 1
            conn = transport.TimedHTTPSConnection('example.test', 443, timeout=1,
                    context=context, deadline=deadline, timings=timings)
            with patch('timing_transport.resolve', return_value=address), \
                    patch('timing_transport.socket.socket', return_value=raw):
                if option_error is not None and option_error.errno != errno.ENOPROTOOPT:
                    with self.assertRaises(OSError):
                        conn.connect()
                    context.wrap_socket.assert_not_called()
                    self.assertEqual(timings.failed_phase, 'tcp_connect')
                else:
                    conn.connect()
                    context.wrap_socket.return_value.do_handshake.assert_called_once()
            raw.setsockopt.assert_called_once_with(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)


class LocalTls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='slash-timing-tls-')
        path = Path(cls.directory.name)
        (path / 'openssl.cnf').write_text('''[req]
prompt = no
distinguished_name = dn
x509_extensions = ext
[dn]
CN = 127.0.0.1
[ext]
subjectAltName = IP:127.0.0.1
basicConstraints = critical,CA:TRUE
keyUsage = critical,digitalSignature,keyEncipherment,keyCertSign
extendedKeyUsage = serverAuth
''')
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                        '-keyout', str(path / 'key.pem'), '-out', str(path / 'cert.pem'),
                        '-config', str(path / 'openssl.cnf')], check=True, capture_output=True)
        cls.server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.server_context.load_cert_chain(str(path / 'cert.pem'), str(path / 'key.pem'))
        cls.client_context = ssl.create_default_context(cafile=str(path / 'cert.pem'))

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    @contextmanager
    def server(self, header_delay=0, body_delay=0, status=200, extra_headers=None):
        received = []
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def do_GET(self):
                received.append({'path': self.path, 'probe': self.headers.get('X-Slash-Probe-Id')})
                time.sleep(header_delay)
                try:
                    self.send_response(status)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(BODY)))
                    self.send_header('Connection', 'close')
                    for name, value in (extra_headers or {}).items():
                        self.send_header(name, value)
                    self.end_headers()
                    self.wfile.flush()
                    time.sleep(body_delay)
                    self.wfile.write(BODY)
                except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
                    pass
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.socket = self.server_context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
        thread.start()
        try:
            yield run.Target('127.0.0.1', server.server_port), received
        finally:
            server.shutdown()
            server.server_close()
            thread.join(1)

    def test_real_tls_separates_dns_headers_and_body_waits(self):
        real_resolver = socket.getaddrinfo
        def delayed_resolver(*args, **kwargs):
            time.sleep(.08)
            return real_resolver(*args, **kwargs)
        headers = {'X-Slash-Request-Id': APP_ID, 'x-amz-apigw-id': EXTENDED_ID,
                   'x-amzn-requestid': GATEWAY_ID}
        with self.server(.10, .10, extra_headers=headers) as (origin, received), \
                patch('timing_transport.socket.getaddrinfo', side_effect=delayed_resolver):
            result = run.request_once(origin, 'secret-token', 2, 1, context=self.client_context)
        self.assertEqual(result['status'], 200)
        self.assertIsNone(result['error'])
        self.assertGreaterEqual(result['timing_ms']['dns'], 70)
        self.assertGreaterEqual(result['timing_ms']['response_headers_wait'], 80)
        self.assertGreaterEqual(result['timing_ms']['response_body'], 70)
        self.assertTrue(all(value is not None for value in result['timing_ms'].values()))
        self.assertLessEqual(sum(result['timing_ms'].values()), result['elapsed_ms'] + .02)
        self.assertEqual(received, [{'path': '/api/v1/me', 'probe': result['client_probe_id']}])
        self.assertEqual(result['correlation'], {'app_request_id': APP_ID,
                         'gateway_extended_request_id': EXTENDED_ID, 'gateway_request_id': GATEWAY_ID})
        self.assertNotIn('secret-token', json.dumps(result))
        self.assertNotIn('synthetic@example.test', json.dumps(result))
        self.assertIsNone(result['phase_at_failure'])

    def test_body_wait_uses_whole_request_deadline_not_a_new_budget(self):
        with self.server(.12, .20) as (origin, _):
            before = time.monotonic()
            result = run.request_once(origin, 'secret-token', .22, 1, context=self.client_context)
            elapsed = time.monotonic() - before
        self.assertEqual(result['error'], 'timeout')
        self.assertEqual(result['phase_at_failure'], 'response_body')
        self.assertIsNone(result['timing_ms']['response_body'])
        self.assertGreater(result['timing_ms']['response_headers_wait'], 100)
        self.assertLess(elapsed, .5)
        self.assertGreater(result['failed_phase_elapsed_ms'], 30)

    def test_slow_headers_are_reported_as_unfinished_header_phase(self):
        with self.server(.30) as (origin, _):
            result = run.request_once(origin, 'secret-token', .10, 1, context=self.client_context)
        self.assertEqual(result['error'], 'timeout')
        self.assertEqual(result['phase_at_failure'], 'response_headers_wait')
        self.assertIsNone(result['timing_ms']['response_headers_wait'])
        self.assertIsNone(result['timing_ms']['response_body'])

    def test_untrusted_certificate_is_rejected_before_http_request(self):
        with self.server() as (origin, received):
            result = run.request_once(origin, 'secret-token', 1, 1)
        self.assertEqual(result['error'], 'tls_error')
        self.assertEqual(result['phase_at_failure'], 'tls_handshake')
        self.assertIsNone(result['timing_ms']['tls_handshake'])
        self.assertEqual(received, [])

    def test_unverified_context_is_rejected_before_dns(self):
        with patch('timing_transport.resolve') as resolve:
            result = run.request_once(run.Target('unused.example.test', 443), 'secret-token', 1, 1,
                                      context=ssl._create_unverified_context())
        resolve.assert_not_called()
        self.assertEqual(result['error'], 'tls_error')
        self.assertEqual(result['phase_at_failure'], 'client_setup')

    def test_redirect_has_no_body_timing_and_no_second_http_request(self):
        with self.server(status=302, extra_headers={'Location': 'https://elsewhere.example.test/secret'}) as (origin, received):
            result = run.request_once(origin, 'secret-token', 1, 1, context=self.client_context)
        self.assertEqual(result['status'], 302)
        self.assertEqual(result['error'], 'http_status')
        self.assertIsNone(result['timing_ms']['response_body'])
        self.assertEqual(len(received), 1)
        self.assertNotIn('elsewhere', json.dumps(result))

    def test_tls_stall_is_bounded_before_any_http_request(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        release = threading.Event()
        def accept():
            conn, _ = listener.accept()
            with conn:
                release.wait(1)
        thread = threading.Thread(target=accept, daemon=True)
        thread.start()
        try:
            origin = run.Target('127.0.0.1', listener.getsockname()[1])
            result = run.request_once(origin, 'secret-token', .10, 1, context=self.client_context)
            self.assertEqual(result['error'], 'timeout')
            self.assertEqual(result['phase_at_failure'], 'tls_handshake')
            self.assertIsNotNone(result['timing_ms']['tcp_connect'])
            self.assertIsNone(result['timing_ms']['tls_handshake'])
            self.assertIsNone(result['timing_ms']['request_send'])
        finally:
            release.set()
            listener.close()
            thread.join(1)


if __name__ == '__main__':
    unittest.main()
