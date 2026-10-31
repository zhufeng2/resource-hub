"""Email password recovery: ownership, one-use proofs, expiry and revocation."""
from concurrent.futures import ThreadPoolExecutor
import os
import unittest
from unittest.mock import patch

from backend.email_verification import code_identity
from backend.store import digest
from . import test_registration
from . import test_web
from .test_service import BASE, PASSWORD

NEW_PASSWORD = 'replacement-password-2026'


class PasswordResetTests(unittest.TestCase):
    cleanup_temp = test_web.WebTests.cleanup_temp
    web_login = test_web.WebTests.web_login
    login = test_web.WebTests.login

    def setUp(self):
        test_registration.RegistrationTests.setUp(self)
        with self.store.connection(True) as db:
            db.execute("UPDATE users SET email='owner@example.com' WHERE username='bob'")
        self.account = self.store.login('bob', PASSWORD)

    def send(self, email='owner@example.com'):
        response = self.client.post('/api/password/reset/code', json={'email': email}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return self.mail.call_args.args[1] if self.mail.call_args else None

    def reset(self, proof_code, **overrides):
        data = {'email': 'owner@example.com', 'code': proof_code, 'password': NEW_PASSWORD}
        data.update(overrides)
        return self.client.post('/api/password/reset', json=data, headers=self.headers)

    def test_recovery_changes_only_owner_and_revokes_all_old_auth(self):
        session, _ = self.store.web_session(self.account['id'])
        token = self.store.issue_mcp_token('bob', self.settings.resource)
        oauth, client_id, _ = self.login('bob')
        foreign = self.store.login('alice', PASSWORD)
        foreign_session, _ = self.store.web_session(foreign['id'])
        code = self.send(' OWNER@example.com ')
        self.assertEqual(self.mail.call_args.args[0], 'owner@example.com')
        response = self.reset(code)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertIsNone(self.store.login('bob', PASSWORD))
        self.assertIsNotNone(self.store.login('bob', NEW_PASSWORD))
        self.assertIsNone(self.store.web_user(session))
        self.assertIsNone(self.store.authenticate(token, self.settings.resource))
        self.assertIsNone(self.store.authenticate(oauth['access_token'], self.settings.resource))
        refreshed = self.client.post('/oauth/token', data={'grant_type': 'refresh_token',
            'client_id': client_id, 'resource': self.settings.resource, 'refresh_token': oauth['refresh_token']})
        self.assertEqual(refreshed.status_code, 400)
        self.assertIsNotNone(self.store.web_user(foreign_session))
        self.assertIsNotNone(self.store.login('alice', PASSWORD))
        self.assertEqual(self.reset(code).status_code, 400)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM mcp_token_secrets').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM email_codes').fetchone()[0], 0)

    def test_recovery_is_independent_of_registration_and_csrf_protected(self):
        with patch.dict(os.environ, {'REGISTRATION_ENABLED': 'false'}):
            session = self.client.get('/api/session').json()
            self.assertFalse(session['registration_enabled'])
            self.assertTrue(session['password_reset_enabled'])
            self.headers['X-CSRF-Token'] = session['csrf']
            for path in ('/api/password/reset/code', '/api/password/reset'):
                self.assertEqual(self.client.post(path, json={}).status_code, 403)
                self.assertEqual(self.client.post(path, json={}, headers={
                    **self.headers, 'Origin': 'https://evil.example'}).status_code, 403)
            code = self.send()
            self.assertEqual(self.reset(code).status_code, 200)
        with patch.dict(os.environ, {'SMTP_HOST': ''}):
            self.assertFalse(self.client.get('/api/session').json()['password_reset_enabled'])
            self.assertEqual(self.reset('000000').status_code, 503)

    def test_unknown_disabled_and_unbound_accounts_do_not_leak_or_receive_codes(self):
        unknown = self.client.post('/api/password/reset/code', json={'email': 'unknown@example.com'}, headers=self.headers)
        self.store.change_user('bob', enabled=False)
        disabled = self.client.post('/api/password/reset/code', json={'email': 'owner@example.com'}, headers=self.headers)
        self.assertEqual(unknown.status_code, 200)
        self.assertEqual(unknown.json(), disabled.json())
        self.mail.assert_not_awaited()
        self.assertIsNone(self.store.password_reset_account('admin@example.com'))
        invalid = self.reset('000000').json()
        self.assertEqual(invalid, self.reset('000000', email='unknown@example.com').json())

    def test_wrong_attempts_expiry_and_browser_binding(self):
        code = self.send()
        wrong = '000000' if code != '000000' else '000001'
        for _ in range(5):
            self.assertEqual(self.reset(wrong).status_code, 400)
        self.assertEqual(self.reset(code).status_code, 400)
        with self.store.connection(True) as db:
            row = db.execute('SELECT * FROM email_codes').fetchone()
            self.assertEqual(row['attempts'], 5)
            self.assertNotEqual(row['code_hash'], code)
            db.execute('UPDATE email_codes SET attempts=0,expires=0')
        self.assertEqual(self.reset(code).status_code, 400)
        with self.store.connection(True) as db:
            db.execute('UPDATE email_codes SET expires=9999999999')
        self.headers['X-CSRF-Token'] = self.client.get('/api/session').json()['csrf']
        self.assertEqual(self.reset(code).status_code, 400)
        self.assertIsNotNone(self.store.login('bob', PASSWORD))

    def test_register_code_and_late_code_after_password_change_cannot_reset(self):
        csrf = self.headers['X-CSRF-Token']
        key, proof = code_identity('owner@example.com', 'register', csrf, '123456')
        self.store.save_email_code(key, proof)
        self.assertEqual(self.reset('123456').status_code, 400)
        code = self.send()
        self.store.change_user('bob', password='another-password-by-admin')
        self.assertEqual(self.reset(code).status_code, 400)
        self.assertIsNotNone(self.store.login('bob', 'another-password-by-admin'))

    def test_failed_delivery_removes_proof_and_response_does_not_expose_account(self):
        self.mail.side_effect = RuntimeError('private SMTP secret')
        known = self.client.post('/api/password/reset/code', json={'email': 'owner@example.com'}, headers=self.headers)
        missing = self.client.post('/api/password/reset/code', json={'email': 'unknown@example.com'}, headers=self.headers)
        self.assertEqual(known.json(), missing.json())
        self.assertNotIn('private SMTP', known.text)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM email_codes').fetchone()[0], 0)
        repeated = self.client.post('/api/password/reset/code', json={'email': 'OWNER@example.com'}, headers=self.headers)
        self.assertEqual(repeated.status_code, 429)

    def test_validation_does_not_consume_good_code(self):
        code = self.send()
        for data in ({'password': 'short'}, {'password': []}, {'code': '123'}, {'code': 123456},
                     {'email': 'bad'}, {'username': 'alice'}):
            self.assertEqual(self.reset(code, **data).status_code, 400)
        self.assertEqual(self.reset(code).status_code, 200)

    def test_proof_can_be_consumed_only_once_under_concurrency(self):
        code = self.send()
        purpose = 'password-reset:' + str(self.account['id']) + ':' + digest(self.account['password'])
        key, proof = code_identity('owner@example.com', purpose, self.headers['X-CSRF-Token'], code)
        def reset(_):
            return self.store.reset_password_with_code(key, proof, 'owner@example.com',
                self.account['id'], self.account['password'], NEW_PASSWORD)
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(reset, range(2))), [False, True])
        self.assertIsNotNone(self.store.login('bob', NEW_PASSWORD))
