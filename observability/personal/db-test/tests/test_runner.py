"""Local Docker tests; all database traffic stays on a disposable internal network.

Build the db-test image before running. No AWS credentials or AWS requests.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import unittest

IMAGE = os.environ.get('DB_TEST_IMAGE', 'slash-personal-db-test:preparation')
SERVER_IMAGE = os.environ.get('DB_TEST_SERVER_IMAGE', 'postgres:18')
CLIENT_MAJOR = os.environ.get('DB_TEST_CLIENT_MAJOR', '18')
HOST = 'synthetic.test.ap-northeast-2.rds.amazonaws.com'
WRONG_HOST = 'wrong.test.ap-northeast-2.rds.amazonaws.com'


def command(*args, check=True, **kw):
    return subprocess.run(args, text=True, capture_output=True, check=check, **kw)


class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='slash-db-runner-test-')
        cls.path = Path(cls.temp.name)
        cls.name = 'slash-db-runner-' + secrets.token_hex(4)
        cls.network = cls.name + '-network'
        cls.resources = []
        cls.addClassCleanup(cls.cleanup)
        cls.password = secrets.token_urlsafe(20)
        cls.server_env = cls.path / 'server.env'
        cls.server_env.write_text('POSTGRES_USER=slashadmin\nPOSTGRES_DB=slash\nPOSTGRES_PASSWORD=' + cls.password + '\n')
        cls.server_env.chmod(0o600)
        cls.client_env = cls.path / 'client.env'
        cls.client_env.write_text('CONFIRM_DISPOSABLE=slash-m2\nPGDATABASE=slash\nPGHOST=' + HOST + '\nPGUSER=slashadmin\nPGPASSWORD=' + cls.password + '\nDB_TEST_START_DELAY_SECONDS=0\n')
        cls.client_env.chmod(0o600)
        command('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                '-subj', '/CN=' + HOST, '-addext', 'subjectAltName=DNS:' + HOST,
                '-keyout', str(cls.path/'server.key'), '-out', str(cls.path/'server.crt'))
        command('docker', 'network', 'create', '--internal', cls.network)
        cls.resources.append(('network', cls.network))
        command('docker', 'run', '-d', '--name', cls.name, '--network', cls.network,
                '--network-alias', HOST, '--network-alias', WRONG_HOST, '--env-file', str(cls.server_env),
                '-v', str(cls.path)+':/certs:ro', '--entrypoint', '/bin/sh', SERVER_IMAGE, '-c',
                'cp /certs/server.key /tmp/server.key && cp /certs/server.crt /tmp/server.crt && chown postgres:postgres /tmp/server.key && chmod 0600 /tmp/server.key && exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/tmp/server.crt -c ssl_key_file=/tmp/server.key')
        cls.resources.append(('container', cls.name))
        deadline = time.monotonic()+45
        while time.monotonic() < deadline:
            result = cls.sql('SHOW ssl', check=False)
            if result.returncode == 0 and result.stdout.strip() == 'on':
                break
            time.sleep(.2)
        else:
            raise AssertionError('Temporary PostgreSQL failed to start')
        cls.sql("CREATE TABLE public.users(id int PRIMARY KEY, name text, public_id uuid, cognito_sub text, email text, display_name text, status text, timezone text, created_at timestamptz, updated_at timestamptz); INSERT INTO public.users(id,name,cognito_sub) VALUES(1,'synthetic','synthetic')")
        cls.sql("CREATE ROLE slashreader LOGIN PASSWORD '" + cls.password + "'; GRANT SELECT ON public.users TO slashreader")
        cls.app = cls.name + '-app'
        command('docker', 'run', '-d', '--name', cls.app, '--network', cls.network,
                '--env-file', str(cls.client_env), '-e', 'PGAPPNAME=PostgreSQL JDBC Driver',
                '-e', 'PGSSLMODE=verify-full', '-e', 'PGSSLROOTCERT=/certs/server.crt',
                '-v', str(cls.path)+':/certs:ro', '--entrypoint', 'sleep', 'postgres:16', '600')
        cls.resources.append(('container', cls.app))
        inspect = json.loads(command('docker', 'inspect', cls.app).stdout)[0]
        cls.app_ip = inspect['NetworkSettings']['Networks'][cls.network]['IPAddress']
        # PostgreSQL 16 psql extended-query mode reproduces JDBC's $1 query text.
        query = ('select "public"."users"."id", "public"."users"."public_id", "public"."users"."cognito_sub", '
                 '"public"."users"."email", "public"."users"."display_name", "public"."users"."status", '
                 '"public"."users"."timezone", "public"."users"."created_at", "public"."users"."updated_at" '
                 'from "public"."users" where "public"."users"."cognito_sub" = $1')
        (cls.path / 'me.sql').write_text('\\set ON_ERROR_STOP on\n' + query + '\n\\bind synthetic\n\\g\n')
        (cls.path / 'other.sql').write_text('\\set ON_ERROR_STOP on\nSELECT name FROM public.users;\n')

    @classmethod
    def cleanup(cls):
        for kind, name in reversed(cls.resources):
            command('docker', 'rm' if kind == 'container' else 'network',
                    *(['-fv', name] if kind == 'container' else ['rm', name]), check=False)
        cls.temp.cleanup()

    @classmethod
    def sql(cls, sql, check=True):
        return command('docker', 'exec', cls.name, 'psql', '-X', '-U', 'slashadmin', '-d', 'slash', '-Atc', sql, check=check)

    def run_command(self, overrides=None, name=None):
        args = ['docker', 'run', '--rm', '--read-only', '--cap-drop=ALL',
                '--security-opt=no-new-privileges', '--network', self.network, '--env-file', str(self.client_env),
                '-v', str(self.path/'server.crt')+':/opt/db-test/rds-ap-northeast-2-bundle.crt:ro']
        if name:
            args += ['--name', name]
        for key, value in (overrides or {}).items():
            args += ['-e', key+'='+value]
        return args+[IMAGE]

    def wait_for_lock(self, proc):
        deadline = time.monotonic()+8
        while time.monotonic()<deadline:
            result = self.sql("SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a USING(pid) WHERE a.application_name IN ('slash-m2-db-delay','slash-m2-cancel-controller') AND l.mode='AccessExclusiveLock' AND l.granted")
            if result.stdout.strip() == '1':
                return
            if proc.poll() is not None:
                out, err = proc.communicate()
                self.fail('Runner ended before acquiring lock: '+out+err)
            time.sleep(.03)
        self.fail('No delay lock acquired')

    def app_query(self, filename='me.sql', appname='PostgreSQL JDBC Driver', username='slashadmin'):
        return subprocess.Popen(['docker', 'exec', '-e', 'PGAPPNAME=' + appname, '-e', 'PGUSER=' + username, self.app,
                                 'psql', '-X', '--no-password', '-Atf', '/certs/' + filename],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def cancel_run(self, overrides=None):
        return subprocess.Popen(self.run_command({'DB_TEST_MODE': 'cancel-one',
            'DB_TEST_EXPECTED_APP_IP': self.app_ip, **(overrides or {})}),
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def finish(self, proc):
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=10)

    def assert_no_controller(self):
        self.assertEqual(self.sql("SELECT count(*) FROM pg_stat_activity WHERE application_name='slash-m2-cancel-controller'").stdout.strip(), '0')
        self.assertEqual(self.sql('SELECT count(*) FROM public.users').stdout.strip(), '1')

    def test_exact_blocked_me_query_cancelled_once_and_lock_released(self):
        controller = self.cancel_run()
        app = None
        try:
            self.wait_for_lock(controller)
            app = self.app_query()
            app_out, app_err = app.communicate(timeout=10)
            stdout, stderr = controller.communicate(timeout=10)
            self.assertEqual(controller.returncode, 0, stdout + stderr)
            self.assertNotEqual(app.returncode, 0, app_out)
            self.assertIn('canceling statement due to user request', app_err)
            self.assertEqual(stdout.count('cancel_signalled'), 1)
            self.assertNotIn(self.password, stdout + stderr)
            self.assert_no_controller()
        finally:
            self.finish(controller)
            if app: self.finish(app)

    def test_wrong_query_shape_is_not_cancelled(self):
        controller = self.cancel_run()
        app = None
        try:
            self.wait_for_lock(controller)
            app = self.app_query('other.sql')
            stdout, stderr = controller.communicate(timeout=10)
            app_out, app_err = app.communicate(timeout=10)
            self.assertNotEqual(controller.returncode, 0, stderr)
            self.assertIn('cancel_refused_or_failed', stdout)
            self.assertEqual(app.returncode, 0, app_err)
            self.assertEqual(app_out.strip(), 'synthetic')
            self.assert_no_controller()
        finally:
            self.finish(controller)
            if app: self.finish(app)

    def test_wrong_ip_application_name_or_role_is_not_cancelled(self):
        for kind in ['ip', 'appname', 'role']:
            controller = self.cancel_run({'DB_TEST_EXPECTED_APP_IP': '10.254.254.254'} if kind == 'ip' else {})
            app = None
            try:
                self.wait_for_lock(controller)
                app = self.app_query(appname='other-client' if kind == 'appname' else 'PostgreSQL JDBC Driver',
                                     username='slashreader' if kind == 'role' else 'slashadmin')
                stdout, stderr = controller.communicate(timeout=12)
                _, app_err = app.communicate(timeout=10)
                self.assertNotEqual(controller.returncode, 0, stderr)
                self.assertIn('cancel_refused_or_failed', stdout)
                self.assertEqual(app.returncode, 0, app_err)
                self.assert_no_controller()
            finally:
                self.finish(controller)
                if app: self.finish(app)

    def test_multiple_blocked_app_queries_are_not_cancelled(self):
        controller = self.cancel_run()
        apps = []
        try:
            self.wait_for_lock(controller)
            apps = [self.app_query(), self.app_query()]
            stdout, stderr = controller.communicate(timeout=10)
            self.assertNotEqual(controller.returncode, 0, stderr)
            self.assertIn('cancel_refused_or_failed', stdout)
            for app in apps:
                _, app_err = app.communicate(timeout=10)
                self.assertEqual(app.returncode, 0, app_err)
            self.assert_no_controller()
        finally:
            self.finish(controller)
            for app in apps: self.finish(app)

    def test_zero_matching_queries_refuses_without_leaving_lock(self):
        controller = self.cancel_run()
        try:
            stdout, stderr = controller.communicate(timeout=12)
            self.assertNotEqual(controller.returncode, 0, stderr)
            self.assertIn('cancel_refused_or_failed', stdout)
            self.assert_no_controller()
        finally:
            self.finish(controller)

    def test_cancel_mode_requires_explicit_single_private_target(self):
        for overrides in [{'DB_TEST_MODE': 'anything'}, {'DB_TEST_MODE': 'cancel-one'},
                          {'DB_TEST_MODE': 'cancel-one', 'DB_TEST_EXPECTED_APP_IP': '8.8.8.8'},
                          {'DB_TEST_MODE': 'cancel-one', 'DB_TEST_EXPECTED_APP_IP': self.app_ip, 'DB_TEST_PULSES': '2'}]:
            with self.subTest(overrides=overrides):
                result = command(*self.run_command(overrides), check=False)
                self.assertEqual(result.returncode, 64, result.stderr)
                self.assertNotIn('pulse_start', result.stdout)

    def test_invalid_target_or_confirmation_never_starts_pulse(self):
        for overrides in [{'CONFIRM_DISPOSABLE':''}, {'PGDATABASE':'postgres'},
                          {'PGHOST':'example.dsql.ap-northeast-2.on.aws'},
                          {'PGHOST':'localhost'}, {'PGPORT':'5433'}, {'PGSSLMODE':'disable'}]:
            with self.subTest(overrides=overrides):
                result = command(*self.run_command(overrides), check=False)
                self.assertEqual(result.returncode, 64, result.stderr)
                self.assertNotIn('pulse_start', result.stdout)
                self.assertNotIn(self.password, result.stdout+result.stderr)
        # Arguments must never turn the fixed runner into an arbitrary SQL client.
        result = command(*self.run_command(), '--command=SELECT pg_sleep(600)', check=False)
        self.assertEqual(result.returncode, 64, result.stderr)
        self.assertNotIn('pulse_start', result.stdout)
        self.assertNotIn(self.password, result.stdout+result.stderr)

    def test_invalid_limits_are_rejected(self):
        for overrides in [{'DB_TEST_PULSES':'0'}, {'DB_TEST_PULSES':'19'},
                          {'DB_TEST_PULSES':'01'}, {'DB_TEST_INTERVAL_SECONDS':'5'},
                          {'DB_TEST_START_DELAY_SECONDS':'61'},
                          {'DB_TEST_PULSES':'18','DB_TEST_INTERVAL_SECONDS':'30','DB_TEST_START_DELAY_SECONDS':'60'}]:
            with self.subTest(overrides=overrides):
                result = command(*self.run_command(overrides), check=False)
                self.assertEqual(result.returncode, 64, result.stderr)
                self.assertNotIn('pulse_start', result.stdout)

    def test_real_query_waits_then_rollback_preserves_data(self):
        proc = subprocess.Popen(self.run_command(), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.wait_for_lock(proc)
            started=time.monotonic()
            self.assertEqual(self.sql('SELECT name FROM public.users').stdout.strip(), 'synthetic')
            self.assertGreater(time.monotonic()-started, 1)
            stdout, stderr=proc.communicate(timeout=10)
            self.assertEqual(proc.returncode, 0, stderr)
            self.assertIn('pulse_completed', stdout)
            self.assertNotIn(self.password, stdout+stderr)
            self.assertEqual(self.sql('SELECT count(*) FROM public.users').stdout.strip(), '1')
        finally:
            if proc.poll() is None:
                proc.kill();proc.wait()

    def test_untrusted_server_certificate_fails_closed(self):
        args = self.run_command()
        mount = args.index('-v')
        del args[mount:mount+2]  # Use real RDS CA; it must reject our local self-signed server.
        result = command(*args, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn('pulse_failed', result.stdout)
        self.assertNotIn(self.password, result.stdout+result.stderr)

    def test_trusted_certificate_with_wrong_hostname_fails_closed(self):
        # Both aliases resolve to this same server; only HOST is in its certificate.
        result = command(*self.run_command({'PGHOST': WRONG_HOST}), check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn('pulse_failed', result.stdout)
        self.assertNotIn(self.password, result.stdout+result.stderr)

    def test_connection_override_environment_cannot_bypass_fixed_target(self):
        result = command(*self.run_command({
            'PGSERVICE': 'missing-service', 'PGSERVICEFILE': '/does-not-exist',
            'PGHOSTADDR': '127.0.0.1', 'PGPASSFILE': '/does-not-exist',
            'PGOPTIONS': '-c statement_timeout=1',
            'PGSSLROOTCERT': '/does-not-exist', 'PGCONNECT_TIMEOUT': 'invalid',
        }), check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('pulse_completed', result.stdout)

    def test_client_image_is_nonroot_readonly_and_supports_forced_timeout(self):
        result = command('docker', 'run', '--rm', '--read-only', '--network', 'none',
                         '--cap-drop=ALL', '--security-opt=no-new-privileges',
                         '--entrypoint', '/bin/sh', IMAGE, '-ec',
                         'test "$(id -u)" = 999; '
                         'test ! -e /usr/lib/postgresql/16/bin/postgres; '
                         'test -z "$(command -v postgres || true)"; '
                         'test -z "$(command -v initdb || true)"; '
                         'test -z "$(find /usr /opt -type f \\( -name postgres -o -name initdb \\) -print)"; '
                         'if command -v apk >/dev/null 2>&1; then '
                         '  packages=$(apk info); '
                         '  if printf "%s\\n" "$packages" | grep -Eq "^postgresql[0-9]+$"; then exit 1; fi; '
                         'else '
                         '  packages=$(dpkg-query -W -f=\'${binary:Package} ${db:Status-Status}\\n\'); '
                         '  if printf "%s\\n" "$packages" | grep -Eq "^postgresql-[0-9]+ installed$"; then exit 1; fi; '
                         'fi; '
                         'for file in /opt/db-test/*.sql /opt/db-test/*.crt; do '
                         '  test -r "$file"; test ! -w "$file"; '
                         'done; '
                         'psql --version; timeout --version; '
                         '! touch /opt/db-test/should-not-be-writable', check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('psql (PostgreSQL) ' + CLIENT_MAJOR + '.', result.stdout)
        self.assertIn('GNU coreutils', result.stdout)
        started = time.monotonic()
        result = command('docker', 'run', '--rm', '--read-only', '--network', 'none',
                         '--cap-drop=ALL', '--security-opt=no-new-privileges',
                         '--entrypoint', 'timeout', IMAGE, '--signal=TERM', '--kill-after=1s',
                         '1s', '/bin/sh', '-c', "trap '' TERM; while :; do sleep 1; done", check=False)
        self.assertEqual(result.returncode, 137, result.stdout + result.stderr)
        self.assertLess(time.monotonic() - started, 8)

    def test_lock_conflict_fails_without_leaving_transaction(self):
        proc = subprocess.Popen(['docker','exec','-e','PGAPPNAME=slash-test-blocker', self.name,
                                 'psql','-X','-U','slashadmin','-d','slash','-Atc',
                                 'BEGIN; LOCK TABLE users IN ACCESS SHARE MODE; SELECT pg_sleep(5); ROLLBACK;'],
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                if self.sql("SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a USING(pid) WHERE a.application_name='slash-test-blocker' AND l.mode='AccessShareLock' AND l.granted").stdout.strip() != '0':
                    break
                time.sleep(.03)
            else:
                self.fail('No test blocker lock')
            result = command(*self.run_command(), check=False)
            self.assertEqual(result.returncode,1)
            self.assertIn('pulse_failed',result.stdout)
            self.assertEqual(self.sql("SELECT count(*) FROM pg_stat_activity WHERE application_name='slash-m2-db-delay'").stdout.strip(),'0')
        finally:
            proc.communicate(timeout=8)

    def test_stop_task_signal_releases_actual_db_lock(self):
        name=self.name+'-signal'
        proc=subprocess.Popen(self.run_command(name=name), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.wait_for_lock(proc)
            command('docker', 'stop', '--time', '8', name)
            stdout,stderr=proc.communicate(timeout=10)
            self.assertNotEqual(proc.returncode,0)
            self.assertIn('stopped',stdout)
            started=time.monotonic()
            self.assertEqual(self.sql('SELECT name FROM public.users').stdout.strip(),'synthetic')
            self.assertLess(time.monotonic()-started,6)
            self.assertEqual(self.sql("SELECT count(*) FROM pg_stat_activity WHERE application_name='slash-m2-db-delay'").stdout.strip(),'0')
        finally:
            command('docker','rm','-f',name,check=False)
            if proc.poll() is None: proc.kill();proc.wait()

    def test_stop_during_start_delay_never_opens_database_session(self):
        name = self.name + '-waiting-signal'
        proc = subprocess.Popen(self.run_command({'DB_TEST_START_DELAY_SECONDS': '60'}, name=name),
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                logs = command('docker', 'logs', name, check=False)
                if '"event":"waiting"' in logs.stdout:
                    break
                if proc.poll() is not None:
                    stdout, stderr = proc.communicate()
                    self.fail('Runner ended before start delay: ' + stdout + stderr)
                time.sleep(.03)
            else:
                self.fail('Runner did not enter start delay')
            command('docker', 'stop', '--time', '8', name)
            stdout, stderr = proc.communicate(timeout=10)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn('stopped', stdout)
            self.assertNotIn('pulse_start', stdout)
            self.assertNotIn(self.password, stdout + stderr)
            self.assertEqual(self.sql("SELECT count(*) FROM pg_stat_activity WHERE application_name='slash-m2-db-delay'").stdout.strip(), '0')
            self.assertEqual(self.sql('SELECT name FROM public.users').stdout.strip(), 'synthetic')
        finally:
            command('docker', 'rm', '-f', name, check=False)
            if proc.poll() is None: proc.kill(); proc.wait()

    def test_stop_cancel_controller_releases_lock_without_cancelling_query(self):
        name = self.name + '-cancel-signal'
        proc = subprocess.Popen(self.run_command({'DB_TEST_MODE': 'cancel-one',
            'DB_TEST_EXPECTED_APP_IP': self.app_ip}, name=name),
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.wait_for_lock(proc)
            command('docker', 'stop', '--time', '8', name)
            stdout, stderr = proc.communicate(timeout=10)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn('stopped', stdout)
            self.assertNotIn('cancel_signalled', stdout)
            self.assertNotIn(self.password, stdout + stderr)
            started = time.monotonic()
            self.assertEqual(self.sql('SELECT name FROM public.users').stdout.strip(), 'synthetic')
            self.assertLess(time.monotonic() - started, 6)
            self.assert_no_controller()
        finally:
            command('docker', 'rm', '-f', name, check=False)
            if proc.poll() is None: proc.kill(); proc.wait()


if __name__ == '__main__':
    unittest.main()
