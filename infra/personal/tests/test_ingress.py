"""Offline checks for the domain-free HTTPS boundary (not an AWS E2E substitute).

REST private integration includes /stage in the backend path. The ALB removes it
only for the explicitly allowed API route; Grafana keeps it in its root URL.
Sources: AWS API Gateway private-integration and ALB rule-transforms guides.
"""
import fnmatch
import ipaddress
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'experiment'


def read(name):
    return json.loads((ROOT / name).read_text())


class IngressBoundary(unittest.TestCase):
    def setUp(self):
        self.main = read('main.tf.json')
        self.ingress = read('ingress.tf.json')
        self.r = self.main['resource']
        self.g = self.ingress['resource']
        self.stage = 'm2'

    def expand(self, text):
        return text.replace('${var.api_stage_name}', self.stage)

    def route(self, method, path, monitoring=True):
        """Evaluate ordered ALB conditions and the configured rewrite on a URL."""
        for rule in sorted(self.r['aws_lb_listener_rule'].values(), key=lambda r: r['priority']):
            if rule.get('count') and not monitoring:
                continue
            conditions = rule['condition']
            if isinstance(conditions, dict):
                conditions = [conditions]
            matches = []
            for condition in conditions:
                if 'path_pattern' in condition:
                    matches.append(any(fnmatch.fnmatchcase(path.split('?', 1)[0], self.expand(pattern))
                                       for pattern in condition['path_pattern']['values']))
                if 'http_request_method' in condition:
                    matches.append(method in condition['http_request_method']['values'])
            if not all(matches):
                continue
            action = rule['action']
            if action['type'] != 'forward':
                return action['fixed_response']['status_code'], None
            if 'transform' in rule:
                rewrite = rule['transform']['url_rewrite_config']['rewrite']
                replacement = re.sub(r'\$(\d+)', r'\\g<\1>', rewrite['replace'])
                path = re.sub(self.expand(rewrite['regex']), replacement, path)
            return action['target_group_arn'], path
        return self.r['aws_lb_listener']['http']['default_action']['fixed_response']['status_code'], None

    def test_baseline_api_and_preflight_preserve_query_after_stage_removal(self):
        for method in ['GET', 'OPTIONS']:
            target, path = self.route(method, '/m2/api/v1/me?example=a%20b&next=c')
            self.assertEqual(target, '${aws_lb_target_group.api.arn}')
            self.assertEqual(path, '/api/v1/me?example=a%20b&next=c')
        self.stage = 'Review_2'
        self.assertEqual(self.route('GET', '/Review_2/api/v1/me')[1], '/api/v1/me')

    def test_nonbaseline_paths_and_writes_fail_closed(self):
        for path in ['/m2/api/v1/jobs', '/m2/internal/jobs', '/m2/actuator/prometheus',
                     '/m2/api/v1/health/dependencies', '/m2/ws/user', '/api/v1/me',
                     '/other/api/v1/me', '/m2/api/v1/me/extra', '/m2/api/v1/me-too']:
            with self.subTest(path=path):
                self.assertEqual(self.route('GET', path), ('404', None))
        for method in ['POST', 'PUT', 'PATCH', 'DELETE']:
            self.assertEqual(self.route(method, '/m2/api/v1/me'), ('404', None))
        self.assertNotIn('full_api', self.r['aws_lb_listener_rule'])
        checks = self.r['terraform_data']['contract']['lifecycle']['precondition']
        self.assertTrue(any(c['condition'] == '${!local.full_mode}' for c in checks))

    def test_grafana_login_assets_and_queries_keep_stage_prefix(self):
        for method, path in [('GET', '/m2/grafana'), ('GET', '/m2/grafana/'),
                             ('GET', '/m2/grafana/public/build/app.js'),
                             ('POST', '/m2/grafana/login'),
                             ('POST', '/m2/grafana/api/ds/query?ds_type=prometheus')]:
            target, forwarded = self.route(method, path)
            self.assertEqual(target, '${aws_lb_target_group.grafana.arn}')
            self.assertEqual(forwarded, path)
        self.assertEqual(self.route('GET', '/m2/grafana/', monitoring=False), ('404', None))
        env = {v['name']: v['value'] for v in self.main['locals']['monitoring_containers'][1]['environment']}
        self.assertEqual(env['GF_SERVER_ROOT_URL'], '${local.api_base_url}/grafana/')
        self.assertEqual(env['GF_SERVER_DOMAIN'], '${local.api_hostname}')
        self.assertEqual(env['GF_SERVER_SERVE_FROM_SUB_PATH'], 'true')
        self.assertEqual(env['GF_SECURITY_COOKIE_SECURE'], 'true')
        self.assertEqual(env['GF_LIVE_MAX_CONNECTIONS'], '0')
        self.assertEqual(self.expand(self.r['aws_lb_target_group']['grafana']['health_check']['path']),
                         '/m2/grafana/api/health')

    def test_no_top_level_catchall_gateway_route(self):
        resources = self.g['aws_api_gateway_resource']
        self.assertEqual(set(resources), {'api', 'v1', 'me', 'grafana', 'grafana_proxy'})
        self.assertEqual(resources['grafana_proxy']['parent_id'], '${aws_api_gateway_resource.grafana[0].id}')
        self.assertEqual(resources['grafana_proxy']['path_part'], '{proxy+}')
        self.assertEqual(resources['me']['parent_id'], '${aws_api_gateway_resource.v1.id}')
        routes = self.ingress['locals']['ingress_routes']
        self.assertIn('http_method="GET"', routes)
        self.assertIn('http_method="OPTIONS"', routes)
        self.assertNotIn('http_method="POST"', routes)

    def test_source_ip_policy_has_allowlist_and_explicit_deny(self):
        policy = self.ingress['locals']['ingress_policy']
        statements = policy['Statement']
        self.assertEqual({s['Effect'] for s in statements}, {'Allow', 'Deny'})
        for s in statements:
            operator = 'IpAddress' if s['Effect'] == 'Allow' else 'NotIpAddress'
            self.assertEqual(s['Condition'], {operator: {'aws:SourceIp': '${sort(tolist(var.allowed_cidrs))}'}})
            self.assertEqual(s['Action'], 'execute-api:Invoke')
            self.assertEqual(s['Resource'], 'execute-api:/*')
        api = self.g['aws_api_gateway_rest_api']['test']
        self.assertEqual(api['policy'], '${jsonencode(local.ingress_policy)}')
        self.assertEqual(api['endpoint_configuration'], {'types': ['REGIONAL'], 'ip_address_type': 'ipv4'})
        # CIDRs are evaluated against the network source, never a client-provided header.
        allowed = [ipaddress.ip_network('203.0.113.10/32')]
        self.assertTrue(any(ipaddress.ip_address('203.0.113.10') in c for c in allowed))
        self.assertFalse(any(ipaddress.ip_address('203.0.113.11') in c for c in allowed))
        self.assertNotIn('X-Forwarded-For', json.dumps(policy))

    def test_internal_alb_only_accepts_dedicated_vpc_link_security_group(self):
        alb = self.r['aws_lb']['test']
        self.assertTrue(alb['internal'])
        self.assertEqual(alb['subnets'], '${aws_subnet.data[*].id}')
        ingress = [r for r in self.r['aws_vpc_security_group_ingress_rule'].values()
                   if r['security_group_id'] == '${aws_security_group.alb.id}']
        self.assertEqual(len(ingress), 1)
        self.assertEqual(ingress[0]['referenced_security_group_id'], '${aws_security_group.vpc_link.id}')
        self.assertEqual(ingress[0]['from_port'], 80)
        self.assertNotIn('cidr_ipv4', ingress[0])
        link = self.g['aws_apigatewayv2_vpc_link']['test']
        self.assertEqual(link['security_group_ids'], ['${aws_security_group.vpc_link.id}'])
        self.assertEqual(link['subnet_ids'], '${aws_subnet.data[*].id}')
        outbound = self.r['aws_vpc_security_group_egress_rule']['vpc_link_to_alb']
        self.assertEqual(outbound['referenced_security_group_id'], '${aws_security_group.alb.id}')
        self.assertEqual(outbound['to_port'], 80)
        self.assertNotIn('aws_nat_gateway', self.r)
        integration = self.g['aws_api_gateway_integration']['baseline']
        self.assertEqual(integration['connection_id'], '${aws_apigatewayv2_vpc_link.test.id}')
        self.assertEqual(integration['integration_target'], '${aws_lb.test.arn}')
        self.assertEqual(integration['uri'], 'http://${local.api_hostname}')

    def test_cors_and_forwarded_headers_do_not_weaken_authentication(self):
        env = self.main['locals']['api_environment']
        self.assertEqual(env['CORS_ALLOWED_ORIGINS'], '${var.cors_allowed_origin}')
        self.assertEqual(env['SERVER_FORWARD_HEADERS_STRATEGY'], 'none')
        self.assertEqual(env['TRUSTED_PROXY_HOPS'], '0')
        self.assertEqual(env['SLASH_AUTH_LOCALDEVTOKEN_ENABLED'], 'false')
        self.assertEqual(env['SPRING_SECURITY_OAUTH2_RESOURCESERVER_JWT_ISSUERURI'], '${var.cognito.issuer_uri}')
        self.assertEqual(self.ingress['locals']['ingress_gateway_cors']['gatewayresponse.header.Access-Control-Allow-Origin'],
                         "'${var.cors_allowed_origin}'")
        self.assertNotIn('authorizer_id', self.g['aws_api_gateway_method']['baseline'])

    def test_no_domain_certificate_and_simple_stage_segment(self):
        variables = read('variables.tf.json')['variable']
        self.assertNotIn('certificate_arn', variables)
        self.assertNotIn('api_hostname', variables)
        condition = variables['api_stage_name']['validation']['condition']
        pattern = re.search(r'regex\("([^"]+)"', condition).group(1)
        for valid in ['m2', 'Review_2', 'test-3']:
            self.assertRegex(valid, pattern)
        for invalid in ['test/path', '', '../me', 'a.b', 'x'*33]:
            self.assertIsNone(re.fullmatch(pattern, invalid))
        self.assertEqual(self.main['locals']['api_base_url'], 'https://${local.api_hostname}/${var.api_stage_name}')
        self.assertEqual(self.main['data']['aws_availability_zones']['available']['filter'],
                         [{'name': 'zone-id', 'values': ['apne2-az1', 'apne2-az2', 'apne2-az3']}])

    def test_deployment_tracks_config_and_caches_are_off(self):
        deployment = self.g['aws_api_gateway_deployment']['test']
        trigger = deployment['triggers']['configuration']
        for reference in ['local.ingress_routes', 'aws_api_gateway_method.baseline',
                          'aws_api_gateway_integration.baseline', 'local.ingress_policy',
                          'local.ingress_gateway_cors', 'binary_media_types']:
            self.assertIn(reference, trigger)
        self.assertNotIn('timestamp(', trigger)
        self.assertFalse(self.g['aws_api_gateway_stage']['test']['cache_cluster_enabled'])
        self.assertFalse(self.g['aws_api_gateway_method_settings']['test']['settings']['caching_enabled'])
        self.assertEqual(self.g['aws_api_gateway_rest_api']['test']['binary_media_types'], ['*/*'])


if __name__ == '__main__':
    unittest.main()
