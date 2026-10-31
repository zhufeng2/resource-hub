"""Offline security and quota tests; no real PanSou login or network search."""
import concurrent.futures
import asyncio
import json
import logging
import os
import re
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from starlette.testclient import TestClient

from backend.app import create_app
from backend.errors import SearchFailure
from backend.config import Settings
from backend.service import SearchService
from backend.store import Store, day_key, pkce
from backend.mcp.oauth import authorization_cookie

logging.getLogger('httpx').setLevel(logging.WARNING)

BASE = 'https://search.example.com'
CALLBACK = 'https://chatgpt.com/connector_platform_oauth_redirect'
PASSWORD = 'test-password-for-online'


class ServiceTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {'PANSOU_BASE_URL': 'https://pansou.example'})
        environment.start()
        self.addCleanup(environment.stop)
        root = Path(__file__).resolve().parents[2] / '.cache' / 'online-tests'
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.settings = Settings(BASE, Path(self.temp.name) / 'service.sqlite3', (CALLBACK,))
        self.calls = []

        async def backend(query, timeout):
            self.calls.append(query)
            if query == 'fail':
                raise SearchFailure('模拟故障，本次不扣额度。')
            return {'query': query, 'results': [{'title': str(i), 'url': 'https://pan.quark.cn/s/test'} for i in range(35)]}

        self.app = create_app(self.settings, backend)
        self.store = self.app.state.store
        self.store.add_user('alice', PASSWORD, 5)
        self.store.add_user('bob', PASSWORD, 5)
        self.client = TestClient(self.app, base_url=BASE)
        self.client.__enter__()
        self.addCleanup(self.cleanup_temp)
        self.addCleanup(self.client.__exit__, None, None, None)

    def cleanup_temp(self):
        # Windows scanners can briefly hold an otherwise closed SQLite temp directory.
        for delay in (0, 0.05, 0.1, 0.2, 0.4):
            if delay:
                time.sleep(delay)
            try:
                self.temp.cleanup()
                return
            except PermissionError:
                pass
        self.temp.cleanup()

    def login(self, username='alice', verifier='x' * 43):
        registration = self.client.post('/oauth/register', json={'redirect_uris': [CALLBACK], 'token_endpoint_auth_method': 'none'})
        self.assertEqual(registration.status_code, 201, registration.text)
        client_id = registration.json()['client_id']
        params = {'client_id': client_id, 'redirect_uri': CALLBACK, 'response_type': 'code',
                  'scope': 'search', 'state': 'original-state', 'resource': self.settings.resource,
                  'code_challenge_method': 'S256', 'code_challenge': pkce(verifier)}
        response = self.client.get('/oauth/authorize', params=params)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['referrer-policy'], 'same-origin')
        ticket = re.search(r'name="ticket" value="([^"]+)"', response.text)[1]
        response = self.client.post('/oauth/authorize', data={
            'ticket': ticket, 'username': username, 'password': PASSWORD, 'action': 'allow'},
            headers={'Origin': BASE}, follow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text)
        location = parse_qs(urlsplit(response.headers['location']).query)
        self.assertEqual(location['state'], ['original-state'])
        self.assertEqual(location['iss'], [BASE])
        exchange = {'grant_type': 'authorization_code', 'client_id': client_id,
                    'redirect_uri': CALLBACK, 'resource': self.settings.resource,
                    'code': location['code'][0], 'code_verifier': verifier}
        token = self.client.post('/oauth/token', data=exchange)
        self.assertEqual(token.status_code, 200, token.text)
        return token.json(), client_id, exchange

    def rpc(self, token, method, params=None):
        response = self.client.post('/mcp', json={
            'jsonrpc': '2.0', 'id': 1, 'method': method, **({'params': params} if params is not None else {})},
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json, text/event-stream',
                     'MCP-Protocol-Version': '2025-03-26'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def tool(self, token, name, arguments=None):
        response = self.rpc(token, 'tools/call', {'name': name, 'arguments': arguments or {}})
        self.assertNotIn('error', response, response)
        result = response['result']
        self.assertFalse(result.get('isError'), result)
        return result.get('structuredContent') or json.loads(result['content'][0]['text'])

    def test_metadata_and_unauthenticated_transport(self):
        response = self.client.post('/mcp', json={})
        self.assertEqual(response.status_code, 401)
        self.assertIn('resource_metadata=', response.headers['www-authenticate'])
        metadata = self.client.get('/.well-known/oauth-authorization-server').json()
        self.assertEqual(metadata['code_challenge_methods_supported'], ['S256'])
        self.assertEqual(self.client.get('/.well-known/oauth-protected-resource/mcp').json()['resource'], self.settings.resource)
        self.assertEqual(self.client.post('/oauth/register', json={'redirect_uris': ['https://attacker.example/callback']}).status_code, 400)
        self.assertEqual(self.client.post('/oauth/register', json={
            'redirect_uris': [CALLBACK], 'grant_types': [{}]}).status_code, 400)

    def test_oauth_mcp_pagination_isolation_and_quota(self):
        tokens, _, exchange = self.login()
        token = tokens['access_token']
        self.assertEqual(self.client.post('/oauth/token', data=exchange).status_code, 400)
        init = self.rpc(token, 'initialize', {'protocolVersion': '2025-03-26', 'capabilities': {},
                                            'clientInfo': {'name': 'test', 'version': '1'}})
        self.assertIn('tools', init['result']['capabilities'])
        tools = self.rpc(token, 'tools/list')['result']['tools']
        self.assertTrue({'search_resources', 'get_search_results', 'get_quota', 'quark_save_file', 'quark_status', 'quark_operation_status'} <= {t['name'] for t in tools})
        first = self.tool(token, 'search_resources', {'query': 'test', 'request_id': 'same-request'})
        self.assertEqual(first['quota']['used'], 1)
        retry = self.tool(token, 'search_resources', {'query': 'test', 'request_id': 'same-request'})
        self.assertEqual(first['search_id'], retry['search_id'])
        self.assertEqual(self.calls, ['test'])
        page = self.tool(token, 'get_search_results', {'search_id': first['search_id'], 'offset': 20})
        self.assertEqual(page['returned_count'], 15)
        self.assertEqual(page['quota']['used'], 1)
        bob, _, _ = self.login('bob')
        private = self.tool(bob['access_token'], 'get_search_results', {'search_id': first['search_id']})
        self.assertEqual(private['error'], 'search_expired_or_not_found')
        failed = self.tool(token, 'search_resources', {'query': 'fail'})
        self.assertEqual(failed['error'], 'search_failed')
        self.assertEqual(self.tool(token, 'get_quota')['used'], 1)
        for i in range(4):
            self.tool(token, 'search_resources', {'query': 'test', 'request_id': 'new-' + str(i)})
        exhausted = self.tool(token, 'search_resources', {'query': 'sixth'})
        self.assertEqual(exhausted['error'], 'daily_limit_reached')
        self.assertEqual(exhausted['quota']['remaining'], 0)

    def test_refresh_revoke_and_disable(self):
        tokens, client_id, _ = self.login()
        params = {'grant_type': 'refresh_token', 'refresh_token': tokens['refresh_token'],
                  'client_id': client_id, 'resource': self.settings.resource}
        rotated = self.client.post('/oauth/token', data=params)
        self.assertEqual(rotated.status_code, 200)
        self.assertEqual(self.client.post('/oauth/token', data=params).status_code, 400)
        self.assertIsNone(self.store.authenticate(tokens['access_token'], self.settings.resource))
        token = rotated.json()['access_token']
        self.store.change_user('alice', enabled=False)
        self.assertEqual(self.client.post('/mcp', json={}, headers={'Authorization': 'Bearer ' + token}).status_code, 401)
        self.store.change_user('alice', enabled=True)
        self.assertIsNone(self.store.authenticate(token, self.settings.resource))
        bob, client_id, _ = self.login('bob')
        self.client.post('/oauth/revoke', data={'token': bob['access_token'], 'client_id': client_id})
        self.assertIsNone(self.store.authenticate(bob['access_token'], self.settings.resource))

    def test_pkce_audience_redirect_csrf_and_password_reset(self):
        tokens, client_id, _ = self.login()
        # Use a fresh authorization code to exercise rejected exchanges before successful redemption.
        p = {'client_id': client_id, 'redirect_uri': CALLBACK, 'response_type': 'code',
             'resource': self.settings.resource, 'code_challenge_method': 'S256', 'code_challenge': pkce('z' * 43)}
        response = self.client.get('/oauth/authorize', params=p)
        ticket = re.search(r'name="ticket" value="([^"]+)"', response.text)[1]
        form = {'ticket': 'wrong', 'username': 'alice', 'password': PASSWORD, 'action': 'allow'}
        self.assertEqual(self.client.post('/oauth/authorize', data=form).status_code, 403)
        form['ticket'] = ticket
        self.assertEqual(self.client.post('/oauth/authorize', data=form, headers={'Origin': 'https://attacker.example'}).status_code, 403)
        self.assertEqual(self.client.post('/oauth/authorize', data=form, headers={'Origin': 'null'}).status_code, 403)
        response = self.client.post('/oauth/authorize', data=form, follow_redirects=False)
        code = parse_qs(urlsplit(response.headers['location']).query)['code'][0]
        exchange = {'grant_type': 'authorization_code', 'client_id': client_id, 'redirect_uri': CALLBACK,
                    'resource': self.settings.resource, 'code': code, 'code_verifier': 'w' * 43}
        self.assertEqual(self.client.post('/oauth/token', data=exchange).status_code, 400)
        exchange['code_verifier'] = 'z' * 43
        exchange['resource'] = 'https://attacker.example/mcp'
        self.assertEqual(self.client.post('/oauth/token', data=exchange).json()['error'], 'invalid_target')
        exchange['resource'] = self.settings.resource
        exchange['redirect_uri'] = 'https://attacker.example'
        self.assertEqual(self.client.post('/oauth/token', data=exchange).status_code, 400)
        exchange['redirect_uri'] = CALLBACK
        self.assertEqual(self.client.post('/oauth/token', data=exchange).status_code, 200)
        self.store.change_user('alice', password='new-password-for-test')
        self.assertIsNone(self.store.authenticate(tokens['access_token'], self.settings.resource))

    def test_concurrent_reservations_restart_and_day_boundary(self):
        user = self.store.login('alice', PASSWORD)

        def attempt(i):
            try:
                return self.store.reserve(user['id'], 'parallel-' + str(i), 'test')[0]
            except ValueError:
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            rows = list(pool.map(attempt, range(12)))
        rows = [r for r in rows if r]
        self.assertEqual(len(rows), 5)
        self.assertEqual(self.store.quota(user['id'])['remaining'], 0)
        self.store.finish(rows[0]['id'], {'results': []})
        self.store.fail(rows[1]['id'])
        reopened = Store(self.settings.database)
        self.assertEqual(reopened.quota(user['id'])['used'], 1)
        self.assertEqual(reopened.quota(user['id'])['remaining'], 1)
        self.assertEqual(day_key(0), '1970-01-01')
        # 16:00 UTC is midnight in Shanghai, independent of the server timezone.
        self.assertNotEqual(day_key(57599), day_key(57600))
        with patch('backend.store.time.time', return_value=time.time() + 86400):
            self.assertEqual(reopened.quota(user['id'])['remaining'], 5)

    def test_limits_expiry_invalid_input_and_body_limit(self):
        tokens, _, _ = self.login()
        token = tokens['access_token']
        self.assertEqual(self.tool(token, 'search_resources', {'query': ' '})['error'], 'invalid_query')
        first = self.tool(token, 'search_resources', {'query': 'test', 'request_id': 'id1'})
        self.assertEqual(self.tool(token, 'search_resources', {'query': 'other', 'request_id': 'id1'})['error'], 'request_id_conflict')
        response = self.client.post('/oauth/token', content=b'x' * 17000)
        self.assertEqual(response.status_code, 413)
        with self.store.connection(True) as db:
            db.execute('UPDATE searches SET created=?', (time.time() - 86401,))
        self.assertEqual(self.tool(token, 'get_search_results', {'search_id': first['search_id']})['error'], 'search_expired_or_not_found')
        self.store.cleanup()
        self.assertTrue(self.store.rate('test-limit', 1, 60))
        self.assertFalse(self.store.rate('test-limit', 1, 60))

    def test_failed_retry_zero_results_and_stale_reservation(self):
        user = self.store.login('alice', PASSWORD)
        old, _ = self.store.reserve(user['id'], 'retry-after-crash', 'test')
        with self.store.connection(True) as db:
            db.execute('UPDATE searches SET created=? WHERE id=?', (time.time() - 181, old['id']))
        new, owned = self.store.reserve(user['id'], 'retry-after-crash', 'test')
        self.assertTrue(owned)
        self.assertNotEqual(old['id'], new['id'])
        self.store.finish(old['id'], {'results': []})
        self.assertEqual(self.store.quota(user['id'])['used'], 0)
        self.store.fail(new['id'])
        retry, _ = self.store.reserve(user['id'], 'retry-after-crash', 'test')
        self.store.finish(retry['id'], {'results': []})
        self.assertEqual(self.store.quota(user['id'])['used'], 1)
        with self.store.connection(True) as db:
            db.execute('UPDATE searches SET created=? WHERE id=?', (time.time() - 32 * 86400, retry['id']))
        self.store.cleanup()
        self.assertIsNone(self.store.search(user['id'], retry['id']))

    def authorization_page(self, client_id, state):
        response = self.client.get('/oauth/authorize', params={
            'client_id': client_id, 'redirect_uri': CALLBACK, 'response_type': 'code',
            'resource': self.settings.resource, 'code_challenge_method': 'S256',
            'code_challenge': pkce('a' * 43), 'state': state})
        self.assertEqual(response.status_code, 200)
        return re.search(r'name="ticket" value="([^"]+)"', response.text)[1]

    def test_parallel_authorization_pages_keep_independent_cookies(self):
        client_id = self.store.register([CALLBACK])
        first = self.authorization_page(client_id, 'first-tab')
        second = self.authorization_page(client_id, 'second-tab')
        for ticket, state in [(first, 'first-tab'), (second, 'second-tab')]:
            self.assertEqual(self.client.cookies[authorization_cookie(ticket)], ticket)
            response = self.client.post('/oauth/authorize', data={
                'ticket': ticket, 'username': 'alice', 'password': PASSWORD, 'action': 'allow'},
                headers={'Origin': BASE}, follow_redirects=False)
            self.assertEqual(response.status_code, 303, response.text)
            callback = parse_qs(urlsplit(response.headers['location']).query)
            self.assertEqual(callback['state'], [state])
            self.assertIn('code', callback)
            self.assertNotIn(authorization_cookie(ticket), self.client.cookies)
        # Consumed tickets cannot be replayed even if the form is resubmitted.
        response = self.client.post('/oauth/authorize', data={
            'ticket': first, 'username': 'alice', 'password': PASSWORD, 'action': 'allow'})
        self.assertEqual(response.status_code, 403)
        self.assertIn('已使用', response.json()['error_description'])

    def test_authorization_cookie_required_and_password_retry(self):
        client_id = self.store.register([CALLBACK])
        ticket = self.authorization_page(client_id, 'retry')
        form = {'ticket': ticket, 'username': 'alice', 'password': PASSWORD, 'action': 'allow'}
        self.client.cookies.clear()
        response = self.client.post('/oauth/authorize', data=form)
        self.assertEqual(response.status_code, 403)
        self.assertIn('Cookie', response.json()['error_description'])
        self.client.cookies.set(authorization_cookie(ticket), 'wrong')
        self.assertEqual(self.client.post('/oauth/authorize', data=form).status_code, 403)
        self.client.cookies.set(authorization_cookie(ticket), ticket)
        response = self.client.post('/oauth/authorize', data={**form, 'password': 'wrong'})
        self.assertEqual(response.status_code, 401)
        self.assertIn(ticket, response.text)
        self.assertEqual(self.client.post('/oauth/authorize', data=form,
                                         follow_redirects=False).status_code, 303)

    def test_expired_authorization_and_legacy_page(self):
        client_id = self.store.register([CALLBACK])
        ticket = self.authorization_page(client_id, 'expired')
        with self.store.connection(True) as db:
            db.execute('UPDATE tickets SET expires=0')
        response = self.client.post('/oauth/authorize', data={'ticket': ticket, 'action': 'deny'})
        self.assertEqual(response.status_code, 403)
        self.assertIn('10 分钟', response.json()['error_description'])
        ticket = self.authorization_page(client_id, 'legacy')
        self.client.cookies.clear()
        self.client.cookies.set('rh_authorize', ticket)
        response = self.client.post('/oauth/authorize', data={'ticket': ticket, 'action': 'deny'},
                                    follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(parse_qs(urlsplit(response.headers['location']).query)['error'], ['access_denied'])

    def test_mcp_personal_token_rotation_and_revoke(self):
        token = self.store.issue_mcp_token('alice', self.settings.resource, 30)
        self.assertTrue(token.startswith('rh_mcp_'))
        user = self.store.authenticate(token, self.settings.resource)
        self.assertEqual(user['username'], 'alice')
        self.assertIsNone(self.store.authenticate(token, 'https://other.example/mcp'))
        replacement = self.store.issue_mcp_token('alice', self.settings.resource, 30)
        self.assertIsNone(self.store.authenticate(token, self.settings.resource))
        self.assertEqual(self.store.authenticate(replacement, self.settings.resource)['username'], 'alice')
        self.assertEqual(self.store.revoke_mcp_token('alice'), 1)
        self.assertIsNone(self.store.authenticate(replacement, self.settings.resource))

    def test_preferences_migrate_verification_and_respect_opt_out(self):
        user_id = self.store.login('alice', PASSWORD)['id']
        with self.store.connection(True) as db:
            db.execute('INSERT OR REPLACE INTO preferences VALUES(?,?)',
                       (user_id, json.dumps({'auto_check': False, 'hide_invalid': False})))
        migrated = self.store.preferences(user_id)
        self.assertTrue(migrated['auto_check'])
        self.assertTrue(migrated['hide_invalid'])
        self.assertTrue(self.store.preferences(user_id)['auto_check'])
        opted_out = self.store.preferences(user_id, {**migrated, 'auto_check': False, 'hide_invalid': False})
        self.assertFalse(opted_out['auto_check'])
        self.assertFalse(self.store.preferences(user_id)['auto_check'])

    def test_mcp_verification_drops_bad_links(self):
        class Checker:
            async def check_links(self, items):
                return [{'state': 'ok' if index == 0 else 'bad', 'summary': ''}
                        for index, _ in enumerate(items)]

        service = SearchService(self.settings, self.store, Checker())
        data = {'results': [
            {'title': 'good', 'url': 'https://pan.quark.cn/s/good', 'cloud_type': 'quark'},
            {'title': 'bad', 'url': 'https://pan.quark.cn/s/bad', 'cloud_type': 'quark'},
        ], 'available_count': 2}
        result = asyncio.run(service.verify_page(data))
        self.assertEqual(len(result['results']), 1)
        self.assertEqual(result['results'][0]['title'], 'good')
        self.assertEqual(result['available_count'], 1)
        self.assertIn('1 条失效', result['verification'])

    def test_deny_and_transport_validation(self):
        _, client_id, _ = self.login()
        params = {'client_id': client_id, 'redirect_uri': CALLBACK, 'response_type': 'code',
                  'resource': self.settings.resource, 'code_challenge_method': 'S256', 'code_challenge': pkce('a' * 43),
                  'state': 'deny-state'}
        response = self.client.get('/oauth/authorize', params=params)
        ticket = re.search(r'name="ticket" value="([^"]+)"', response.text)[1]
        response = self.client.post('/oauth/authorize', data={
            'ticket': ticket, 'action': 'deny'}, follow_redirects=False)
        callback = parse_qs(urlsplit(response.headers['location']).query)
        self.assertEqual(callback['error'], ['access_denied'])
        self.assertEqual(callback['iss'], [BASE])
        self.assertEqual(callback['state'], ['deny-state'])
        self.assertEqual(self.client.get('/healthz', headers={'Host': 'attacker.example'}).status_code, 400)
        params['code_challenge_method'] = 'plain'
        response = self.client.get('/oauth/authorize', params=params, follow_redirects=False)
        self.assertEqual(parse_qs(urlsplit(response.headers['location']).query)['error'], ['invalid_request'])


if __name__ == '__main__':
    unittest.main()
