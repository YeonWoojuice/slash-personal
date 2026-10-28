#!/usr/bin/env python3
"""Preview or explicitly run one deployed, bounded Slash DB test task."""
import argparse
from datetime import datetime, timezone
import json
import ipaddress
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid

ACCOUNT = '642935793048'
REGION = 'ap-northeast-2'


def validate(config, now=None):
    if not isinstance(config, dict) or config.get('account_id') != ACCOUNT or config.get('region') != REGION:
        raise ValueError('Expected the approved account and Seoul region.')
    prefix = f'arn:aws:ecs:{REGION}:{ACCOUNT}:'
    if not re.fullmatch(re.escape(prefix) + r'cluster/[A-Za-z0-9_-]+', config.get('cluster_arn', '')):
        raise ValueError('Invalid experiment cluster ARN.')
    if not re.fullmatch(re.escape(prefix) + r'task-definition/[A-Za-z0-9_-]+-db-test:[0-9]+', config.get('task_definition_arn', '')):
        raise ValueError('Expected a versioned db-test task definition.')
    for name, pattern in [('subnets', r'subnet-[0-9a-f]+'), ('security_groups', r'sg-[0-9a-f]+')]:
        values = config.get(name)
        if not isinstance(values, list) or not 1 <= len(values) <= 2 or not all(isinstance(v, str) and re.fullmatch(pattern, v) for v in values):
            raise ValueError('Invalid experiment network settings.')
    if config.get('container') != 'db-test' or config.get('assign_public_ip') != 'ENABLED':
        raise ValueError('Unexpected task container or network mode.')
    expiry = datetime.fromisoformat(config['expires_at'].replace('Z', '+00:00'))
    if expiry.tzinfo is None or expiry <= (now or datetime.now(timezone.utc)):
        raise ValueError('Experiment cleanup deadline has expired or has no timezone.')
    return expiry.timestamp()


class Aws:
    def __call__(self, *args):
        result = subprocess.run(['aws', '--region', REGION, '--no-cli-pager', '--output', 'json',
                                 '--cli-connect-timeout', '5', '--cli-read-timeout', '15', *args],
                                capture_output=True, text=True, timeout=45)
        if result.returncode:
            # Avoid echoing credentials or arbitrary service error content.
            raise RuntimeError('AWS CLI failed: ' + ' '.join(args[:2]))
        return json.loads(result.stdout)


def resolve_core_target(config, aws):
    """Resolve one stable running core task from deployed ECS metadata, never CLI IP input."""
    cluster = config['cluster_arn']
    cluster_name = cluster.rsplit('/', 1)[1]
    prefix = f'arn:aws:ecs:{REGION}:{ACCOUNT}:service/{cluster_name}/'
    service_arn = config.get('core_service_arn', '')
    if not re.fullmatch(re.escape(prefix) + r'[A-Za-z0-9_-]+', service_arn):
        raise ValueError('A deployed core service ARN in this cluster is required.')
    response = aws('ecs', 'describe-services', '--cluster', cluster, '--services', service_arn)
    services = response.get('services', [])
    if response.get('failures') or len(services) != 1:
        raise ValueError('Could not identify the core service.')
    service = services[0]
    deployments = service.get('deployments', [])
    if (service.get('serviceArn') != service_arn or service.get('status') != 'ACTIVE'
            or service.get('desiredCount') != 1 or service.get('runningCount') != 1
            or service.get('pendingCount') != 0 or len(deployments) != 1
            or deployments[0].get('status') != 'PRIMARY'
            or deployments[0].get('rolloutState') != 'COMPLETED'):
        raise ValueError('Core must have exactly one stable running task with no rollout.')
    listed = aws('ecs', 'list-tasks', '--cluster', cluster, '--service-name', service['serviceName'],
                 '--desired-status', 'RUNNING').get('taskArns', [])
    if len(listed) != 1:
        raise ValueError('Core must resolve to exactly one running task.')
    described = aws('ecs', 'describe-tasks', '--cluster', cluster, '--tasks', listed[0])
    tasks = described.get('tasks', [])
    if described.get('failures') or len(tasks) != 1:
        raise ValueError('Could not inspect the core task.')
    task = tasks[0]
    if (task.get('taskArn') != listed[0] or task.get('lastStatus') != 'RUNNING'
            or task.get('desiredStatus') != 'RUNNING'
            or task.get('group') != 'service:' + service['serviceName']
            or task.get('taskDefinitionArn') != service.get('taskDefinition')
            or task.get('healthStatus') == 'UNHEALTHY'):
        raise ValueError('Core task does not match the stable deployed service.')
    containers = task.get('containers', [])
    if (len(containers) != 1 or containers[0].get('name') != 'api'
            or containers[0].get('lastStatus') != 'RUNNING'):
        raise ValueError('Expected one running core API container.')
    interfaces = [a for a in task.get('attachments', [])
                  if a.get('type') == 'ElasticNetworkInterface' and a.get('status') == 'ATTACHED']
    if len(interfaces) != 1:
        raise ValueError('Expected one attached core network interface.')
    details = {d['name']: d['value'] for d in interfaces[0].get('details', [])}
    ip = ipaddress.IPv4Address(details.get('privateIPv4Address', ''))
    private_ranges = ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')
    if (not any(ip in ipaddress.IPv4Network(cidr) for cidr in private_ranges)
            or details.get('subnetId') not in config['subnets']):
        raise ValueError('Core IP must belong to the deployed private task network.')
    return {'task_arn': task['taskArn'], 'private_ip': str(ip)}


