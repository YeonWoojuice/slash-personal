import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import run
import step_probe as probe

ORIGIN = run.Target('abc123def4.execute-api.ap-northeast-2.amazonaws.com', 443, '/m2/api/v1/me')
SECRET = 'do-not-record-token-or-response'


def success(sequence, phase='step', **changes):
    result = {'sequence': sequence, 'phase': phase, 'status': 200, 'error': None,
              'elapsed_ms': 100, 'started_at': '2026-10-29T01:00:00+09:00',
              'finished_at': '2026-10-29T01:00:00.100+09:00'}
    result.update(changes)
    return result


class Clock:
    def __init__(self):
        self.value = 0.0
        self.jump = 0
    def now(self):
        return self.value
    def sleep(self, seconds):
        self.value += seconds + self.jump
        self.jump = 0


class Future:
    def __init__(self, clock, finish, fn):
        self.clock, self.finish, self.fn = clock, finish, fn
        self.value = None
    def done(self):
        return self.clock.now() >= self.finish
    def result(self):
        if not self.done():
            self.clock.sleep(self.finish - self.clock.now())
        if self.value is None:
            self.value = self.fn()
        return self.value


class Executor:
    def __init__(self, clock, delay):
        self.clock, self.delay = clock, delay
        self.starts, self.futures = [], []
        self.peak = 0
    def factory(self, max_workers):
        assert max_workers == 4
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def submit(self, fn, sequence, phase, stage):
        self.starts.append((sequence, stage, self.clock.now()))
        future = Future(self.clock, self.clock.now() + self.delay(sequence, stage),
                        lambda: fn(sequence, phase, stage))
        self.futures.append(future)
        self.peak = max(self.peak, sum(not f.done() for f in self.futures))
        return future


