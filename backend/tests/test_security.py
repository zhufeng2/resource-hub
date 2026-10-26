"""Regression tests for request limits, upstream boundaries and data retention."""
import asyncio
import gzip
import os
import time
import unittest
from unittest.mock import patch

import httpx

from backend.app import Guard
from backend.errors import SearchFailure
from backend.service import checkable_url
from backend.upstream import Upstream
from . import test_service as fixtures
from .test_service import PASSWORD


class Boundaries(unittest.IsolatedAsyncioTestCase):
    async def test_stream_limit_including_login_and_compression(self):
        real_client = httpx.AsyncClient
        for fixed_token in ('', 'test-token'):
            for content in (b'x' * 4_000_001, gzip.compress(b'x' * 4_000_001)):
                headers = {'content-encoding': 'gzip'} if content[:2] == b'\x1f\x8b' else {}
                def handler(request):
                    return httpx.Response(200, content=content, headers=headers)
                def factory(**kwargs):
                    return real_client(**kwargs, transport=httpx.MockTransport(handler))
                with patch.dict(os.environ, {'PANSOU_BASE_URL': 'https://pansou.example',
                        'PANSOU_API_TOKEN': fixed_token, 'PANSOU_USERNAME': 'test', 'PANSOU_PASSWORD': PASSWORD}), \
                        patch('backend.upstream.httpx.AsyncClient', factory):
                    with self.assertRaises(SearchFailure):
                        await Upstream().request('/api/search', {})

    async def test_compressed_json_still_works(self):
        real_client = httpx.AsyncClient
        def factory(**kwargs):
            return real_client(**kwargs, transport=httpx.MockTransport(lambda request:
                httpx.Response(200, content=gzip.compress(b'{"total":0}'), headers={'content-encoding': 'gzip'})))
        with patch.dict(os.environ, {'PANSOU_BASE_URL': 'https://pansou.example', 'PANSOU_API_TOKEN': 'test'}), \
                patch('backend.upstream.httpx.AsyncClient', factory):
            self.assertEqual(await Upstream().request('/api/search'), {'total': 0})

    async def test_body_limits_for_delete_and_chunked_requests(self):
        for method in ('POST', 'DELETE'):
            called, sent = [], []
            async def app(*args):
                called.append(True)
            async def receive():
                return {'type': 'http.request', 'body': b'x' * 9000, 'more_body': True}
            async def send(message):
                sent.append(message)
            await Guard(app, None, None)({'type': 'http', 'headers': [], 'path': '/api/history',
                'method': method}, receive, send)
            self.assertFalse(called)
            self.assertEqual(sent[0]['status'], 413)

    async def test_body_timeout(self):
        sent = []
        async def app(*args):
            self.fail('timed out request reached app')
        async def receive():
            raise asyncio.TimeoutError
        async def send(message):
            sent.append(message)
        await Guard(app, None, None)({'type': 'http', 'headers': [], 'path': '/api/search',
            'method': 'POST'}, receive, send)
        self.assertEqual(sent[0]['status'], 408)

    def test_upstream_requires_explicit_destination(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            Upstream()

    def test_link_check_rejects_malformed_and_private_targets(self):
        for url in ('https://pan.quark.cn:bad/s/test', 'https://[broken',
                    'https://pan.quark.cn:8443/s/test', 'https://user@pan.quark.cn/s/test',
                    'https://127.0.0.1/s/test', 'https://pan.quark.cn.attacker.example/s/test'):
            self.assertFalse(checkable_url(url, 'quark'))
        self.assertTrue(checkable_url('https://pan.quark.cn/s/test', 'quark'))


class Retention(unittest.TestCase):
    setUp = fixtures.ServiceTests.setUp
    cleanup_temp = fixtures.ServiceTests.cleanup_temp

    def test_expired_content_erased_without_deleting_ledger(self):
        user = self.store.login('alice', PASSWORD)
        row, _ = self.store.reserve(user['id'], 'retention', 'private keyword')
        self.store.finish(row['id'], {'results': []})
        with patch('backend.store.time.time', return_value=time.time() + 86401):
            self.store.cleanup()
        with self.store.connection() as db:
            saved = db.execute('SELECT * FROM searches WHERE id=?', (row['id'],)).fetchone()
        self.assertEqual(saved['query'], '')
        self.assertIsNone(saved['result'])
        self.assertEqual(saved['request_id'], 'retention')
        self.assertEqual(saved['status'], 'done')

    def test_mcp_rate_limit_applies_to_valid_token(self):
        token = self.store.issue_mcp_token('alice', self.settings.resource)
        user = self.store.login('alice', PASSWORD)
        for _ in range(120):
            self.store.rate('mcp:' + str(user['id']), 120, 60)
        response = self.client.post('/mcp', json={}, headers={'Authorization': 'Bearer ' + token})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers['retry-after'], '60')