def run(config, aws, emit, clock=time.time, sleep=time.sleep, mode='delay'):
    expiry = validate(config)
    if mode not in ('delay', 'cancel-one'):
        raise ValueError('Unsupported DB trial mode.')
    identity = aws('sts', 'get-caller-identity')
    if identity['Account'] != ACCOUNT:
        raise ValueError('Current AWS identity is not the approved account.')
    cluster = config['cluster_arn']
    definition = config['task_definition_arn']
    family = definition.split('/')[-1].rsplit(':', 1)[0]
    if aws('ecs', 'list-tasks', '--cluster', cluster, '--family', family, '--desired-status', 'RUNNING').get('taskArns'):
        raise ValueError('A DB test is already pending/running. Wait for its confirmed stop.')
    definition_data = aws('ecs', 'describe-task-definition', '--task-definition', definition)['taskDefinition']
    containers = definition_data.get('containerDefinitions', [])
    if len(containers) != 1 or containers[0].get('name') != 'db-test' or containers[0].get('command') or containers[0].get('entryPoint'):
        raise ValueError('Expected the fixed db-test image entrypoint with no command override.')
    if not re.fullmatch(ACCOUNT + r'[.]dkr[.]ecr[.]ap-northeast-2[.]amazonaws[.]com/[a-z0-9/._-]+@sha256:[a-f0-9]{64}', containers[0].get('image', '')):
        raise ValueError('Expected the reviewed immutable ECR image.')
    env = {item['name']: item['value'] for item in containers[0].get('environment', [])}
    if env.get('CONFIRM_DISPOSABLE') != 'slash-m2' or env.get('PGDATABASE') != 'slash':
        raise ValueError('Expected disposable Slash database settings.')
    overrides = []
    if env.get('DB_TEST_MODE', 'delay') != 'delay' or env.get('DB_TEST_EXPECTED_APP_IP'):
        raise ValueError('Task definition must default to delay with no preset cancellation target.')
    if mode == 'cancel-one':
        if env.get('DB_TEST_PULSES', '1') != '1':
            raise ValueError('cancel-one requires exactly one configured pulse.')
        target = resolve_core_target(config, aws)
        emit({'event': 'verified_cancel_target', **target})
        overrides = ['--overrides', json.dumps({'containerOverrides': [{'name': 'db-test', 'environment': [
            {'name': 'DB_TEST_MODE', 'value': 'cancel-one'},
            {'name': 'DB_TEST_EXPECTED_APP_IP', 'value': target['private_ip']}]}]})]
    run_id = 'slash-m2-' + uuid.uuid4().hex[:20]
    network = {'awsvpcConfiguration': {'subnets': config['subnets'], 'securityGroups': config['security_groups'], 'assignPublicIp': 'ENABLED'}}
    deadline = min(clock() + 900, expiry)
    task_arn = None
    stopped = False
    emit({'event': 'launch_requested', 'run_id': run_id, 'task_definition': definition, 'trial_mode': mode})
    try:
        try:
            result = aws('ecs', 'run-task', '--cluster', cluster, '--task-definition', definition,
                         '--launch-type', 'FARGATE', '--platform-version', '1.4.0', '--count', '1',
                         '--started-by', run_id, '--client-token', run_id, '--propagate-tags', 'TASK_DEFINITION',
                         '--network-configuration', json.dumps(network), *overrides)
        except (Exception, KeyboardInterrupt):
            # Errors and interruption may follow an accepted start. ECS discovery
            # is eventually consistent; recover only this unique run, with a bound.
            recovered = []
            for attempt in range(5):
                try:
                    recovered = aws('ecs', 'list-tasks', '--cluster', cluster, '--started-by', run_id).get('taskArns', [])
                except Exception:
                    recovered = []
                if recovered:
                    break
                if attempt < 4:
                    sleep(2)
            if len(recovered) == 1:
                task_arn = recovered[0]
                emit({'event': 'recovered_after_lost_response', 'task_arn': task_arn})
            else:
                emit({'event': 'launch_outcome_unknown', 'run_id': run_id,
                      'action': 'Check tasks by startedBy before retrying; no automatic second launch.'})
            raise
        tasks = result.get('tasks', [])
        if tasks:
            task_arn = tasks[0]['taskArn']
        if result.get('failures') or len(tasks) != 1:
            raise RuntimeError('ECS did not accept exactly one task.')
        emit({'event': 'task_started', 'task_arn': task_arn})
        last = None
        while clock() < deadline:
            response = aws('ecs', 'describe-tasks', '--cluster', cluster, '--tasks', task_arn)
            if response.get('failures') or len(response.get('tasks', [])) != 1:
                raise RuntimeError('Could not confirm task state.')
            task = response['tasks'][0]
            state = task['lastStatus']
            if state != last:
                emit({'event': 'state', 'state': state, 'task_arn': task_arn})
                last = state
            if state == 'STOPPED':
                stopped = True
                containers = task.get('containers', [])
                okay = len(containers) == 1 and containers[0].get('name') == 'db-test' and containers[0].get('exitCode') == 0
                emit({'event': 'finished', 'success': okay,
                      'exit_code': containers[0].get('exitCode') if containers else None})
                return 0 if okay else 1
            sleep(5)
        raise TimeoutError('Task exceeded its startup/runtime/cleanup deadline.')
    finally:
        if task_arn and not stopped:
            try:
                aws('ecs', 'stop-task', '--cluster', cluster, '--task', task_arn, '--reason', 'Slash bounded DB test cleanup')
                cleanup_deadline = clock() + 90
                while clock() < cleanup_deadline:
                    tasks = aws('ecs', 'describe-tasks', '--cluster', cluster, '--tasks', task_arn).get('tasks', [])
                    if len(tasks) == 1 and tasks[0]['lastStatus'] == 'STOPPED':
                        stopped = True
                        break
                    sleep(5)
                emit({'event': 'cleanup', 'task_arn': task_arn, 'stopped_confirmed': stopped})
            except Exception:
                emit({'event': 'cleanup', 'task_arn': task_arn, 'stopped_confirmed': False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True, help='terraform output -json db_test file')
    parser.add_argument('--mode', choices=['delay', 'cancel-one'], default='delay')
    parser.add_argument('--execute', action='store_true', help='Actually start the deployed fault task; otherwise preview only')
    parser.add_argument('--result', type=Path, help='New private JSONL file required with --execute')
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text())
        validate(config)
        if not args.execute:
            print(json.dumps({'mode': 'preview_only', 'account': ACCOUNT, 'region': REGION,
                              'task_definition': config['task_definition_arn'], 'count': 1,
                              'expires_at': config['expires_at'], 'trial_mode': args.mode}, indent=2))
            return 0
        if args.result is None:
            raise ValueError('--result is required for an actual run.')
        descriptor = os.open(args.result, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        def interrupted(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, interrupted)
        with os.fdopen(descriptor, 'w') as output:
            def emit(record):
                record = {'at': datetime.now(timezone.utc).isoformat(), **record}
                line = json.dumps(record)
                output.write(line + '\n'); output.flush()
                print(line, flush=True)
            return run(config, Aws(), emit, mode=args.mode)
    except KeyboardInterrupt:
        print('Interrupted. Check the cleanup record; DB locks may persist until the SQL timeout.', file=sys.stderr)
        return 130
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, TimeoutError, subprocess.TimeoutExpired):
        print('Task preparation/run failed. Inspect the private result file; an unconfirmed stop requires follow-up.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