class BoundedSteps(unittest.TestCase):
    def execute(self, behavior=None, delay=lambda *_: 0, clock=None):
        clock = clock or Clock()
        executor, events, calls = Executor(clock, delay), [], []
        def request(origin, token, timeout, sequence, phase='trial'):
            self.assertEqual(origin, ORIGIN)
            self.assertEqual(token, SECRET)
            self.assertEqual(timeout, 3)
            calls.append((sequence, phase, clock.now()))
            return behavior(sequence, phase) if behavior else success(sequence, phase)
        result = probe.run_probe(ORIGIN, SECRET, events.append, request=request,
                                 clock=clock.now, sleep=clock.sleep, executor_factory=executor.factory)
        return result, events, calls, executor, clock

    def test_full_schedule_is_1020_plus_two_checks_and_passive_cooldown(self):
        result, events, calls, executor, clock = self.execute()
        self.assertEqual(result['outcome'], 'observed')
        self.assertEqual([x['sent'] for x in result['stages']], [60, 120, 240, 600])
        self.assertEqual(result['sent_step_requests'], 1020)
        self.assertEqual(len(calls), 1022)
        self.assertEqual(calls[0][1], 'preflight')
        self.assertEqual(calls[-1][1], 'postflight')
        self.assertAlmostEqual(calls[-1][2], 480)
        self.assertAlmostEqual(clock.now(), 600)
        self.assertEqual(events[-1]['phase'], 'cooldown_start')
        for stage, start, rate in [(1, 0, .5), (2, 120, 1), (3, 240, 2), (4, 360, 5)]:
            starts = [t for _, s, t in executor.starts if s == stage]
            for index, actual in enumerate(starts):
                self.assertAlmostEqual(actual, start + index / rate, places=6)
        self.assertTrue(all(x['latency_ms']['p95'] == 100 for x in result['stages']))

    def test_preflight_failure_sends_no_steps_or_postflight(self):
        result, _, calls, executor, _ = self.execute(lambda n, p: success(n, p, status=401, error='http_status'))
        self.assertEqual(result['outcome'], 'stopped')
        self.assertEqual(result['stop_reason'], 'http_status')
        self.assertEqual(len(calls), 1)
        self.assertEqual(executor.starts, [])

    def test_every_error_status_stops_before_next_request(self):
        for status in [401, 403, 429, 500, 503]:
            with self.subTest(status=status):
                result, _, calls, _, _ = self.execute(lambda n, p: success(n, p, status=status if p == 'step' else 200))
                self.assertEqual(result['sent_step_requests'], 1)
                self.assertEqual(result['stop_reason'], 'http_status')
                self.assertFalse(result['postflight_passed'])
                self.assertEqual(len(calls), 2)

    def test_transport_or_shape_error_and_slow_200_stop(self):
        for changes, reason in [({'error': 'tls_error'}, 'tls_error'),
                                ({'error': 'invalid_response_shape'}, 'invalid_response_shape'),
                                ({'error': 'timeout'}, 'timeout'),
                                ({'elapsed_ms': 2000.001}, 'latency_limit')]:
            with self.subTest(reason=reason):
                result, _, _, _, _ = self.execute(lambda n, p: success(n, p, **(changes if p == 'step' else {})))
                self.assertEqual(result['stop_reason'], reason)
                self.assertEqual(result['sent_step_requests'], 1)

    def test_inflight_over_two_seconds_stops_before_completion(self):
        result, events, _, executor, _ = self.execute(delay=lambda *_: 2.5)
        self.assertEqual(result['stop_reason'], 'inflight_latency_limit')
        self.assertLessEqual(result['sent_step_requests'], 2)
        self.assertEqual(result['sent_step_requests'], sum(x['completed'] for x in result['stages']))
        self.assertLessEqual(executor.peak, 4)
        self.assertTrue(any(e.get('error') == 'inflight_latency_limit' for e in events))

    def test_capacity_limit_stops_and_drains_without_catchup(self):
        result, _, _, executor, _ = self.execute(delay=lambda n, stage: 1 if stage == 4 else 0)
        self.assertEqual(result['stop_reason'], 'capacity_skipped')
        self.assertEqual(result['stages'][3]['sent'], 4)
        self.assertEqual(result['skipped_step_requests'], 1)
        self.assertEqual(executor.peak, 4)
        self.assertEqual(result['sent_step_requests'], sum(x['completed'] for x in result['stages']))

    def test_scheduler_delay_is_not_replayed_as_a_burst(self):
        clock = Clock()
        clock.jump = 10
        result, _, _, executor, _ = self.execute(clock=clock)
        self.assertEqual(result['stop_reason'], 'schedule_skipped')
        self.assertEqual(len(executor.starts), 1)

    def test_sub_interval_pause_never_compresses_later_dispatches(self):
        clock = Clock()
        clock.jump = 3.8
        result, _, _, executor, _ = self.execute(clock=clock)
        self.assertEqual(result['outcome'], 'observed')
        self.assertLessEqual(result['schedule_elapsed_seconds'], 483)
        for previous, current in zip(executor.starts, executor.starts[1:]):
            interval = 1 / probe.STAGES[current[1] - 1][0]
            self.assertGreaterEqual(current[2] - previous[2] + 1e-9, interval)
        self.assertGreater(result['stages'][0]['dispatch_window_seconds'], 120)

    def test_stage_boundary_pause_keeps_new_stage_interval(self):
        class BoundaryClock(Clock):
            def sleep(self, seconds):
                if self.value < 117.9 <= self.value + seconds:
                    self.jump = 1.5
                super().sleep(seconds)
        result, _, _, executor, _ = self.execute(clock=BoundaryClock())
        self.assertEqual(result['outcome'], 'observed')
        last_first_stage = [x for x in executor.starts if x[1] == 1][-1]
        first_second_stage = next(x for x in executor.starts if x[1] == 2)
        self.assertGreaterEqual(first_second_stage[2] - last_first_stage[2] + 1e-9, 1)

    def test_pause_past_hard_limit_does_not_send_or_succeed(self):
        class EndClock(Clock):
            def sleep(self, seconds):
                if self.value < 479 <= self.value + seconds:
                    self.jump = 10
                super().sleep(seconds)
        result, _, _, executor, _ = self.execute(clock=EndClock())
        self.assertEqual(result['outcome'], 'stopped')
        self.assertEqual(result['stop_reason'], 'schedule_time_limit')
        self.assertTrue(all(start < 483 for _, _, start in executor.starts))
        self.assertLess(result['sent_step_requests'], 1020)

    def test_final_wait_oversleep_never_sends_late_postflight(self):
        class FinalWaitPause(Clock):
            def sleep(self, seconds):
                if self.value < 479.9 <= self.value + seconds:
                    self.jump = 10
                super().sleep(seconds)
        result, _, calls, _, _ = self.execute(clock=FinalWaitPause())
        self.assertEqual(result['sent_step_requests'], 1020)
        self.assertEqual(result['outcome'], 'stopped')
        self.assertEqual(result['stop_reason'], 'schedule_time_limit')
        self.assertFalse(result['postflight_passed'])
        self.assertIsNone(result['postflight_dispatch_offset_seconds'])
        self.assertFalse(any(phase == 'postflight' for _, phase, _ in calls))

    def test_drain_oversleep_never_sends_late_postflight(self):
        class DrainPause(Clock):
            def sleep(self, seconds):
                if self.value < 480.1 <= self.value + seconds:
                    self.jump = 10
                super().sleep(seconds)
        result, _, calls, _, _ = self.execute(clock=DrainPause(), delay=lambda n, stage: .5 if n == 1020 else 0)
        self.assertEqual(result['sent_step_requests'], 1020)
        self.assertEqual(result['outcome'], 'stopped')
        self.assertEqual(result['stop_reason'], 'schedule_time_limit')
        self.assertGreater(result['active_elapsed_seconds'], 483)
        self.assertFalse(any(phase == 'postflight' for _, phase, _ in calls))

    def test_postflight_failure_prevents_success(self):
        result, _, calls, _, _ = self.execute(lambda n, p: success(n, p, status=500 if p == 'postflight' else 200))
        self.assertEqual(result['outcome'], 'stopped')
        self.assertEqual(result['sent_step_requests'], 1020)
        self.assertFalse(result['postflight_passed'])
        self.assertEqual(len(calls), 1022)

    def test_untrusted_result_fields_and_exception_text_are_never_emitted(self):
        def bad(n, phase):
            if phase == 'step':
                raise RuntimeError(SECRET)
            return success(n, phase, body=SECRET, token=SECRET, email=SECRET,
                           headers={'Authorization': SECRET}, started_at=SECRET)
        result, events, _, _, _ = self.execute(bad)
        self.assertEqual(result['stop_reason'], 'request_exception')
        self.assertNotIn(SECRET, json.dumps([result, events]))
        self.assertIsNone(events[0]['started_at'])

    def test_invalid_latency_or_error_is_not_a_false_success(self):
        for value in [None, float('nan'), float('inf'), True, -1]:
            with self.subTest(value=value):
                result, _, _, _, _ = self.execute(lambda n, p: success(n, p, elapsed_ms=value))
                self.assertEqual(result['stop_reason'], 'invalid_result')
        for error in [SECRET, {'detail': SECRET}, [SECRET]]:
            result, events, _, _, _ = self.execute(lambda n, p: success(n, p, error=error))
            self.assertEqual(result['stop_reason'], 'invalid_result')
            self.assertNotIn(SECRET, json.dumps(events))


