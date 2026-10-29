"""Browser security and shared quota integration, using in-process fake upstream calls."""
import asyncio
import json
import os
import unittest
from unittest.mock import patch

import httpx

from . import test_service as fixtures
from .test_service import BASE, PASSWORD
from backend.app import create_app
from backend.upstream import Upstream
from backend.store import Store, digest


class FakeUpstream:
    def __init__(self):
        self.actions = []

    async def catalog(self):
        return {'plugins': ['qqpd', 'gying', 'panlian', 'weibo', 'woniu'], 'channels': ['example']}

    async def create_binding(self, provider):
        return 'a' * 64

    async def binding_action(self, binding, action, data):
        self.actions.append((binding['id'], action))
        return {'success': True, 'data': {'logged_in': action != 'logout'}, 'message': ''}

    async def check_links(self, items):
        return [{'state': 'ok', 'summary': ''} for _ in items]

    normalize = staticmethod(Upstream.normalize)

    async def request(self, path, payload, **kwargs):
        return {'success': True, 'data': {'results': [{'title': 'source example', 'links': [
            {'type': 'quark', 'url': 'https://pan.quark.cn/s/source'}]}]}}


class WebTests(unittest.TestCase):
    cleanup_temp = fixtures.ServiceTests.cleanup_temp
    login = fixtures.ServiceTests.login
    rpc = fixtures.ServiceTests.rpc
    tool = fixtures.ServiceTests.tool

    def setUp(self):
        fixtures.ServiceTests.setUp(self)
        self.fake = FakeUpstream()
        self.app.state.upstream = self.fake
        # The registered bound methods retain their Web object, so replace its adapter as well.
        for route in self.app.routes:
            endpoint = getattr(route, 'endpoint', None)
            for cell in getattr(endpoint, '__closure__', ()) or ():
                handler = cell.cell_contents
                if hasattr(handler, '__self__') and hasattr(handler.__self__, 'upstream'):
                    handler.__self__.upstream = self.fake
        self.store.change_user('alice', is_admin=True)
        self.store.add_user('admin', PASSWORD, 5, is_admin=True)

    def web_login(self, username='alice'):
        response = self.client.get('/api/session')
        if response.json().get('username'):
            self.client.post('/api/logout', json={}, headers={
                'Origin': BASE, 'X-CSRF-Token': response.json()['csrf']})
            response = self.client.get('/api/session')
        csrf = response.json()['csrf']
        response = self.client.post('/api/login', json={'username': username, 'password': PASSWORD},
                                    headers={'Origin': BASE, 'X-CSRF-Token': csrf})
        self.assertEqual(response.status_code, 200, response.text)
        return {'Origin': BASE, 'X-CSRF-Token': response.json()['csrf']}

    def test_web_login_csrf_and_mcp_share_quota(self):
        self.assertEqual(self.client.get('/api/history').status_code, 401)
        headers = self.web_login()
        self.assertTrue(self.client.cookies['rh_session'])
        self.assertEqual(self.client.post('/api/search', json={'query': 'test'}).status_code, 403)
        result = self.client.post('/api/search', json={'query': 'test', 'request_id': 'web1'}, headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        search_id = result.json()['search_id']
        refreshed = self.client.post('/api/search', json={
            'query': 'test', 'request_id': 'web-refresh', 'refresh': True}, headers=headers)
        self.assertEqual(refreshed.json()['quota']['used'], 2)
        tokens, _, _ = self.login()
        self.assertEqual(self.tool(tokens['access_token'], 'get_quota')['used'], 2)
        self.assertEqual(self.client.get('/api/results/' + search_id).json()['available_count'], 35)
        self.web_login('bob')
        self.assertIn('error', self.client.get('/api/results/' + search_id).json())

    def test_page_versions_assets_by_content_to_prevent_stale_styles(self):
        directory = self.settings.database.parent / 'asset-version-test'
        directory.mkdir()
        (directory / 'index.html').write_text('<link rel="stylesheet" href="/assets/glass.css">', encoding='utf-8')
        stylesheet = directory / 'glass.css'
        stylesheet.write_text('button {color:blue}', encoding='utf-8')
        with patch('web.app.STATIC', directory):
            first = self.client.get('/profile')
            self.assertIn('/assets/glass.css?v=', first.text)
            self.assertEqual(first.headers['cache-control'], 'no-cache')
            stylesheet.write_text('button {color:white}', encoding='utf-8')
            second = self.client.get('/profile')
            self.assertNotEqual(first.text, second.text)

    def test_admin_permissions_preferences_and_revocation(self):
        headers = self.web_login('bob')
        self.assertEqual(self.client.get('/api/users').status_code, 403)
        invalid = self.client.put('/api/preferences', json={'admin': True}, headers=headers)
        self.assertEqual(invalid.status_code, 400)
        headers = self.web_login('admin')
        created = self.client.post('/api/users', json={'username': 'charlie', 'password': PASSWORD, 'daily_limit': 7}, headers=headers)
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(self.store.login('charlie', PASSWORD)['daily_limit'], 7)
        config = {'cloud_types': ['baidu'], 'auto_check': True, 'theme': 'dark'}
        saved = self.client.put('/api/preferences', json=config, headers=headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.store.preferences(self.store.login('admin', PASSWORD)['id'])['cloud_types'], ['baidu'])
        tokens, _, _ = self.login('admin')
        self.assertEqual(self.client.post('/api/connections/revoke', json={}, headers=headers).status_code, 200)
        self.assertIsNone(self.store.authenticate(tokens['access_token'], self.settings.resource))

    def test_delete_history_requires_owner_and_csrf_and_erases_content(self):
        self.assertEqual(self.client.delete('/api/history').status_code, 401)
        self.assertEqual(self.client.delete('/api/history/missing').status_code, 401)
        headers = self.web_login()
        result = self.client.post('/api/search', json={'query': 'private history', 'request_id': 'delete-one'}, headers=headers).json()
        search_id = result['search_id']
        self.assertEqual(self.client.delete('/api/history/' + search_id).status_code, 403)
        self.assertEqual(self.client.delete('/api/history/' + search_id, headers={
            **headers, 'Origin': 'https://other.example'}).status_code, 403)
        other_headers = self.web_login('bob')
        self.assertEqual(self.client.delete('/api/history/' + search_id, headers=other_headers).status_code, 404)
        self.assertIsNotNone(self.store.search(self.store.login('alice', PASSWORD)['id'], search_id)['result'])
        headers = self.web_login()
        before = self.client.get('/api/session').json()['quota']
        deleted = self.client.delete('/api/history/' + search_id, headers=headers)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json(), {'deleted_ids': [search_id], 'items': []})
        self.assertEqual(self.client.get('/api/session').json()['quota'], before)
        self.assertEqual(self.client.get('/api/results/' + search_id).json()['error'], 'search_expired_or_not_found')
        self.assertEqual(self.client.delete('/api/history/' + search_id, headers=headers).status_code, 404)
        row = self.store.search(self.store.login('alice', PASSWORD)['id'], search_id)
        self.assertEqual(row['query'], '')
        self.assertIsNone(row['result'])
        tokens, _, _ = self.login()
        self.assertEqual(self.tool(tokens['access_token'], 'get_search_results', {'search_id': search_id})['error'],
                         'search_expired_or_not_found')

    def test_delete_history_removes_duplicate_keywords_without_refunding_quota(self):
        self.store.change_user('alice', is_admin=False, limit=3)
        headers = self.web_login()
        results = []
        for index, query in enumerate(('Ｆｏｏ  BAR', 'foo bar', 'keep')):
            results.append(self.client.post('/api/search', json={
                'query': query, 'request_id': 'delete-group-' + str(index)}, headers=headers).json())
        self.assertEqual(len(self.client.get('/api/history').json()['items']), 2)
        deleted = self.client.delete('/api/history/' + results[1]['search_id'], headers=headers).json()
        self.assertEqual(set(deleted['deleted_ids']), {results[0]['search_id'], results[1]['search_id']})
        self.assertEqual([item['query'] for item in deleted['items']], ['keep'])
        backend_calls = len(self.calls)
        replay = self.client.post('/api/search', json={
            'query': 'foo bar', 'request_id': 'delete-group-1'}, headers=headers).json()
        self.assertEqual(replay['error'], 'request_id_conflict')
        self.assertEqual(len(self.calls), backend_calls)
        blocked = self.client.post('/api/search', json={'query': 'new'}, headers=headers)
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()['quota']['used'], 3)
        self.assertEqual(blocked.json()['quota']['remaining'], 0)

    def test_clear_history_preserves_other_users_and_pending_searches(self):
        other_headers = self.web_login('bob')
        other = self.client.post('/api/search', json={'query': 'other user'}, headers=other_headers).json()
        headers = self.web_login()
        result = self.client.post('/api/search', json={'query': 'own search'}, headers=headers).json()
        user_id = self.store.login('alice', PASSWORD)['id']
        pending, _ = self.store.reserve(user_id, 'still-running', 'pending keyword')
        before = self.store.quota(user_id)
        self.assertEqual(self.client.delete('/api/history').status_code, 403)
        cleared = self.client.delete('/api/history', headers=headers)
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json(), {'deleted_ids': [result['search_id']], 'items': []})
        self.assertEqual(self.client.delete('/api/history', headers=headers).json()['deleted_ids'], [])
        self.assertEqual(self.store.quota(user_id), before)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT status,query FROM searches WHERE id=?', (pending['id'],)).fetchone()['query'],
                             'pending keyword')
        self.web_login('bob')
        self.assertEqual(self.client.get('/api/history').json()['items'][0]['id'], other['search_id'])
        self.assertIn('results', self.client.get('/api/results/' + other['search_id']).json())

    def test_admin_quota_is_unlimited(self):
        self.store.change_user('admin', limit=0)
        headers = self.web_login('admin')
        result = self.client.post('/api/search', json={'query': 'test', 'request_id': 'admin-unlimited'}, headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()['quota']['unlimited'])
        self.assertIsNone(result.json()['quota']['daily_limit'])
        self.assertIsNone(result.json()['quota']['remaining'])
        self.store.change_user('bob', limit=0)
        headers = self.web_login('bob')
        blocked = self.client.post('/api/search', json={'query': 'test'}, headers=headers)
        self.assertEqual(blocked.status_code, 429, blocked.text)
        self.assertEqual(blocked.json()['error'], 'daily_limit_reached')

    def test_binding_ownership_and_test_search_quota(self):
        headers = self.web_login()
        response = self.client.post('/api/bindings', json={'provider': 'gying', 'label': 'my account'}, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        item = response.json()['items'][0]
        self.assertNotIn('upstream_hash', item)
        result = self.client.post('/api/bindings/' + item['id'], json={'action': 'test_search', 'keyword': 'test'}, headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['quota']['used'], 1)
        self.assertEqual(self.client.post('/api/bindings/' + item['id'], json={
            'action': 'update_config', 'base_url': 'https://127.0.0.1/'}, headers=headers).status_code, 403)
        headers = self.web_login('bob')
        denied = self.client.post('/api/bindings/' + item['id'], json={'action': 'get_status'}, headers=headers)
        self.assertEqual(denied.status_code, 404)

    def test_password_change_revokes_web_and_mcp_sessions(self):
        headers = self.web_login()
        tokens, _, _ = self.login()
        personal = self.client.post('/api/mcp-token', headers=headers).json()['token']
        result = self.client.post('/api/password', json={'current_password': PASSWORD, 'password': 'new-long-password-2026'}, headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.get('/api/history').status_code, 401)
        self.assertIsNone(self.store.authenticate(tokens['access_token'], self.settings.resource))
        self.assertIsNone(self.store.authenticate(personal, self.settings.resource))
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM mcp_token_secrets').fetchone()[0], 0)

    def test_personal_mcp_token_is_session_owned_and_shares_quota(self):
        for method in ('GET', 'POST', 'DELETE'):
            self.assertEqual(self.client.request(method, '/api/mcp-token').status_code, 401)
        headers = self.web_login('bob')
        for method in ('POST', 'DELETE'):
            self.assertEqual(self.client.request(method, '/api/mcp-token').status_code, 403)
            self.assertEqual(self.client.request(method, '/api/mcp-token', headers={
                **headers, 'Origin': 'https://other.example'}).status_code, 403)
        issued = self.client.post('/api/mcp-token', json={'username': 'alice'}, headers=headers)
        self.assertEqual(issued.status_code, 200, issued.text)
        self.assertEqual(issued.headers['cache-control'], 'no-store')
        token = issued.json()['token']
        self.assertEqual(self.store.authenticate(token, self.settings.resource)['username'], 'bob')
        self.assertEqual(self.client.get('/api/mcp-token').json()['token'], token)
        self.assertNotIn(token, self.client.get('/api/session').text)
        # Encryption survives a Store restart without placing plaintext in SQLite.
        reopened = Store(self.settings.database)
        bob = self.store.login('bob', PASSWORD)
        self.assertEqual(reopened.mcp_token_status(bob['id'], self.settings.resource, reveal=True)['token'], token)
        with self.store.connection() as db:
            encrypted = db.execute('SELECT ciphertext FROM mcp_token_secrets WHERE hash=?', (digest(token),)).fetchone()[0]
            self.assertNotIn(token.encode(), encrypted)
        self.assertEqual(self.tool(token, 'get_quota')['username'], 'bob')
        result = self.tool(token, 'search_resources', {'query': 'test', 'request_id': 'personal-mcp'})
        self.assertEqual(result['quota']['used'], 1)
        self.assertEqual(self.client.get('/api/session').json()['quota']['used'], 1)
        alice_headers = self.web_login('alice')
        self.assertFalse(self.client.get('/api/mcp-token').json()['active'])
        self.client.delete('/api/mcp-token', headers=alice_headers)
        self.assertIsNotNone(self.store.authenticate(token, self.settings.resource))

    def test_personal_mcp_rotation_and_revoke_preserve_oauth_until_revoke_all(self):
        headers = self.web_login('bob')
        oauth, _, _ = self.login('bob')
        old = self.client.post('/api/mcp-token', headers=headers).json()['token']
        new = self.client.post('/api/mcp-token', headers=headers).json()['token']
        self.assertNotEqual(old, new)
        self.assertIsNone(self.store.authenticate(old, self.settings.resource))
        self.assertIsNotNone(self.store.authenticate(new, self.settings.resource))
        self.assertIsNotNone(self.store.authenticate(oauth['access_token'], self.settings.resource))
        self.assertFalse(self.client.delete('/api/mcp-token', headers=headers).json()['active'])
        self.assertIsNone(self.store.authenticate(new, self.settings.resource))
        self.assertIsNotNone(self.store.authenticate(oauth['access_token'], self.settings.resource))
        token = self.client.post('/api/mcp-token', headers=headers).json()['token']
        self.client.post('/api/connections/revoke', headers=headers)
        self.assertIsNone(self.store.authenticate(token, self.settings.resource))
        self.assertIsNone(self.store.authenticate(oauth['access_token'], self.settings.resource))
        self.assertIsNone(self.client.get('/api/mcp-token').json()['token'])

    def test_personal_mcp_token_default_lifetime_is_seven_days(self):
        issued_at = 1800000000
        bob = self.store.login('bob', PASSWORD)
        with patch('backend.store.time.time', return_value=issued_at):
            token = self.store.issue_mcp_token('bob', self.settings.resource)
            status = self.store.mcp_token_status(bob['id'], self.settings.resource)
            self.assertEqual(status['expires_at'], issued_at + 7 * 86400)
        with patch('backend.store.time.time', return_value=issued_at + 7 * 86400 - 1):
            self.assertIsNotNone(self.store.authenticate(token, self.settings.resource))
        with patch('backend.store.time.time', return_value=issued_at + 7 * 86400):
            self.assertIsNone(self.store.authenticate(token, self.settings.resource))
            self.assertFalse(self.store.mcp_token_status(bob['id'], self.settings.resource)['active'])

    def test_legacy_mcp_token_and_missing_key_require_explicit_regeneration(self):
        headers = self.web_login('bob')
        token = self.client.post('/api/mcp-token', headers=headers).json()['token']
        with self.store.connection(True) as db:
            db.execute('DELETE FROM mcp_token_secrets WHERE hash=?', (digest(token),))
        legacy = self.client.get('/api/mcp-token').json()
        self.assertTrue(legacy['active'])
        self.assertIsNone(legacy['token'])
        self.assertIsNotNone(self.store.authenticate(token, self.settings.resource))
        token = self.client.post('/api/mcp-token', headers=headers).json()['token']
        key_path = self.settings.database.with_name(self.settings.database.name + '.mcp.key')
        key_path.unlink()
        missing = self.client.get('/api/mcp-token').json()
        self.assertTrue(missing['active'])
        self.assertIsNone(missing['token'])
        self.assertIsNotNone(self.store.authenticate(token, self.settings.resource))
        new = self.client.post('/api/mcp-token', headers=headers).json()['token']
        self.assertIsNone(self.store.authenticate(token, self.settings.resource))
        self.assertEqual(self.client.get('/api/mcp-token').json()['token'], new)

    def test_static_page_and_check_reject_arbitrary_urls(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('搜索源账号', response.text)
        self.assertNotIn('不会登录', response.text)
        headers = self.web_login()
        result = self.client.post('/api/search', json={'query': 'test'}, headers=headers).json()
        denied = self.client.post('/api/check', json={'search_id': result['search_id'], 'urls': ['http://127.0.0.1/admin']}, headers=headers)
        self.assertEqual(denied.status_code, 403)


class UpstreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_admin_credential_stays_server_side_and_response_is_filtered(self):
        calls = []

        def handler(request):
            calls.append(request)
            if request.url.path == '/api/auth/login':
                return httpx.Response(200, json={'token': 'private-admin-token'})
            self.assertEqual(request.headers['Authorization'], 'Bearer private-admin-token')
            if request.url.path == '/api/search':
                return httpx.Response(200, json={'merged_by_type': {'quark': [{'url': 'https://pan.quark.cn/s/test', 'note': 'test'}]}, 'token': 'must-not-leak'})
            return httpx.Response(200, json={'success': True, 'data': {'logged_in': True, 'cookie': 'private-cookie', 'token': 'private-token'}})

        real_client = httpx.AsyncClient
        def factory(**kwargs):
            kwargs['transport'] = httpx.MockTransport(handler)
            return real_client(**kwargs)

        with patch.dict(os.environ, {'PANSOU_BASE_URL': 'https://pansou.example', 'PANSOU_USERNAME': 'admin',
                                    'PANSOU_PASSWORD': 'private-password', 'PANSOU_API_TOKEN': ''}), patch('backend.upstream.httpx.AsyncClient', factory):
            upstream = Upstream()
            result = await upstream.search('test', 10, {'cloud_types': ['quark'], 'plugins': ['gying'], 'refresh': True})
            status = await upstream.binding_action({'provider': 'gying', 'upstream_hash': 'a' * 64}, 'get_status', {})
        self.assertNotIn('private', json.dumps(result))
        self.assertNotIn('cookie', status['data'])
        self.assertNotIn('token', status['data'])
        payload = json.loads(calls[1].content)
        self.assertEqual(payload['plugins'], ['gying'])
        self.assertTrue(payload['refresh'])
