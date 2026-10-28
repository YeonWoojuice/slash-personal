import base64
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

spec = importlib.util.spec_from_file_location('operator_auth', Path(__file__).with_name('auth.py'))
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)


def config():
    return {'account_id': '642935793048', 'region': 'ap-northeast-2',
            'issuer_uri': 'https://cognito-idp.ap-northeast-2.amazonaws.com/ap-northeast-2_Test123',
            'client_id': 'operator123', 'authorization_base_url': 'https://slash-lab.auth.ap-northeast-2.amazoncognito.com',
            'redirect_uri': auth.CALLBACK, 'read_scope': auth.READ_SCOPE}


def token(read=True, **overrides):
    claims = {'iss': config()['issuer_uri'], 'client_id': 'operator123', 'token_use': 'access',
              'scope': 'openid ' + auth.READ_SCOPE if read else 'openid', 'exp': time.time() + 3600}
    claims.update(overrides)
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b'=').decode()
    return encode({'alg': 'RS256'}) + '.' + encode(claims) + '.fixture-signature'


class Contract(unittest.TestCase):
    def test_config_rejects_arbitrary_hosts_accounts_and_callbacks(self):
        for key, value in [('authorization_base_url', 'https://evil.example'), ('account_id', '000000000000'),
                           ('issuer_uri', 'https://example.com/issuer'), ('redirect_uri', 'http://0.0.0.0:8765/callback'),
                           ('read_scope', 'admin'), ('client_id', 'client?foo=bar')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                auth.validate_config({**config(), key: value})

    def test_pkce_uses_rfc_s256_vector_and_no_secret(self):
        verifier = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'
        self.assertEqual(auth.challenge(verifier), 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM')
        url = auth.authorization_url(config(), verifier, 'random-state')
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query['scope'], ['openid lambdaops/incidents.read'])
        self.assertEqual(query['code_challenge_method'], ['S256'])
        self.assertNotIn(verifier, url)
        self.assertNotIn('client_secret', query)
        self.assertEqual(parse_qs(urlsplit(auth.authorization_url(config(), verifier, 's', False)).query)['scope'], ['openid'])

    def test_callback_rejects_wrong_state_duplicate_code_or_path(self):
        self.assertEqual(auth.parse_callback('/callback?state=valid&code=abc', 'valid'), 'abc')
        self.assertIsNone(auth.parse_callback('/callback?state=valid&error=access_denied', 'valid'))
        for path in ['/callback?state=wrong&code=abc', '/callback?state=%C3%A9&code=abc', '/other?state=valid&code=abc',
                     '/callback?state=valid&state=valid&code=abc', '/callback?state=valid&code=a&code=b',
                     'https://evil/callback?state=valid&code=abc']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                auth.parse_callback(path, 'valid')

    def test_token_sanity_is_access_client_issuer_scope_and_lifetime(self):
        self.assertEqual(auth.access_claims(token(), config())['token_use'], 'access')
        self.assertEqual(auth.access_claims(token(False), config(), False)['scope'], 'openid')
        for overrides in [{'token_use': 'id'}, {'client_id': 'slash-web'}, {'iss': 'https://evil.example'},
                          {'scope': 'openid'}, {'exp': time.time() + 1}, {'exp': float('inf')}, {'exp': True}]:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                auth.access_claims(token(**overrides), config())
        with self.assertRaises(ValueError):
            auth.access_claims(token(), config(), False)

    def test_exchange_sends_verifier_and_only_returns_access_token(self):
        captured = []
        access = token()
        def send(request):
            captured.append(request)
            return 200, {'token_type': 'Bearer', 'access_token': access, 'id_token': 'private-id', 'refresh_token': 'private-refresh'}
        self.assertEqual(auth.exchange_code(config(), 'secret-code', 'secret-verifier', send=send), access)
        form = parse_qs(captured[0].data.decode())
        self.assertEqual(form['code_verifier'], ['secret-verifier'])
        self.assertEqual(form['grant_type'], ['authorization_code'])
        self.assertNotIn('client_secret', form)

    def test_redirects_are_not_followed(self):
        self.assertIsNone(auth.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example'))

    def test_private_files_are_exclusive_and_read_refuses_unsafe_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'token'
            auth.save_private(path, 'private-token\n')
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(auth.load_private(path), 'private-token')
            with self.assertRaises(FileExistsError):
                auth.save_private(path, 'overwrite')
            link = Path(directory) / 'link'; link.symlink_to(path)
            with self.assertRaises(OSError):
                auth.load_private(link)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                auth.load_private(path)

    def test_probe_refuses_non_gateway_url_and_nested_paths(self):
        self.assertEqual(auth.api_base('https://abc123.execute-api.ap-northeast-2.amazonaws.com/dev/'),
                         'https://abc123.execute-api.ap-northeast-2.amazonaws.com/dev')
        for value in ['http://abc123.execute-api.ap-northeast-2.amazonaws.com', 'https://evil.example',
                      'https://abc123.execute-api.ap-northeast-2.amazonaws.com.evil.example',
                      'https://abc123.execute-api.ap-northeast-2.amazonaws.com/a/b',
                      'https://abc123.execute-api.ap-northeast-2.amazonaws.com?token=x']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                auth.api_base(value)

    def test_probe_uses_same_client_positive_negative_and_no_sensitive_results(self):
        access, negative = token(), token(False)
        incident = 'inc_' + 'a' * 32
        captured = []
        def send(request):
            captured.append(request)
            authorization = request.get_header('Authorization')
            if authorization is None:
                return 401, None
            if authorization == 'Bearer ' + negative:
                return 403, None
            return 200, {'items': []} if request.full_url.endswith('/incidents') else {
                'requestedIncidentId': incident, 'incidentId': incident,
                'redirected': False, 'stateHistory': [], 'private': 'do-not-record'}
        result = auth.probe(config(), 'https://abc123.execute-api.ap-northeast-2.amazonaws.com', access, negative, incident, send)
        self.assertTrue(result['all_passed']); self.assertTrue(result['detail_checked'])
        self.assertEqual(len(captured), 6)
        self.assertNotIn(access, json.dumps(result)); self.assertNotIn('do-not-record', json.dumps(result))
        self.assertEqual([item['actual_status'] for item in result['checks']], [200, 401, 403, 200, 401, 403])

    def probe_detail(self, body):
        access, negative = token(), token(False)
        def send(request):
            credential = request.get_header('Authorization')
            if credential is None:
                return 401, None
            if credential == 'Bearer ' + negative:
                return 403, None
            return 200, {'items': []} if request.full_url.endswith('/incidents') else body
        return auth.probe(config(), 'https://abc.execute-api.ap-northeast-2.amazonaws.com',
                          access, negative, 'inc_' + 'a' * 32, send)

    def test_probe_accepts_canonical_detail_for_previous_id(self):
        body = {'requestedIncidentId': 'inc_' + 'a' * 32, 'incidentId': 'inc_' + 'b' * 32,
                'redirected': True, 'stateHistory': []}
        result = self.probe_detail(body)
        self.assertTrue(result['all_passed'])
        self.assertEqual(result['checks'][3]['actual_status'], 200)
        self.assertTrue(result['checks'][3]['passed'])
        self.assertNotIn(body['requestedIncidentId'], json.dumps(result))
        self.assertNotIn(body['incidentId'], json.dumps(result))

    def test_probe_rejects_inconsistent_detail_identity_and_redirect(self):
        direct = {'requestedIncidentId': 'inc_' + 'a' * 32, 'incidentId': 'inc_' + 'a' * 32,
                  'redirected': False, 'stateHistory': []}
        invalid = [
            {**direct, 'requestedIncidentId': 'inc_' + 'c' * 32},
            {**direct, 'incidentId': 'not-an-incident'},
            {**direct, 'incidentId': 'inc_' + 'b' * 32},
            {**direct, 'redirected': True},
            {**direct, 'redirected': 0},
            {**direct, 'redirected': 'false'},
            {**direct, 'stateHistory': {}},
        ]
        invalid.extend({k: v for k, v in direct.items() if k != absent}
                       for absent in ['requestedIncidentId', 'incidentId', 'redirected', 'stateHistory'])
        for body in invalid:
            with self.subTest(body=body):
                result = self.probe_detail(body)
                self.assertEqual(result['checks'][3]['actual_status'], 200)
                self.assertFalse(result['checks'][3]['passed'])
                self.assertFalse(result['all_passed'])

    def test_failed_or_empty_detail_is_not_success(self):
        result = auth.probe(config(), 'https://abc.execute-api.ap-northeast-2.amazonaws.com', token(), token(False),
                            'inc_' + 'a' * 32, lambda req: (200, {}))
        self.assertFalse(result['all_passed'])
        self.assertFalse(result['checks'][0]['passed'])

    def test_foundation_keeps_clients_separate_and_exports_matching_scope(self):
        path = Path(os.environ.get('FOUNDATION_CONFIG', str(Path(__file__).resolve().parents[3] / 'infra/personal/foundation/main.tf.json')))
        data = json.loads(path.read_text())
        clients = data['resource']['aws_cognito_user_pool_client']
        self.assertEqual(clients['web']['callback_urls'], ['http://localhost:5173/callback'])
        self.assertEqual(clients['web']['allowed_oauth_scopes'], ['openid', 'email', 'profile'])
        operator = clients['lambdaops_operator']
        self.assertFalse(operator['generate_secret']); self.assertEqual(operator['allowed_oauth_flows'], ['code'])
        self.assertEqual(operator['callback_urls'], [auth.CALLBACK])
        self.assertEqual(operator['user_pool_id'], clients['web']['user_pool_id'])
        value = data['output']['lambdaops_auth']['value']
        m3 = data['output']['lambdaops_m3_auth_tfvars']['value']
        self.assertEqual(m3['jwt_issuer'], value['issuer_uri'])
        self.assertEqual(m3['jwt_audience'], value['client_id'])
        self.assertEqual(m3['read_authorization_scope'], value['read_scope'])
        self.assertEqual(operator['allowed_oauth_scopes'][1], value['read_scope'])

if __name__ == '__main__':
    unittest.main()
