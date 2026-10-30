"""Quark binding, credential boundaries and tenant isolation; no real drive calls."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from backend.quark import QuarkError, validate_cookie
from . import test_web as web_fixtures
from .test_service import PASSWORD


class QuarkTests(unittest.TestCase):
    setUp = web_fixtures.WebTests.setUp
    cleanup_temp = web_fixtures.WebTests.cleanup_temp
    login = web_fixtures.WebTests.login
    rpc = web_fixtures.WebTests.rpc
    tool = web_fixtures.WebTests.tool
    web_login = web_fixtures.WebTests.web_login

    def bind(self, cookie='session=alice-private'):
        headers = self.web_login()
        with patch.object(self.app.state.quark, 'run', new=AsyncMock(return_value={'total': 100})):
            response = self.client.post('/api/quark-account', json={
                'cookie': cookie}, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_binding_encryption_no_echo_and_csrf(self):
        self.assertEqual(self.client.get('/api/quark-account').status_code, 401)
        headers = self.web_login()
        self.assertEqual(self.client.post('/api/quark-account', json={'cookie': 'session=secret'}).status_code, 403)
        self.assertEqual(self.client.delete('/api/quark-account').status_code, 403)
        self.assertEqual(self.client.post('/api/quark-account', json={
            'cookie': 'session=secret', 'user_id': 2}, headers=headers).status_code, 400)
        bound = self.bind()
        self.assertTrue(bound['bound'])
        self.assertNotIn('cookie', json.dumps(bound))
        uid = self.store.login('alice', PASSWORD)['id']
        with self.store.connection() as db:
            raw = bytes(db.execute('SELECT ciphertext FROM quark_accounts WHERE user_id=?', (uid,)).fetchone()[0])
        self.assertNotIn(b'alice-private', raw)
        self.assertEqual(self.store.quark_account(uid, secret=True)['cookie'], 'session=alice-private')
        self.web_login('bob')
        self.assertEqual(self.client.get('/api/quark-account').json(), {'bound': False})

    def test_failed_validation_keeps_original_and_rebind_rotates_namespace(self):
        first = self.bind()
        headers = self.web_login()
        with patch.object(self.app.state.quark, 'run', new=AsyncMock(return_value={'error': 'expired'})):
            response = self.client.post('/api/quark-account', json={'cookie': 'session=invalid'}, headers=headers)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get('/api/quark-account').json()['id'], first['id'])
        second = self.bind('session=new-private')
        self.assertNotEqual(first['id'], second['id'])
        self.assertFalse(self.client.delete('/api/quark-account', headers=self.web_login()).json()['bound'])

    def test_cookie_reveal_is_explicit_csrf_protected_and_owner_scoped(self):
        self.assertEqual(self.client.post('/api/quark-account/reveal', json={}).status_code, 401)
        self.bind()
        headers = self.web_login()
        self.assertEqual(self.client.post('/api/quark-account/reveal', json={}).status_code, 403)
        self.assertNotIn('cookie', self.client.get('/api/quark-account').json())
        revealed = self.client.post('/api/quark-account/reveal', json={}, headers=headers)
        self.assertEqual(revealed.json(), {'cookie': 'session=alice-private'})
        self.assertEqual(revealed.headers['cache-control'], 'no-store')
        self.assertIn(self.client.get('/api/quark-account/reveal').status_code, (404, 405))
        other = self.web_login('bob')
        self.assertEqual(self.client.post('/api/quark-account/reveal', json={}, headers=other).status_code, 404)
        self.assertEqual(self.client.post('/api/quark-account/reveal', json={'user_id': 1}, headers=other).status_code, 400)

    def test_mcp_ownership_permissions_records_and_unbinding(self):
        self.bind()
        alice, _, _ = self.login()
        bob, _, _ = self.login('bob')
        args = {'share_url': 'https://pan.quark.cn/s/example', 'fid': 'source',
                'to_parent_fid': 'destination', 'request_id': 'same-id', 'execute': True}
        self.assertEqual(self.tool(bob['access_token'], 'quark_save_file', args)['error'], 'quark_not_bound')
        self.bind()
        uid = self.store.login('alice', PASSWORD)['id']
        account = self.store.quark_account(uid)
        path = self.app.state.quark.journal(uid, account['id'], 'same-id')
        path.write_text('{"phase":"submitted","taskId":"private-task"}', encoding='utf-8')
        async def fake(cookie, action, args=None, journal=None, execute=False):
            self.assertEqual(cookie, 'session=alice-private')
            self.assertEqual(journal, path)
            return {'phase': 'verified'}
        with patch.object(self.app.state.quark, 'run', side_effect=fake):
            self.assertEqual(self.tool(alice['access_token'], 'quark_save_file', args)['phase'], 'verified')
            self.assertEqual(self.tool(bob['access_token'], 'quark_operation_status', {'request_id': 'same-id'})['error'], 'quark_not_bound')
        self.bind('session=changed')
        self.assertEqual(self.tool(alice['access_token'], 'quark_operation_status', {'request_id': 'same-id'})['error'], 'operation_not_found')
        with self.assertRaises(QuarkError):
            self.app.state.quark.journal(uid, account['id'], '../../other')

    def test_tool_schemas_do_not_expose_credentials_or_user_identity(self):
        tokens, _, _ = self.login()
        tools = self.rpc(tokens['access_token'], 'tools/list')['result']['tools']
        for tool in tools:
            properties = tool['inputSchema'].get('properties', {})
            self.assertFalse({'cookie', 'token', 'user_id', 'cookie_file', 'journal', 'task_id'} & set(properties))
        save = next(t for t in tools if t['name'] == 'quark_save_file')
        self.assertFalse(save['inputSchema']['properties']['execute']['default'])

    def test_large_text_json_escaping_and_other_request_limits(self):
        self.bind()
        tokens, _, _ = self.login()
        headers = {'Authorization': 'Bearer ' + tokens['access_token'],
                   'Accept': 'application/json, text/event-stream', 'Content-Type': 'application/json',
                   'MCP-Protocol-Version': '2025-03-26'}
        content = '\u89c2' * 10000  # 30KB UTF-8, 60KB when JSON escapes Chinese.
        args = {'parent_fid': 'folder', 'name': 'Guide.md', 'content': content, 'request_id': 'large-guide'}
        payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                   'params': {'name': 'quark_create_text_file', 'arguments': args}}
        raw = json.dumps(payload, ensure_ascii=True).encode()
        self.assertGreater(len(raw), 16384)
        with patch.object(self.app.state.quark, 'run', new=AsyncMock(return_value={'phase': 'preview'})) as run:
            response = self.client.post('/mcp', content=raw, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()['result'].get('isError'))
            self.assertEqual(run.call_args.args[2]['content'], content)
            args['content'] = '\u89c2' * 11000
            self.assertEqual(self.tool(tokens['access_token'], 'quark_create_text_file', args)['error'], 'text_size_limit')
            self.assertEqual(run.await_count, 1)
        payload['params']['name'] = 'quark_list_files'
        self.assertEqual(self.client.post('/mcp', content=json.dumps(payload).encode(), headers=headers).status_code, 413)
        self.assertEqual(self.client.post('/mcp', content=b'x' * (256 * 1024 + 1), headers=headers).status_code, 413)

    def test_missing_key_fails_closed_and_cookie_validation(self):
        self.bind()
        uid = self.store.login('alice', PASSWORD)['id']
        self.store.path.with_name(self.store.path.name + '.quark.key').unlink()
        result = asyncio.run(self.app.state.quark.call(uid, 'list'))
        self.assertEqual(result['error'], 'credential_unavailable')
        for value in ('session=secret\r\nOther: bad', 'bad', {}, 'session=你好'):
            with self.assertRaises(QuarkError):
                validate_cookie(value)
        self.assertEqual(validate_cookie('Cookie: session=ok; other=a=b'), 'session=ok; other=a=b')

    def test_runtime_receives_cookie_only_on_stdin_and_errors_are_redacted(self):
        class Process:
            returncode = 0
            async def communicate(inner, raw):
                payload = json.loads(raw)
                self.assertEqual(payload['cookie'], 'session=private')
                return b'{"files":[]}', b''
        async def spawn(*args, **kwargs):
            self.assertNotIn('private', str(args))
            self.assertNotIn('QUARK_SECRET_KEY', kwargs['env'])
            self.assertIsNotNone(kwargs['stdin'])
            return Process()
        with patch('backend.quark.asyncio.create_subprocess_exec', side_effect=spawn):
            result = asyncio.run(self.app.state.quark.run('session=private', 'list'))
        self.assertEqual(result, {'files': []})

    def test_swapped_encrypted_credentials_are_rejected(self):
        self.bind()
        alice = self.store.login('alice', PASSWORD)['id']
        bob = self.store.login('bob', PASSWORD)['id']
        self.store.bind_quark(bob, 'session=bob')
        with self.store.connection(True) as db:
            ciphertext = db.execute('SELECT ciphertext FROM quark_accounts WHERE user_id=?', (alice,)).fetchone()[0]
            db.execute('UPDATE quark_accounts SET ciphertext=? WHERE user_id=?', (ciphertext, bob))
        self.assertEqual(asyncio.run(self.app.state.quark.call(bob, 'list'))['error'], 'credential_unavailable')

    def test_real_node_bridge_without_network(self):
        result = asyncio.run(self.app.state.quark.run('session=dummy-private', 'unsupported'))
        self.assertEqual(result['error'], 'quark_operation_failed')
        self.assertNotIn('dummy-private', json.dumps(result))

    def test_busy_user_cannot_consume_all_quark_workers(self):
        self.bind()
        uid = self.store.login('alice', PASSWORD)['id']
        self.app.state.quark.inflight[uid] = 2
        result = asyncio.run(self.app.state.quark.call(uid, 'list'))
        self.assertEqual(result['error'], 'quark_busy')

    def test_worker_capacity_timeout_does_not_spawn_or_leak_a_slot(self):
        from backend.quark import QuarkService
        adapter = QuarkService(self.store)
        async def timeout(awaitable, seconds):
            awaitable.close()
            raise asyncio.TimeoutError
        async def verify():
            await adapter.slots.acquire()
            before = adapter.slots._value
            with patch('backend.quark.asyncio.wait_for', side_effect=timeout), \
                    self.assertRaises(QuarkError) as error:
                async with adapter.available_slot():
                    self.fail('slot should not have been acquired')
            self.assertEqual(error.exception.code, 'quark_busy')
            self.assertEqual(adapter.slots._value, before)
            adapter.slots.release()
        asyncio.run(verify())

    def test_manage_and_bulk_transfer_tools_use_authenticated_namespace(self):
        self.bind()
        tokens, _, _ = self.login()
        uid = self.store.login('alice', PASSWORD)['id']
        account = self.store.quark_account(uid)
        cases = [
            ('quark_create_text_file', {'parent_fid': 'folder', 'name': 'Guide.md', 'content': '# Guide',
              'request_id': 'text1'}, 'create_text'),
            ('quark_reset_folder_progress', {'folder_fid': 'folder', 'folder_name': 'Series',
              'request_id': 'reset1'}, 'reset_progress'),
            ('quark_rename', {'fid': 'folder', 'name': 'Series', 'request_id': 'rename1'}, 'rename'),
            ('quark_move', {'fids': ['folder'], 'to_parent_fid': 'target', 'request_id': 'move1'}, 'move'),
            ('quark_save_entries', {'share_url': 'https://pan.quark.cn/s/example', 'fids': ['folder', 'episode'],
              'source_parent_fid': '0', 'to_parent_fid': 'target', 'request_id': 'batch1'}, 'save_entries')]
        for tool, args, action in cases:
            async def fake(cookie, actual, params=None, journal=None, execute=False):
                self.assertEqual(cookie, 'session=alice-private')
                self.assertEqual(actual, action)
                self.assertEqual(journal, self.app.state.quark.journal(uid, account['id'], args['request_id']))
                self.assertFalse(execute)
                return {'phase': 'preview'}
            with patch.object(self.app.state.quark, 'run', side_effect=fake):
                self.assertEqual(self.tool(tokens['access_token'], tool, args)['phase'], 'preview')

    def test_reset_continues_without_repeated_mcp_calls_and_status_does_not_submit(self):
        self.bind()
        uid = self.store.login('alice', PASSWORD)['id']
        q = self.app.state.quark
        args = {'folderFid': 'folder', 'folderName': 'Series', 'explicitReset': True}
        real_sleep = asyncio.sleep
        async def quick_sleep(seconds):
            await real_sleep(0)
        async def verify():
            calls = 0
            async def run(cookie, action, params=None, journal=None, execute=False):
                nonlocal calls
                self.assertEqual(action, 'reset_progress')
                calls += 1
                return {'phase': 'verified' if calls == 3 else 'in_progress', 'verified': calls * 40, 'skipped': 0}
            with patch.object(q, 'run', side_effect=run), patch('backend.quark.asyncio.sleep', side_effect=quick_sleep):
                first = await q.call(uid, 'reset_progress', args, 'auto-reset', True)
                self.assertTrue(first['background_running'])
                repeat = await q.call(uid, 'reset_progress', args, 'auto-reset', True)
                self.assertTrue(repeat['background_running'])
                conflict = await q.call(uid, 'reset_progress', {**args, 'folderName': 'Other'}, 'auto-reset', True)
                self.assertEqual(conflict['error'], 'plan_conflict')
                self.assertEqual(calls, 1)
                await next(iter(q.reset_jobs.values()))['task']
                result = await q.call(uid, 'operation', request_id='auto-reset')
                self.assertEqual(result['phase'], 'verified')
                self.assertFalse(result['background_running'])
                self.assertEqual(calls, 3)
        asyncio.run(verify())

    def test_reset_stops_on_rebinding_or_repeated_stagnation(self):
        self.bind()
        uid = self.store.login('alice', PASSWORD)['id']
        q = self.app.state.quark
        real_sleep = asyncio.sleep
        async def quick_sleep(seconds):
            await real_sleep(0)
        async def verify():
            args = {'folderFid': 'folder', 'folderName': 'Series', 'explicitReset': True}
            with patch.object(q, 'run', new=AsyncMock(return_value={'phase': 'in_progress', 'verified': 0, 'skipped': 0})) as run, \
                    patch('backend.quark.asyncio.sleep', side_effect=quick_sleep):
                await q.call(uid, 'reset_progress', args, 'stagnant', True)
                await next(iter(q.reset_jobs.values()))['task']
                self.assertEqual(run.await_count, 4)
                await q.call(uid, 'reset_progress', args, 'rebind-reset', True)
                job = next(j for j in q.reset_jobs.values() if j['running'])
                before = run.await_count
                self.store.bind_quark(uid, 'session=rebound')
                await job['task']
                self.assertEqual(run.await_count, before)
                self.assertFalse(job['running'])
        asyncio.run(verify())
