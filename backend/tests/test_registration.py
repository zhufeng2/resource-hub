"""Email proof, account isolation, replay protection and SMTP transport tests."""
from concurrent.futures import ThreadPoolExecutor
import os
import sqlite3
import unittest
from unittest.mock import AsyncMock, patch

from backend.email_verification import VerificationMailer, code_identity, normalize_email
from . import test_web
from .test_service import BASE, PASSWORD


class RegistrationTests(unittest.TestCase):
    cleanup_temp = test_web.WebTests.cleanup_temp
    web_login = test_web.WebTests.web_login

    def setUp(self):
        env = patch.dict(os.environ, {'SMTP_HOST': 'smtp.example.com', 'SMTP_FROM': 'no-reply@example.com',
                                     'SMTP_SECURITY': 'ssl', 'REGISTRATION_ENABLED': 'true'})
        env.start()
        self.addCleanup(env.stop)
        test_web.WebTests.setUp(self)
        mail = patch('backend.email_verification.VerificationMailer.send', new_callable=AsyncMock)
        self.mail = mail.start()
        self.addCleanup(mail.stop)
        self.headers = {'Origin': BASE, 'X-CSRF-Token': self.client.get('/api/session').json()['csrf']}

    def send(self, email='reader@example.com', binding=False):
        response = self.client.post('/api/email/code' if binding else '/api/register/code',
                                    json={'email': email}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return self.mail.call_args.args[1]

    def register(self, code, **overrides):
        data = {'username': 'reader', 'password': PASSWORD, 'email': 'reader@example.com', 'code': code}
        data.update(overrides)
        return self.client.post('/api/register', json=data, headers=self.headers)

    def test_registration_requires_email_and_grants_only_member_defaults(self):
        self.assertTrue(self.client.get('/api/session').json()['registration_enabled'])
        self.headers['X-CSRF-Token'] = self.client.get('/api/session').json()['csrf']
        code = self.send(' Reader@Example.COM ')
        self.assertEqual(self.mail.call_args.args[0], 'reader@example.com')
        denied = self.register(code, is_admin=True, daily_limit=10000)
        self.assertEqual(denied.status_code, 400)
        response = self.register(code, email=' READER@example.com ')
        self.assertEqual(response.status_code, 201, response.text)
        user = self.store.login('reader', PASSWORD)
        self.assertEqual((user['email'], user['is_admin'], user['daily_limit']),
                         ('reader@example.com', 0, self.settings.default_limit))
        self.assertNotEqual(user['password'], PASSWORD)
        self.assertEqual(self.register(code, username='reader2').status_code, 400)
        self.headers = self.web_login('reader')
        session = self.client.get('/api/session').json()
        self.assertEqual(session['email'], 'reader@example.com')
        self.assertFalse(session['can_manage_users'])
        self.assertNotIn('password', session)

    def test_csrf_gate_configuration_gate_and_no_unverified_accounts(self):
        self.assertEqual(self.register('000000').status_code, 400)
        self.assertIsNone(self.store.login('reader', PASSWORD))
        response = self.client.post('/api/register/code', json={'email': 'reader@example.com'})
        self.assertEqual(response.status_code, 403)
        response = self.client.post('/api/register/code', json={'email': 'reader@example.com'},
                                    headers={**self.headers, 'Origin': 'https://evil.example'})
        self.assertEqual(response.status_code, 403)
        for env in ({'SMTP_HOST': ''}, {'REGISTRATION_ENABLED': 'false'}, {'SMTP_SECURITY': 'none'},
                    {'SMTP_PORT': 'invalid'}, {'SMTP_FROM': 'invalid'},
                    {'SMTP_USERNAME': 'sender', 'SMTP_PASSWORD': ''}):
            with patch.dict(os.environ, env):
                self.assertEqual(self.register('000000').status_code, 503)
                self.assertFalse(self.client.get('/api/session').json()['registration_enabled'])
        self.mail.assert_not_awaited()

    def test_code_attempt_limit_expiration_and_session_binding(self):
        code = self.send()
        wrong = '000000' if code != '000000' else '000001'
        for _ in range(5):
            self.assertEqual(self.register(wrong).status_code, 400)
        self.assertEqual(self.register(code).status_code, 400)
        with self.store.connection(True) as db:
            row = db.execute('SELECT * FROM email_codes').fetchone()
            self.assertEqual(row['attempts'], 5)
            self.assertNotEqual(row['code_hash'], code)
            db.execute('UPDATE email_codes SET attempts=0,expires=0')
        self.assertEqual(self.register(code).status_code, 400)
        with self.store.connection(True) as db:
            db.execute('UPDATE email_codes SET expires=9999999999')
        self.headers['X-CSRF-Token'] = self.client.get('/api/session').json()['csrf']
        self.assertEqual(self.register(code).status_code, 400)
        self.assertIsNone(self.store.login('reader', PASSWORD))

    def test_send_rate_limits_and_delivery_failure_invalidate_code(self):
        self.mail.side_effect = RuntimeError('private SMTP password must not escape')
        response = self.client.post('/api/register/code', json={'email': 'reader@example.com'}, headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private SMTP', response.text)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM email_codes').fetchone()[0], 0)
        repeated = self.client.post('/api/register/code', json={'email': 'READER@example.com'}, headers=self.headers)
        self.assertEqual(repeated.status_code, 429)
        self.mail.assert_awaited_once()

    def test_existing_account_binding_and_admin_email_search(self):
        self.headers = self.web_login('alice')
        code = self.send('Owner@Example.com', binding=True)
        # A binding code cannot be repurposed for registration.
        self.assertEqual(self.register(code, email='owner@example.com').status_code, 403)
        response = self.client.post('/api/email', json={'email': 'owner@example.com', 'code': code}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get('/api/session').json()['email'], 'owner@example.com')
        self.assertEqual(self.client.post('/api/email/code', json={'email': 'other@example.com'}, headers=self.headers).status_code, 400)
        self.headers = self.web_login('admin')
        result = self.client.get('/api/users?q=OWNER@EXAMPLE.COM').json()
        self.assertEqual([u['username'] for u in result['items']], ['alice'])
        self.headers = self.web_login('bob')
        before = self.mail.await_count
        # Clear mailbox cooldown solely to exercise the duplicate-mailbox response.
        with self.store.connection(True) as db:
            db.execute("DELETE FROM limits WHERE key LIKE 'mail-%'")
        self.client.post('/api/email/code', json={'email': 'owner@example.com'}, headers=self.headers)
        self.assertEqual(self.mail.await_count, before)

    def test_two_concurrent_registrations_cannot_claim_same_mailbox(self):
        entries = []
        for index in range(2):
            key, proof = code_identity('shared@example.com', 'register', f'session-{index}', '123456')
            self.store.save_email_code(key, proof)
            entries.append((key, proof, f'reader{index}'))

        def run(entry):
            key, proof, username = entry
            try:
                return self.store.verify_email_account(key, proof, 'shared@example.com',
                                                      username=username, password=PASSWORD)
            except sqlite3.IntegrityError:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(run, entries)), [False, True])
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM users WHERE email='shared@example.com'").fetchone()[0], 1)

    def test_legacy_database_migrates_without_losing_existing_user(self):
        from backend.store import Store
        path = self.settings.database.parent / 'legacy.sqlite3'
        with self.store.connection() as db:
            password = db.execute("SELECT password FROM users WHERE username='bob'").fetchone()[0]
        with sqlite3.connect(path) as db:
            db.execute('''CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL, daily_limit INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                is_admin INTEGER NOT NULL DEFAULT 0)''')
            db.execute('INSERT INTO users VALUES(1,?,?,5,1,1)', ('legacy-admin', password))
        db.close()
        migrated = Store(path)
        self.assertIsNone(migrated.login('legacy-admin', PASSWORD)['email'])
        self.assertEqual(migrated.login('legacy-admin', PASSWORD)['is_admin'], 1)
        self.assertEqual(Store(path).user_page()['total'], 1)

    def test_input_validation(self):
        for domain in ['qq.com', '163.com', 'gmail.com', 'outlook.com', 'foxmail.com', 'company.example']:
            self.assertEqual(normalize_email('Reader@' + domain), 'reader@' + domain)
        for email in ['bad', 'a\r\nbcc:x@example.com', 'x@localhost', '.x@example.com', 'x..y@example.com']:
            with self.assertRaises(ValueError):
                normalize_email(email)
        for username in ['admin', 'ADMIN', 'root', '../bad', 'ab', 'bad name']:
            self.assertEqual(self.register('000000', username=username).status_code, 400)


class SMTPTests(unittest.TestCase):
    def test_tls_and_starttls_and_no_secret_in_message(self):
        env = {'SMTP_HOST': 'smtp.example.com', 'SMTP_FROM': 'Resource Hub <no-reply@example.com>',
               'SMTP_USERNAME': 'sender', 'SMTP_PASSWORD': 'smtp-secret'}
        for security, transport in [('ssl', 'SMTP_SSL'), ('starttls', 'SMTP')]:
            with patch.dict(os.environ, {**env, 'SMTP_SECURITY': security}), patch('smtplib.' + transport) as factory:
                client = factory.return_value
                client.send_message.return_value = {}
                VerificationMailer()._send('reader@example.com', '123456')
                client.login.assert_called_once_with('sender', 'smtp-secret')
                message = client.send_message.call_args.args[0]
                self.assertEqual(message['To'], 'reader@example.com')
                self.assertIn('123456', message.get_content())
                self.assertNotIn('smtp-secret', message.as_string())
                if security == 'starttls':
                    factory.return_value.starttls.assert_called_once()
                else:
                    self.assertTrue(factory.call_args.kwargs['context'].check_hostname)
