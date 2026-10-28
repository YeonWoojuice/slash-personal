"""Offline regression checks for the disposable environment's lifecycle boundaries."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return json.loads((ROOT / path).read_text())

class Guardrails(unittest.TestCase):
    def setUp(self):
        self.main = read('experiment/main.tf.json')
        self.r = self.main['resource']

    def test_no_hourly_compute_in_foundation(self):
        self.assertEqual(set(read('foundation/main.tf.json')['resource']), {
            'aws_ecr_repository', 'aws_ecr_lifecycle_policy',
            'aws_cognito_user_pool', 'aws_cognito_user_pool_client',
            'aws_cognito_user_pool_domain', 'aws_cognito_resource_server'})

    def test_disposable_data(self):
        db = self.r['aws_db_instance']['test']
        self.assertTrue(db['skip_final_snapshot'])
        self.assertFalse(db['deletion_protection'])
        self.assertEqual(db['backup_retention_period'], 0)
        self.assertFalse(db['publicly_accessible'])
        self.assertEqual(self.r['aws_elasticache_replication_group']['test']['snapshot_retention_limit'], 0)

    def test_no_unrestricted_ingress_or_nat(self):
        self.assertNotIn('aws_nat_gateway', self.r)
        for rule in self.r['aws_vpc_security_group_ingress_rule'].values():
            self.assertNotEqual(rule.get('cidr_ipv4'), '0.0.0.0/0')
        self.assertEqual(self.r['aws_vpc_security_group_ingress_rule']['db']['referenced_security_group_id'], '${aws_security_group.core.id}')

    def test_workloads_require_explicit_gate(self):
        variables = read('experiment/variables.tf.json')['variable']
        self.assertFalse(variables['enable_workloads']['default'])
        self.assertFalse(variables['cloud_contract_verified']['default'])
        for task in self.r['aws_ecs_task_definition'].values():
            self.assertIn('terraform_data.contract', task['depends_on'])
        checks = self.r['terraform_data']['contract']['lifecycle']['precondition']
        self.assertTrue(any('cloud_contract_verified' in c['condition'] for c in checks))

    def test_task_role_and_secret_isolation(self):
        self.assertEqual(self.r['aws_iam_role_policy']['bedrock']['role'], '${aws_iam_role.inference_task.id}')
        self.assertNotIn('secrets', self.main['locals']['inference_containers'][0])
        self.assertEqual(self.r['aws_iam_role_policy']['core_secrets']['role'], '${aws_iam_role.core_execution.id}')

    def test_cloudwatch_permission_is_opt_in_and_namespace_limited(self):
        variables = read('experiment/variables.tf.json')['variable']
        self.assertFalse(variables['enable_cloudwatch_metrics']['default'])
        policy = self.r['aws_iam_role_policy']['core_cloudwatch']
        self.assertEqual(policy['role'], '${aws_iam_role.core_task.id}')
        self.assertEqual(policy['count'], '${var.enable_cloudwatch_metrics ? 1 : 0}')
        self.assertIn('Action=["cloudwatch:PutMetricData"]', policy['policy'])
        self.assertIn('StringEquals={"cloudwatch:namespace"=local.cloudwatch_namespace', policy['policy'])
        self.assertIn('"aws:RequestedRegion"="ap-northeast-2"', policy['policy'])
        self.assertNotIn('StringEqualsIfExists', policy['policy'])
        self.assertIn('aws_iam_role_policy.core_cloudwatch',
                      self.r['aws_ecs_service']['core']['depends_on'])

    def test_cloudwatch_export_keeps_personal_runtime_boundaries(self):
        env = self.main['locals']['api_environment']
        self.assertEqual(env['SLASH_OBSERVABILITY_CLOUDWATCH_ENABLED'],
                         '${tostring(var.enable_cloudwatch_metrics)}')
        self.assertEqual(self.main['locals']['cloudwatch_namespace'], 'LambdaOps/Slash')
        self.assertEqual(env['SLASH_OBSERVABILITY_CLOUDWATCH_NAMESPACE'], '${local.cloudwatch_namespace}')
        self.assertEqual(env['SLASH_OBSERVABILITY_CLOUDWATCH_SERVICE'], 'slash-api')
        self.assertEqual(env['SLASH_OBSERVABILITY_CLOUDWATCH_ENVIRONMENT'], 'dev')
        self.assertEqual(env['SLASH_OBSERVABILITY_CLOUDWATCH_PUBLISHINTERVALMS'], '60000')
        self.assertEqual(env['SLASH_OBSERVABILITY_QUERYMETRICS_ENABLED'], 'true')
        self.assertEqual(env['SLASH_OBSERVABILITY_FAULTS_ENABLED'], 'false')
        self.assertEqual(env['SLASH_AUTH_LOCALDEVTOKEN_ENABLED'], 'false')
        self.assertEqual(env['SPRING_PROFILES_ACTIVE'], 'personal')
        self.assertIn('merge(var.api_environment, local.api_environment)',
                      self.main['locals']['api_container']['environment'])

    def test_account_is_pinned_in_both_roots(self):
        for root in ['foundation', 'experiment']:
            self.assertEqual(read(root + '/versions.tf.json')['provider']['aws']['allowed_account_ids'], ['${var.account_id}'])

class MonitoringGuardrails(unittest.TestCase):
    def setUp(self):
        self.main = read('experiment/main.tf.json')
        self.r = self.main['resource']

    def test_baseline_default_denies_unfinished_routes(self):
        self.assertEqual(read('experiment/variables.tf.json')['variable']['experiment_mode']['default'], 'api-baseline')
        self.assertEqual(self.r['aws_lb_listener']['http']['default_action']['fixed_response']['status_code'], '404')
        self.assertNotIn('full_api', self.r['aws_lb_listener_rule'])
        self.assertEqual(self.r['aws_lb_listener_rule']['baseline_me']['condition'][0]['path_pattern']['values'], ['/${var.api_stage_name}/api/v1/me'])

    def test_metrics_port_is_internal_and_prometheus_not_exposed(self):
        metrics = self.r['aws_vpc_security_group_ingress_rule']['metrics']
        self.assertEqual(metrics['from_port'], 9091)
        self.assertEqual(metrics['referenced_security_group_id'], '${aws_security_group.monitoring.id}')
        for rule in self.r['aws_vpc_security_group_ingress_rule'].values():
            if rule.get('from_port') in [9090, 9091, 3000]:
                self.assertNotIn('cidr_ipv4', rule)
        prom = self.main['locals']['monitoring_containers'][0]
        self.assertNotIn('portMappings', prom)
        arguments = json.loads((ROOT.parents[1] / 'observability/personal/prometheus/arguments.json').read_text())
        self.assertIn('--web.listen-address=127.0.0.1:9090', arguments)

    def test_grafana_secret_is_not_a_literal_environment_value(self):
        grafana = self.main['locals']['monitoring_containers'][1]
        self.assertNotIn('GF_SECURITY_ADMIN_PASSWORD', [e['name'] for e in grafana['environment']])
        self.assertEqual(grafana['secrets'][0]['name'], 'GF_SECURITY_ADMIN_PASSWORD')

if __name__ == '__main__':
    unittest.main()
