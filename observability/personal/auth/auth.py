#!/usr/bin/env python3
"""Explicit local Cognito PKCE login and read-only LambdaOps API verification."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import webbrowser

CALLBACK = 'http://localhost:8765/callback'
READ_SCOPE = 'lambdaops/incidents.read'
ACCOUNT = '642935793048'
REGION = 'ap-northeast-2'
MAX_RESPONSE = 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_config(config):
    if config.get('account_id') != ACCOUNT or config.get('region') != REGION:
        raise ValueError('Use the approved account and Seoul region.')
    if not re.fullmatch(r'https://cognito-idp[.]ap-northeast-2[.]amazonaws[.]com/ap-northeast-2_[A-Za-z0-9]+', config.get('issuer_uri', '')):
        raise ValueError('Expected the deployed Seoul Cognito issuer.')
    if not re.fullmatch(r'https://[a-z0-9-]+[.]auth[.]ap-northeast-2[.]amazoncognito[.]com', config.get('authorization_base_url', '')):
        raise ValueError('Expected the Cognito-provided Seoul login domain.')
    if not re.fullmatch(r'[a-z0-9]{1,128}', config.get('client_id', '')):
        raise ValueError('Expected the deployed operator client ID.')
    if config.get('redirect_uri') != CALLBACK or config.get('read_scope') != READ_SCOPE:
        raise ValueError('Callback or read scope does not match the reviewed contract.')
    return config


def challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')


def authorization_url(config, verifier, state, with_read_scope=True):
    validate_config(config)
    scopes = 'openid ' + READ_SCOPE if with_read_scope else 'openid'
    return config['authorization_base_url'] + '/oauth2/authorize?' + urlencode({
        'response_type': 'code', 'client_id': config['client_id'], 'redirect_uri': CALLBACK,
        'scope': scopes, 'state': state, 'code_challenge_method': 'S256',
        'code_challenge': challenge(verifier)})


def parse_callback(path, expected_state):
    parsed = urlsplit(path)
    if parsed.path != '/callback' or parsed.scheme or parsed.netloc or len(path) > 8192:
        raise ValueError('Unexpected callback path.')
    params = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=10)
    state = params.get('state', [])
    if len(state) != 1 or not state[0].isascii() or not secrets.compare_digest(state[0], expected_state):
        raise ValueError('Callback state mismatch.')
    if 'error' in params:
        return None
    code = params.get('code', [])
    if len(code) != 1 or not code[0] or len(code[0]) > 4096:
        raise ValueError('Expected exactly one authorization code.')
    return code[0]


def receive_code(url, state, open_browser=False, timeout_seconds=300):
    result = {}
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(2)
        def log_message(self, *args):
            pass
        def do_GET(self):
            try:
                if self.headers.get('Host') != 'localhost:8765':
                    raise ValueError('Unexpected callback host.')
                code = parse_callback(self.path, state)
                result['code'] = code
                status, message = 200, b'Login response received. Return to the terminal.'
            except ValueError:
                status, message = 400, b'Invalid login response.'
            self.send_response(status)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(message)))
            self.end_headers()
            self.wfile.write(message)
    with HTTPServer(('127.0.0.1', 8765), Handler) as server:
        server.timeout = 1
        print('Open this Cognito login URL in your browser (password stays in Cognito):\n' + url)
        if open_browser:
            webbrowser.open(url)
        deadline = time.monotonic() + timeout_seconds
        while 'code' not in result and time.monotonic() < deadline:
            server.handle_request()
    if 'code' not in result:
        raise TimeoutError('Login timed out after five minutes.')
    if result['code'] is None:
        raise ValueError('Cognito did not complete login.')
    return result['code']


def http_json(request):
    opener = build_opener(NoRedirect())
    try:
        response = opener.open(request, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        body = response.read(MAX_RESPONSE + 1)
        if len(body) > MAX_RESPONSE:
            raise ValueError('Response exceeds the size limit.')
        status = response.code
        # Negative probes need only the status; do not parse/reflect error bodies.
        return status, json.loads(body) if status == 200 else None


def access_claims(token, config, with_read_scope=True, now=None):
    if not isinstance(token, str) or len(token) > 16384 or any(c.isspace() for c in token):
        raise ValueError('Invalid access token.')
    try:
        parts = token.split('.')
        if len(parts) != 3 or not all(parts):
            raise ValueError
        def decode(part):
            return json.loads(base64.b64decode(part + '=' * (-len(part) % 4), altchars=b'-_', validate=True))
        header, claims = decode(parts[0]), decode(parts[1])
        exp = claims['exp']
        if (header.get('alg') != 'RS256' or claims.get('token_use') != 'access'
                or claims.get('iss') != config['issuer_uri'] or claims.get('client_id') != config['client_id']
                or isinstance(exp, bool) or not isinstance(exp, (int, float)) or not math.isfinite(exp)
                or exp <= (time.time() if now is None else now) + 90):
            raise ValueError
        scope = claims.get('scope', '')
        if not isinstance(scope, str) or ((READ_SCOPE in scope.split()) != with_read_scope):
            raise ValueError
        return claims
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError):
        raise ValueError('Token is not the expected operator access token with sufficient lifetime and scope.') from None


def exchange_code(config, code, verifier, with_read_scope=True, send=http_json):
    body = urlencode({'grant_type': 'authorization_code', 'client_id': config['client_id'],
                      'redirect_uri': CALLBACK, 'code': code, 'code_verifier': verifier}).encode('ascii')
    request = Request(config['authorization_base_url'] + '/oauth2/token', data=body,
                      headers={'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
    status, response = send(request)
    if status != 200 or not isinstance(response, dict) or response.get('token_type', '').lower() != 'bearer':
        raise ValueError('Cognito token exchange failed.')
    token = response.get('access_token')
    access_claims(token, config, with_read_scope)
    return token


def save_private(path, contents):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        stream.write(contents)


def load_private(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > 16384):
            raise ValueError('Token file must be owner-only and at most 16 KiB.')
        with os.fdopen(descriptor, 'r') as stream:
            descriptor = None
            return stream.read().strip()
    finally:
        if descriptor is not None:
            os.close(descriptor)


def api_base(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not re.fullmatch(r'[a-z0-9]+[.]execute-api[.]ap-northeast-2[.]amazonaws[.]com', parsed.hostname or '')
            or parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not re.fullmatch(r'(?:/[A-Za-z0-9_-]+)?/?', parsed.path)):
        raise ValueError('Expected a Seoul API Gateway HTTPS URL with at most one stage.')
    return value.rstrip('/')


def detail_matches_request(body, requested_id):
    """DSQL can return a canonical Incident for a previously issued fixed ID."""
    if not isinstance(body, dict) or body.get('requestedIncidentId') != requested_id:
        return False
    canonical_id = body.get('incidentId')
    return (isinstance(canonical_id, str)
            and re.fullmatch(r'inc_[0-9a-f]{32}', canonical_id) is not None
            and body.get('redirected') is (canonical_id != requested_id)
            and isinstance(body.get('stateHistory'), list))


def probe(config, base, token, no_scope_token, incident_id=None, send=http_json):
    base = api_base(base)
    access_claims(token, config, True)
    access_claims(no_scope_token, config, False)
    paths = ['/incidents']
    if incident_id:
        if not re.fullmatch(r'inc_[0-9a-f]{32}', incident_id):
            raise ValueError('Invalid Incident ID.')
        paths.append('/incidents/' + incident_id)
    checks = []
    for path in paths:
        for kind, credential, expected in [('read_scope', token, 200), ('missing_token', None, 401), ('no_read_scope', no_scope_token, 403)]:
            headers = {'Accept': 'application/json'}
            if credential:
                headers['Authorization'] = 'Bearer ' + credential
            status, body = send(Request(base + path, headers=headers, method='GET'))
            shape = status != 200 or (
                    isinstance(body, dict) and isinstance(body.get('items'), list)
                    if path == '/incidents' else detail_matches_request(body, incident_id))
            checks.append({'route': 'list' if path == '/incidents' else 'detail', 'case': kind,
                           'expected_status': expected, 'actual_status': status,
                           'passed': status == expected and shape})
    return {'at': datetime.now(timezone.utc).isoformat(), 'checks': checks,
            'all_passed': all(item['passed'] for item in checks), 'detail_checked': bool(incident_id)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True, help='foundation output -json lambdaops_auth')
    commands = parser.add_subparsers(dest='command', required=True)
    login = commands.add_parser('login')
    login.add_argument('--token-file', type=Path, required=True, help='New file outside the repository, mode 600')
    login.add_argument('--without-read-scope', action='store_true', help='Request openid only for a genuine 403 test')
    login.add_argument('--open-browser', action='store_true')
    check = commands.add_parser('probe')
    check.add_argument('--api-url', required=True)
    check.add_argument('--token-file', type=Path, required=True)
    check.add_argument('--no-scope-token-file', type=Path, required=True)
    check.add_argument('--incident-id')
    check.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    try:
        config = validate_config(json.loads(args.config.read_text()))
        if args.command == 'login':
            if args.token_file.exists():
                raise ValueError('Choose a new token file.')
            verifier, state = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
            code = receive_code(authorization_url(config, verifier, state, not args.without_read_scope), state, args.open_browser)
            token = exchange_code(config, code, verifier, not args.without_read_scope)
            save_private(args.token_file, token + '\n')
            print('Access token saved privately. ID/refresh tokens were not saved. No API has been called.')
            return 0
        if os.path.lexists(args.result):
            raise ValueError('Choose a new result file.')
        result = probe(config, args.api_url, load_private(args.token_file),
                       load_private(args.no_scope_token_file), args.incident_id)
        save_private(args.result, json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2))
        return 0 if result['all_passed'] else 1
    except KeyboardInterrupt:
        print('Cancelled; no further requests will be made.', file=sys.stderr)
        return 130
    except Exception:
        # Never print exception text containing a token, code, response or user data.
        print('Authentication check failed. Check configuration, token lifetime, file permissions and the documented prerequisites.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
