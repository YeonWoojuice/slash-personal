"""Offline tests: injected observations, no requests or AWS calls."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('slash_cancel_probe', Path(__file__).with_name('cancel_probe.py'))
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class CancelProbeTests(unittest.TestCase):
    def observe(self, responses, seconds=5):
        records = []
        now = [0]
        def request(*args, **kwargs):
            status, error = responses.pop(0)
            return {'status': status, 'error': error, 'phase': kwargs['phase']}
        def sleep(value): now[0] += value
        result = probe.observe_cancel_once(None, 'not-a-real-token', seconds, 8, records.append,
                                          request=request, clock=lambda: now[0], sleep=sleep)
        return result, records

    def test_exact_500_between_valid_preflight_and_postcheck_succeeds(self):
        result, records = self.observe([(200, None), (200, None), (500, 'http_status'), (200, None)])
        self.assertEqual(result['outcome'], 'observed_500_then_200')
        self.assertEqual(result['observed_500'], 1)
        self.assertEqual(records[-1]['phase'], 'postcheck')

    def test_missing_500_fails_at_bound(self):
        result, records = self.observe([(200, None)] * 6)
        self.assertEqual(result['outcome'], 'expected_500_not_observed')
        self.assertEqual(len(records), 6)

    def test_preflight_error_cannot_be_expected_fault(self):
        for response in [(500, 'http_status'), (401, 'http_status'), (200, 'invalid_response_shape')]:
            result, records = self.observe([response])
            self.assertEqual(result['outcome'], 'preflight_failed')
            self.assertEqual(len(records), 1)

    def test_transport_auth_other_server_errors_fail_immediately(self):
        for response in [(None, 'timeout'), (None, 'tls_error'), (401, 'http_status'),
                         (403, 'http_status'), (502, 'http_status'), (500, 'timeout')]:
            result, records = self.observe([(200, None), response])
            self.assertEqual(result['outcome'], 'unexpected_response')
            self.assertEqual(len(records), 2)

    def test_second_500_or_invalid_recovery_fails(self):
        for response in [(500, 'http_status'), (200, 'invalid_response_shape'), (None, 'connection_error')]:
            result, records = self.observe([(200, None), (500, 'http_status'), response])
            self.assertEqual(result['outcome'], 'postcheck_failed')
            self.assertEqual(len(records), 3)


if __name__ == '__main__':
    unittest.main()
