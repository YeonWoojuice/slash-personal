"""Offline checks for the domain-free HTTPS boundary (not an AWS E2E substitute).

The integration URI explicitly includes /stage, as required by the observed
VPC Link V2 request path. The ALB removes it only for the allowed API route;
Grafana keeps it in its root URL.
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
            self.assertEqual(s['Resource'], '${aws_api_gateway_rest_api.test.execution_arn}/*')
        api = self.g['aws_api_gateway_rest_api']['test']
        self.assertNotIn('policy', api)
        policy_resource = self.g['aws_api_gateway_rest_api_policy']['test']
        self.assertEqual(policy_resource['rest_api_id'], '${aws_api_gateway_rest_api.test.id}')
        self.assertEqual(policy_resource['policy'], '${jsonencode(local.ingress_policy)}')
        self.assertIn('aws_api_gateway_rest_api_policy.test',
                      self.g['aws_api_gateway_deployment']['test']['depends_on'])
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
        self.assertEqual(integration['uri'], 'http://${local.api_hostname}/${var.api_stage_name}${local.ingress_paths[each.key]}')

    def test_gateway_backend_paths_reach_allowed_alb_routes(self):
        # A host-only integration URI sent every request to the ALB fallback.
        # Render the complete configured URI before evaluating the ALB boundary.
        # This catches both a missing backend path and a missing explicit stage.
        integration = self.g['aws_api_gateway_integration']['baseline']
        paths = self.ingress['locals']['ingress_paths']
        self.assertEqual(set(paths), {'me_get', 'me_options', 'grafana', 'grafana_proxy'})
        cases = [
            ('me_get', 'GET', None, '/api/v1/me', 'api'),
            ('me_options', 'OPTIONS', None, '/api/v1/me', 'api'),
            ('grafana', 'GET', None, '/m2/grafana', 'grafana'),
            ('grafana_proxy', 'GET', 'public/build/app.js', '/m2/grafana/public/build/app.js', 'grafana'),
            ('grafana_proxy', 'POST', 'login', '/m2/grafana/login', 'grafana'),
            ('grafana_proxy', 'POST', 'api/ds/query', '/m2/grafana/api/ds/query', 'grafana'),
        ]
        for key, method, proxy, expected_path, service in cases:
            with self.subTest(route=key, proxy=proxy):
                uri = self.expand(integration['uri']).replace('${local.api_hostname}', 'example.invalid')
                uri = uri.replace('${local.ingress_paths[each.key]}', paths[key])
                path = uri.removeprefix('http://example.invalid')
                if proxy is not None:
                    self.assertIn('"integration.request.path.proxy"="method.request.path.proxy"',
                                  integration['request_parameters'])
                    self.assertIn('"method.request.path.proxy"=true',
                                  self.g['aws_api_gateway_method']['baseline']['request_parameters'])
                    path = path.replace('{proxy}', proxy)
                self.assertNotIn('{proxy}', path)
                target, forwarded = self.route(method, path + '?probe=a%20b')
                self.assertEqual(target, '${aws_lb_target_group.' + service + '.arn}')
                self.assertEqual(forwarded, expected_path + '?probe=a%20b')

    def test_aws_normalized_defaults_are_explicit(self):
        # Omitting these values produced repeated replacement/update plans
        # after AWS returned normalized service-discovery and gateway values.
        # Preserve DNS-only discovery actually created by the original empty
        # block; ALB/ECS handle application health, not Cloud Map custom health.
        for service in self.r['aws_service_discovery_service'].values():
            self.assertNotIn('health_check_custom_config', service)
            self.assertNotIn('health_check_config', service)
        self.assertEqual(self.g['aws_api_gateway_gateway_response']['cors']['response_templates'],
                         {'application/json': '{"message":$context.error.messageString}'})

    def test_request_correlation_uses_gateway_context_only_on_baseline_get(self):
        # A client-controlled request ID is unsuitable for joining the runner
        # to the application's timing log. The REST-generated extended ID is
        # also returned to the client as x-amz-apigw-id. This verifies the
        # declared mapping, not AWS's runtime header forwarding behavior.
        headers = self.ingress['locals']['ingress_request_headers']
        self.assertEqual(headers, {
            'me_get': {
                'integration.request.header.X-Slash-Gateway-Request-Id':
                    'context.extendedRequestId'
            }
        })
        mapping = self.g['aws_api_gateway_integration']['baseline']['request_parameters']
        self.assertIn('merge(', mapping)
        self.assertIn('lookup(local.ingress_request_headers, each.key, {})', mapping)
        self.assertIn('"integration.request.path.proxy"="method.request.path.proxy"', mapping)
        self.assertEqual(self.g['aws_api_gateway_integration']['baseline']['type'], 'HTTP_PROXY')
        for route in ['me_options', 'grafana', 'grafana_proxy']:
            self.assertEqual(headers.get(route, {}), {})
        # The existing HTTP proxy forwards the bounded probe header normally;
        # it is neither used as the trusted Gateway ID nor placed in metrics.
        self.assertNotIn('method.request.header', json.dumps(headers))
        self.assertEqual(self.main['locals']['api_environment']['SPRING_PROFILES_ACTIVE'], 'personal')
        self.assertEqual(self.main['locals']['api_environment']['PERSONAL_REQUEST_TIMING_ENABLED'], 'true')

    def test_timing_does_not_enable_sensitive_or_account_wide_logging(self):
        self.assertNotIn('access_log_settings', self.g['aws_api_gateway_stage']['test'])
        settings = self.g['aws_api_gateway_method_settings']['test']['settings']
        self.assertEqual(settings['logging_level'], 'OFF')
        self.assertFalse(settings['data_trace_enabled'])
        self.assertFalse(settings['metrics_enabled'])
        self.assertFalse(self.g['aws_api_gateway_stage']['test']['xray_tracing_enabled'])
        self.assertNotIn('aws_api_gateway_account', self.g)
        self.assertNotIn('aws_api_gateway_account', self.r)
        self.assertNotIn('access_logs', self.r['aws_lb']['test'])

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
        # Hash the declared file and resolved inputs, never whole provider objects:
        # AWS fills/normalizes defaults after create, which otherwise forces a
        # redundant deployment on the very next plan.
        for reference in ['filesha256("${path.module}/ingress.tf.json")',
                          'var.name', 'local.ingress_routes', 'local.ingress_paths',
                          'local.ingress_policy', 'local.ingress_gateway_cors',
                          'var.api_stage_name', 'local.monitoring_enabled',
                          'local.api_hostname', 'aws_apigatewayv2_vpc_link.test.id',
                          'aws_lb.test.arn']:
            self.assertIn(reference, trigger)
        self.assertNotIn('aws_api_gateway_method.baseline', trigger)
        self.assertNotIn('aws_api_gateway_integration.baseline', trigger)
        self.assertNotIn('aws_api_gateway_gateway_response.cors', trigger)
        self.assertNotIn('aws_api_gateway_rest_api.test.binary_media_types', trigger)
        self.assertNotIn('timestamp(', trigger)
        self.assertFalse(self.g['aws_api_gateway_stage']['test']['cache_cluster_enabled'])
        self.assertFalse(self.g['aws_api_gateway_method_settings']['test']['settings']['caching_enabled'])
        self.assertEqual(self.g['aws_api_gateway_rest_api']['test']['binary_media_types'], ['*/*'])


if __name__ == '__main__':
    unittest.main()
