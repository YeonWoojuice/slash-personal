"""Check the one-off task cannot silently become a public or persistent service."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class DbTaskBoundaries(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'experiment/db-test.tf.json').read_text())
        self.r = self.config['resource']
        self.container = self.config['locals']['db_test_container']

    def test_optional_definition_never_starts_a_service(self):
        self.assertFalse(self.config['variable']['enable_db_test_task']['default'])
        self.assertNotIn('aws_ecs_service', self.r)
        self.assertNotIn('null_resource', self.r)
        for group in self.r.values():
            for resource in group.values():
                self.assertEqual(resource['count'], '${var.enable_db_test_task ? 1 : 0}')
                self.assertNotIn('provisioner', resource)
        conditions = self.r['terraform_data']['db_test_contract']['lifecycle']['precondition']
        self.assertIn('var.enable_workloads && var.enable_cloudwatch_metrics', conditions[0]['condition'])
        self.assertIn('api-baseline', conditions[0]['condition'])
        self.assertIn('var.db_test_pulses * 17', conditions[2]['condition'])
        self.assertIn('<= 600', conditions[2]['condition'])

    def test_no_test_ingress_and_only_db_or_https_egress(self):
        test_sg = '${aws_security_group.db_test[0].id}'
        for ingress in self.r['aws_vpc_security_group_ingress_rule'].values():
            self.assertNotEqual(ingress['security_group_id'], test_sg)
            self.assertEqual(ingress['security_group_id'], '${aws_security_group.db.id}')
            self.assertEqual(ingress['referenced_security_group_id'], test_sg)
            self.assertEqual(ingress['from_port'], 5432)
        outbound = self.r['aws_vpc_security_group_egress_rule']
        self.assertEqual(outbound['db_test_postgres']['referenced_security_group_id'], '${aws_security_group.db.id}')
        self.assertEqual({x['to_port'] for x in outbound.values()}, {5432, 443})

    def test_secret_only_injected_by_execution_role(self):
        policies = self.r['aws_iam_role_policy']
        self.assertEqual(len(policies), 1)
        policy = policies['db_test_execution']
        self.assertEqual(policy['role'], '${aws_iam_role.db_test_execution[0].id}')
        self.assertIn('Resource=aws_db_instance.test.master_user_secret[0].secret_arn', policy['policy'])
        self.assertIn('Resource=local.db_test_repository_arn', policy['policy'])
        self.assertNotIn('ssmmessages', policy['policy'])
        env = {entry['name']: entry['value'] for entry in self.container['environment']}
        self.assertNotIn('PGPASSWORD', env)
        self.assertEqual(env['PGHOST'], '${aws_db_instance.test.address}')
        self.assertEqual(env['PGDATABASE'], 'slash')
        self.assertEqual(env['CONFIRM_DISPOSABLE'], 'slash-m2')
        self.assertEqual(env['DB_TEST_MODE'], 'delay')
        self.assertNotIn('DB_TEST_EXPECTED_APP_IP', env)
        self.assertIn('core_service_arn=aws_ecs_service.core[0].id', self.config['output']['db_test']['value'])
        self.assertEqual(self.container['secrets'], [{'name': 'PGPASSWORD', 'valueFrom': '${aws_db_instance.test.master_user_secret[0].secret_arn}:password::'}])

    def test_fixed_image_entrypoint_and_no_listener(self):
        task = self.r['aws_ecs_task_definition']['db_test']
        self.assertIn('terraform_data.db_test_contract', task['depends_on'])
        self.assertEqual(task['cpu'], '256')
        self.assertEqual(task['runtime_platform']['cpu_architecture'], 'X86_64')
        self.assertNotIn('command', self.container)
        self.assertNotIn('entryPoint', self.container)
        self.assertNotIn('portMappings', self.container)
        self.assertTrue(self.container['readonlyRootFilesystem'])
        self.assertEqual(self.container['mountPoints'][0]['containerPath'], '/tmp')

if __name__ == '__main__':
    unittest.main()