class Cli(unittest.TestCase):
    def test_private_files_and_minimum_token_lifetime_without_http(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'new'
            def fake(origin, token, emit):
                emit({'phase': 'preflight', 'status': 200})
                return {'outcome': 'observed'}
            argv = ['step_probe.py', '--base-url', 'https://' + ORIGIN.host + '/m2',
                    '--issuer', 'expected-issuer', '--client-id', 'expected-client', '--output', str(output)]
            with patch('sys.argv', argv), patch.object(probe.observer, 'read_token', return_value=SECRET), \
                    patch.object(probe.observer, 'check_token') as check, patch.object(probe, 'run_probe', side_effect=fake), \
                    patch('sys.stdout', new_callable=io.StringIO) as stdout:
                self.assertEqual(probe.main(), 0)
            check.assert_called_once_with(SECRET, 'expected-issuer', 'expected-client', 642)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
            for name in ['requests.jsonl', 'summary.json']:
                self.assertEqual(stat.S_IMODE((output / name).stat().st_mode), 0o600)
                self.assertNotIn(SECRET, (output / name).read_text())
            self.assertNotIn(SECRET, stdout.getvalue())

    def test_invalid_token_never_creates_output_or_runs_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'new'
            argv = ['step_probe.py', '--base-url', 'https://' + ORIGIN.host + '/m2', '--output', str(output)]
            with patch('sys.argv', argv), patch.object(probe.observer, 'read_token', return_value=SECRET), \
                    patch.object(probe.observer, 'check_token', side_effect=ValueError(SECRET)), \
                    patch.object(probe, 'run_probe') as call, patch('sys.stderr', new_callable=io.StringIO) as stderr:
                self.assertEqual(probe.main(), 2)
            call.assert_not_called()
            self.assertFalse(output.exists())
            self.assertNotIn(SECRET, stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
