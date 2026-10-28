"""Offline lifecycle checks: these tests never invoke the AWS CLI."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('slash_task_runner', Path(__file__).with_name('run.py'))
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
ACCOUNT = runner.ACCOUNT
PREFIX = f'arn:aws:ecs:ap-northeast-2:{ACCOUNT}:'
TASK = PREFIX + 'task/slash-test/0123456789abcdef'


def config():
    return {'account_id': ACCOUNT, 'region': 'ap-northeast-2',
            'cluster_arn': PREFIX + 'cluster/slash-test',
            'core_service_arn': PREFIX + 'service/slash-test/core',
            'task_definition_arn': PREFIX + 'task-definition/slash-test-db-test:1',
            'subnets': ['subnet-123abc', 'subnet-456def'], 'security_groups': ['sg-789abc'],
            'assign_public_ip': 'ENABLED', 'container': 'db-test',
            'expires_at': '2099-01-01T00:00:00Z'}


class Clock:
    def __init__(self):
        self.now = time.time()
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


class FakeAWS:
    def __init__(self):
        self.calls = []
        self.account = ACCOUNT
        self.active = []
        self.states = ['RUNNING', 'STOPPED']
        self.cleanup_states = ['STOPPED']
        self.exit_code = 0
        self.launch_error = None
        self.recovery = [[TASK]]
        self.stopping = False
        self.core_tasks = [PREFIX + 'task/slash-test/core123']
        self.core_service = {'serviceArn': PREFIX + 'service/slash-test/core', 'serviceName': 'core',
                             'status': 'ACTIVE', 'desiredCount': 1, 'runningCount': 1, 'pendingCount': 0,
                             'taskDefinition': PREFIX + 'task-definition/slash-test-core:7',
                             'deployments': [{'status': 'PRIMARY', 'rolloutState': 'COMPLETED'}]}
        self.core_task = {'taskArn': self.core_tasks[0], 'lastStatus': 'RUNNING', 'desiredStatus': 'RUNNING',
                         'group': 'service:core', 'taskDefinitionArn': self.core_service['taskDefinition'],
                         'containers': [{'name': 'api', 'lastStatus': 'RUNNING'}],
                         'attachments': [{'type': 'ElasticNetworkInterface', 'status': 'ATTACHED',
                                          'details': [{'name': 'privateIPv4Address', 'value': '10.40.1.5'},
                                                      {'name': 'subnetId', 'value': 'subnet-123abc'}]}]}
        self.container = {
            'name': 'db-test',
            'image': f'{ACCOUNT}.dkr.ecr.ap-northeast-2.amazonaws.com/slash-lab/db-test@sha256:' + 'a' * 64,
            'environment': [{'name': 'CONFIRM_DISPOSABLE', 'value': 'slash-m2'},
                            {'name': 'PGDATABASE', 'value': 'slash'}]}

    def count(self, operation):
        return sum(call[:2] == operation for call in self.calls)

    @staticmethod
    def next(values):
        return values.pop(0) if len(values) > 1 else values[0]

    def __call__(self, *args):
        self.calls.append(args)
        operation = args[:2]
        if operation == ('sts', 'get-caller-identity'):
            return {'Account': self.account}
        if operation == ('ecs', 'describe-services'):
            return {'services': [self.core_service]}
        if operation == ('ecs', 'list-tasks'):
            if '--service-name' in args:
                return {'taskArns': self.core_tasks}
            return {'taskArns': self.next(self.recovery) if '--started-by' in args else self.active}
        if operation == ('ecs', 'describe-task-definition'):
            return {'taskDefinition': {'containerDefinitions': [self.container]}}
        if operation == ('ecs', 'run-task'):
            if self.launch_error:
                raise self.launch_error
            return {'tasks': [{'taskArn': TASK}], 'failures': []}
        if operation == ('ecs', 'stop-task'):
            self.stopping = True
            return {'task': {'taskArn': TASK, 'lastStatus': 'STOPPING'}}
        if operation == ('ecs', 'describe-tasks'):
            if args[-1] == self.core_task['taskArn']:
                return {'tasks': [self.core_task]}
            state = self.next(self.cleanup_states if self.stopping else self.states)
            if isinstance(state, BaseException):
                raise state
            return {'tasks': [{'taskArn': TASK, 'lastStatus': state,
                               'containers': [{'name': 'db-test', 'exitCode': self.exit_code}]}]}
        raise AssertionError('Unexpected AWS operation: ' + repr(operation))


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.aws = FakeAWS()
        self.clock = Clock()
        self.records = []

    def run_task(self, settings=None, mode='delay'):
        return runner.run(settings or config(), self.aws, self.records.append,
                          clock=self.clock, sleep=self.clock.sleep, mode=mode)

    def assert_cleaned_once(self):
        self.assertEqual(self.aws.count(('ecs', 'run-task')), 1)
        self.assertEqual(self.aws.count(('ecs', 'stop-task')), 1)
        self.assertTrue(any(r.get('event') == 'cleanup' and r.get('stopped_confirmed') for r in self.records))

    def test_wrong_config_account_and_expired_config_refuse_before_aws(self):
        for changes in [{'account_id': '000000000000'}, {'expires_at': '2000-01-01T00:00:00Z'}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.run_task({**config(), **changes})
        self.assertEqual(self.aws.calls, [])

    def test_wrong_current_identity_refuses_before_task_launch(self):
        self.aws.account = '000000000000'
        with self.assertRaises(ValueError):
            self.run_task()
        self.assertEqual(self.aws.count(('ecs', 'run-task')), 0)

    def test_existing_pending_or_running_task_refuses_duplicate(self):
        self.aws.active = [TASK]
        with self.assertRaises(ValueError):
            self.run_task()
        self.assertEqual(self.aws.count(('ecs', 'run-task')), 0)
        listing = next(call for call in self.aws.calls if call[:2] == ('ecs', 'list-tasks'))
        self.assertEqual(listing[listing.index('--desired-status') + 1], 'RUNNING')

    def test_floating_image_or_command_override_refuses_launch(self):
        for changes in [{'image': 'postgres:latest'}, {'command': ['sh']}]:
            with self.subTest(changes=changes):
                self.aws = FakeAWS()
                self.aws.container.update(changes)
                with self.assertRaises(ValueError):
                    self.run_task()
                self.assertEqual(self.aws.count(('ecs', 'run-task')), 0)

    def test_stopped_success_requires_exit_zero(self):
        self.assertEqual(self.run_task(), 0)
        self.assertEqual(self.aws.count(('ecs', 'run-task')), 1)
        self.assertEqual(self.aws.count(('ecs', 'stop-task')), 0)
        self.assertEqual(self.records[-1]['event'], 'finished')
        self.assertTrue(self.records[-1]['success'])

    def test_nonzero_exit_is_failure_without_restarting(self):
        self.aws.exit_code = 1
        self.assertEqual(self.run_task(), 1)
        self.assertFalse(self.records[-1]['success'])
        self.assertEqual(self.aws.count(('ecs', 'run-task')), 1)

    def test_timeout_stops_and_confirms_stopped(self):
        self.aws.states = ['RUNNING']
        with self.assertRaises(TimeoutError):
            self.run_task()
        self.assert_cleaned_once()

    def test_interruption_during_polling_stops_and_confirms_stopped(self):
        self.aws.states = [KeyboardInterrupt()]
        with self.assertRaises(KeyboardInterrupt):
            self.run_task()
        self.assert_cleaned_once()

    def test_lost_run_response_recovers_own_task_and_cleans_without_second_launch(self):
        self.aws.launch_error = subprocess.TimeoutExpired(['aws', 'ecs', 'run-task'], 45)
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_task()
        self.assert_cleaned_once()
        launch = next(call for call in self.aws.calls if call[:2] == ('ecs', 'run-task'))
        recovery = next(call for call in self.aws.calls if '--started-by' in call and call[:2] == ('ecs', 'list-tasks'))
        run_id = launch[launch.index('--started-by') + 1]
        self.assertEqual(launch[launch.index('--client-token') + 1], run_id)
        self.assertEqual(recovery[recovery.index('--started-by') + 1], run_id)

    def test_interrupt_during_launch_also_recovers_and_cleans_accepted_task(self):
        self.aws.launch_error = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.run_task()
        self.assert_cleaned_once()

    def test_lost_launch_response_retries_discovery_before_cleanup(self):
        self.aws.launch_error = OSError('synthetic connection lost')
        self.aws.recovery = [[], [], [TASK]]
        with self.assertRaises(OSError):
            self.run_task()
        self.assert_cleaned_once()
        recoveries = [call for call in self.aws.calls if call[:2] == ('ecs', 'list-tasks') and '--started-by' in call]
        self.assertEqual(len(recoveries), 3)

    def test_unknown_launch_outcome_never_launches_again(self):
        self.aws.launch_error = ValueError('synthetic response parse failure')
        self.aws.recovery = [[]]
        with self.assertRaises(ValueError):
            self.run_task()
        self.assertEqual(self.aws.count(('ecs', 'run-task')), 1)
        self.assertEqual(self.aws.count(('ecs', 'stop-task')), 0)
        self.assertTrue(any(r.get('event') == 'launch_outcome_unknown' and r.get('run_id') for r in self.records))
        recoveries = [call for call in self.aws.calls if call[:2] == ('ecs', 'list-tasks') and '--started-by' in call]
        self.assertEqual(len(recoveries), 5)

    def test_unconfirmed_stop_is_reported_without_success_claim(self):
        self.aws.states = [RuntimeError('synthetic state read failure')]
        self.aws.cleanup_states = ['STOPPING']
        with self.assertRaises(RuntimeError):
            self.run_task()
        self.assertFalse(self.records[-1]['stopped_confirmed'])
        self.assertFalse(any(r.get('event') == 'finished' and r.get('success') for r in self.records))

    def test_cancel_mode_uses_only_resolved_app_ip_and_mode_overrides(self):
        self.assertEqual(self.run_task(mode='cancel-one'), 0)
        launch = next(call for call in self.aws.calls if call[:2] == ('ecs', 'run-task'))
        overrides = json.loads(launch[launch.index('--overrides') + 1])
        self.assertEqual(overrides, {'containerOverrides': [{'name': 'db-test', 'environment': [
            {'name': 'DB_TEST_MODE', 'value': 'cancel-one'},
            {'name': 'DB_TEST_EXPECTED_APP_IP', 'value': '10.40.1.5'}]}]})
        self.assertTrue(any(r.get('event') == 'verified_cancel_target' for r in self.records))

    def test_delay_mode_never_overrides_task_settings(self):
        self.run_task()
        launch = next(call for call in self.aws.calls if call[:2] == ('ecs', 'run-task'))
        self.assertNotIn('--overrides', launch)
        self.assertEqual(self.aws.count(('ecs', 'describe-services')), 0)

    def test_cancel_mode_refuses_missing_foreign_or_rolling_core_service(self):
        for change in [{'core_service_arn': ''}, {'core_service_arn': PREFIX + 'service/other/core'}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.run_task({**config(), **change}, mode='cancel-one')
        self.aws.core_service['deployments'][0]['rolloutState'] = 'IN_PROGRESS'
        with self.assertRaises(ValueError):
            self.run_task(mode='cancel-one')
        self.assertEqual(self.aws.count(('ecs', 'run-task')), 0)

    def test_cancel_mode_refuses_zero_or_multiple_app_tasks(self):
        for values in [[], [PREFIX + 'task/slash-test/a', PREFIX + 'task/slash-test/b']]:
            self.aws.core_tasks = values
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.run_task(mode='cancel-one')
        self.assertEqual(self.aws.count(('ecs', 'run-task')), 0)

    def test_cancel_mode_refuses_changed_revision_network_or_wrong_container(self):
        for kind in ['revision', 'ip', 'subnet', 'container', 'health']:
            self.aws = FakeAWS()
            if kind == 'revision': self.aws.core_task['taskDefinitionArn'] += '0'
            if kind == 'ip': self.aws.core_task['attachments'][0]['details'][0]['value'] = '8.8.8.8'
            if kind == 'subnet': self.aws.core_task['attachments'][0]['details'][1]['value'] = 'subnet-dead'
            if kind == 'container': self.aws.core_task['containers'][0]['name'] = 'other'
            if kind == 'health': self.aws.core_task['healthStatus'] = 'UNHEALTHY'
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.run_task(mode='cancel-one')
            self.assertEqual(self.aws.count(('ecs', 'run-task')), 0)

    def test_cancel_mode_refuses_repetition_or_preset_cancel_target(self):
        for environment in [{'name': 'DB_TEST_PULSES', 'value': '2'},
                            {'name': 'DB_TEST_MODE', 'value': 'cancel-one'},
                            {'name': 'DB_TEST_EXPECTED_APP_IP', 'value': '10.40.1.5'}]:
            self.aws = FakeAWS()
            self.aws.container['environment'].append(environment)
            with self.subTest(environment=environment), self.assertRaises(ValueError):
                self.run_task(mode='cancel-one')
            self.assertEqual(self.aws.count(('ecs', 'run-task')), 0)

    def test_default_preview_never_constructs_aws_client_or_runs_task(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(config()))
            with patch('sys.argv', ['run.py', '--config', str(path)]), \
                    patch.object(runner, 'Aws') as aws_constructor, \
                    patch('sys.stdout', new_callable=io.StringIO) as stdout:
                self.assertEqual(runner.main(), 0)
                aws_constructor.assert_not_called()
            self.assertEqual(json.loads(stdout.getvalue())['mode'], 'preview_only')


if __name__ == '__main__':
    unittest.main()
