import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import latency_report as report

PROBE = '67d9086c-b119-4c3c-bcaf-d9fed74b0c17'
APP = '79a279f5-ac7a-47d6-ad2b-c82e054ff210'
OTHER = 'afea7884-7159-4198-916e-8cc6c601e90c'
GATEWAY = 'AbcdEFgh123='
SECRET = 'do-not-copy-token-user-email-or-body'


def client(**changes):
    data = {'sequence': 699, 'elapsed_ms': 2054.693, 'status': 200,
            'client_probe_id': PROBE, 'timing_ms': {'response_headers_wait': 1990.0},
            'correlation': {'app_request_id': APP, 'gateway_extended_request_id': GATEWAY}}
    data.update(changes)
    return data


def app(**changes):
    data = {'event': 'personal_request_timing', 'route': '/api/v1/me',
            'timestamp': '2026-10-29T00:00:00Z',
            'appRequestId': APP, 'clientProbeId': PROBE, 'gatewayRequestId': GATEWAY,
            'status': 200, 'durationMs': 7.5, 'email': SECRET}
    data.update(changes)
    return data


class Report(unittest.TestCase):
    def test_matches_exact_ids_without_subtracting_different_measurement_spans(self):
        result = report.summarize([client(headers=SECRET, body=SECRET)], [report.app_record(app())])
        row = result['slowest_requests'][0]
        self.assertEqual(result['matched_application_requests'], 1)
        self.assertEqual(row['application']['record']['duration_ms'], 7.5)
        self.assertEqual(row['largest_completed_client_phase'], 'response_headers_wait')
        self.assertEqual(len(row['application']['matched_on']), 3)
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertNotIn('network_ms', row)

    def test_legacy_record_does_not_invent_phase_measurements(self):
        result = report.summarize([{'sequence': 699, 'elapsed_ms': 2054.693, 'status': 200}])
        self.assertEqual(result['legacy_requests_without_timings'], 1)
        self.assertEqual(result['requests_with_timings'], 0)
        row = result['slowest_requests'][0]
        self.assertIsNone(row['largest_completed_client_phase'])
        self.assertTrue(all(value is None for value in row['timing_ms'].values()))
        self.assertEqual(row['application']['state'], 'not_found')

    def test_timeout_without_response_id_can_match_unique_client_probe_id(self):
        result = report.summarize([client(correlation={}, status=None)], [report.app_record(app())])
        self.assertEqual(result['matched_application_requests'], 1)
        self.assertEqual(result['slowest_requests'][0]['application']['matched_on'], ['client_probe_id'])

    def test_conflicting_or_ambiguous_ids_never_choose_an_application_record(self):
        for records in [[app(clientProbeId=OTHER)], [app(), app(appRequestId=OTHER)]]:
            with self.subTest(records=records):
                result = report.summarize([client()], [report.app_record(a) for a in records])
                self.assertEqual(result['ambiguous_or_conflicting_requests'], 1)
                self.assertIsNone(result['slowest_requests'][0]['application']['record'])

    def test_identical_exported_event_is_deduplicated(self):
        event = report.app_record(app())
        result = report.summarize([client()], [event, dict(event)])
        self.assertEqual(result['matched_application_requests'], 1)
        self.assertEqual(result['valid_application_events'], 1)

    def test_reused_client_probe_id_without_an_independent_unique_id_is_ambiguous(self):
        result = report.summarize([client(sequence=1, correlation={}), client(sequence=2, correlation={})],
                                  [report.app_record(app())])
        self.assertEqual(result['matched_application_requests'], 0)
        self.assertEqual(result['ambiguous_or_conflicting_requests'], 2)

    def test_reused_probe_id_does_not_silently_filter_conflicting_events(self):
        result = report.summarize([client(sequence=1, correlation={'app_request_id': APP}),
                                   client(sequence=2, correlation={'app_request_id': OTHER})],
                                  [report.app_record(app(gatewayRequestId=None)),
                                   report.app_record(app(appRequestId=OTHER, gatewayRequestId=None))])
        # Shared probe ID makes the union ambiguous even though other IDs differ;
        # prefer a reviewable ambiguity to silently discarding conflicting hits.
        self.assertEqual(result['matched_application_requests'], 0)
        self.assertEqual(result['ambiguous_or_conflicting_requests'], 2)

    def test_events_at_different_times_are_not_collapsed_as_duplicate_exports(self):
        result = report.summarize([client()], [report.app_record(app()),
                                   report.app_record(app(timestamp='2026-10-29T00:00:01Z'))])
        self.assertEqual(result['valid_application_events'], 2)
        self.assertEqual(result['ambiguous_or_conflicting_requests'], 1)

    def test_enormous_numeric_input_is_rejected_without_exception_or_raw_value(self):
        self.assertIsNone(report.number(10 ** 999))
        self.assertIsNone(report.app_record(app(durationMs=10 ** 999)))
        result = report.summarize([client(elapsed_ms=10 ** 999)])
        self.assertEqual(result['request_count'], 0)

    def test_unrelated_logs_or_bad_ids_are_not_request_evidence(self):
        for event in [app(event='other'), app(route='/actuator'), app(appRequestId=SECRET),
                      app(durationMs=float('nan')), app(durationMs=True), app(durationMs=-1)]:
            self.assertIsNone(report.app_record(event))
        parsed = report.app_record(app(clientProbeId=SECRET, gatewayRequestId='JWT.part.signature', status=None))
        self.assertIsNone(parsed['client_probe_id'])
        self.assertIsNone(parsed['gateway_extended_request_id'])
        self.assertIsNone(parsed['status'])

    def test_cloudwatch_message_and_spring_prefix_accept_only_known_json_event(self):
        event = json.dumps(app(), separators=(',', ':'))
        self.assertEqual(report.app_record({'message': 'INFO logger : ' + event}), report.app_record(app()))
        self.assertIsNone(report.app_record('INFO ' + SECRET))
        self.assertIsNone(report.app_record('INFO ' + event + ' trailing invalid text'))

    def test_sorts_slowest_and_skips_control_records(self):
        result = report.summarize([{'phase': 'cooldown_start'}, client(sequence=1, elapsed_ms=5),
                                   client(sequence=2, elapsed_ms=20)], top=1)
        self.assertEqual(result['request_count'], 2)
        self.assertEqual(result['slowest_requests'][0]['sequence'], 2)

    def test_cli_report_is_private_and_cannot_overwrite_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source, logs, output = [Path(directory) / name for name in ('requests.jsonl', 'app.jsonl', 'report.json')]
            source.write_text(json.dumps(client(body=SECRET)) + '\n')
            logs.write_text('INFO prefix ' + json.dumps(app(), separators=(',', ':')) + '\n')
            args = ['latency_report.py', '--requests', str(source), '--app-logs', str(logs), '--output', str(output)]
            with patch('sys.argv', args), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(report.main(), 0)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(SECRET, output.read_text())
            self.assertEqual(json.loads(output.read_text())['matched_application_requests'], 1)
            before = output.read_bytes()
            with patch('sys.argv', args), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(report.main(), 2)
            self.assertEqual(output.read_bytes(), before)

    def test_malformed_or_oversized_input_does_not_leak_source_or_create_report(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'input', Path(directory) / 'report'
            for value in [SECRET, 'x' * (report.MAX_LINE_BYTES + 1)]:
                source.write_text(value)
                args = ['latency_report.py', '--requests', str(source), '--output', str(output)]
                with patch('sys.argv', args), contextlib.redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(report.main(), 2)
                self.assertNotIn(SECRET, error.getvalue())
                self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
