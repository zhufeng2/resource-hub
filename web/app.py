"""Browser UI and authenticated, same-origin JSON endpoints."""
import asyncio
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
from urllib.parse import urlsplit

from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from backend.backend import SearchFailure
from backend.service import validate_preferences
from backend.store import digest
from backend.upstream import PROVIDERS

STATIC = Path(__file__).parent / 'static'
COOKIE = 'rh_session'


class WebError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def reply(data, status=200):
    return JSONResponse(data, status_code=status, headers={'Cache-Control': 'no-store'})


class Web:
    def __init__(self, settings, store, service, upstream):
        self.settings, self.store, self.service, self.upstream = settings, store, service, upstream

    def user(self, request, write=False, admin=False):
        user = self.store.web_user(request.cookies.get(COOKIE, ''))
        if not user:
            raise WebError('请先登录。', 401)
        if write and (request.headers.get('origin') != self.settings.base_url or not hmac.compare_digest(
                request.headers.get('x-csrf-token', ''), user['csrf'])):
            raise WebError('请求已失效，请刷新页面。', 403)
        if admin and not user['is_admin']:
            raise WebError('此操作需要管理员权限。', 403)
        ip = request.client.host if request.client else 'unknown'
        if not self.store.rate('web:' + digest(ip) + ':' + str(user['id']), 240, 60):
            raise WebError('请求过于频繁，请稍后再试。', 429)
        return user

    async def body(self, request):
        try:
            data = await request.json()
        except ValueError:
            raise WebError('请求格式不正确。')
        if not isinstance(data, dict):
            raise WebError('请求格式不正确。')
        return data

    def profile(self, user):
        return {'id': str(user['id']), 'account_status': 'active', 'username': user['username'], 'is_admin': bool(user['is_admin']),
                'quota': self.store.quota(user['id']), 'preferences': self.store.preferences(user['id']),
                'csrf': user['csrf'], 'mcp_url': self.settings.resource,
                'preview': bool(getattr(self.upstream, 'preview', False))}

    async def revoke_connections(self, request):
        user = self.user(request, write=True)
        with self.store.connection(True) as db:
            db.execute('DELETE FROM tokens WHERE user_id=?', (user['id'],))
            db.execute('DELETE FROM codes WHERE user_id=?', (user['id'],))
        return reply({'ok': True})

    async def index(self, request):
        return FileResponse(STATIC / 'index.html', headers={
            'Cache-Control': 'no-cache', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'same-origin', 'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})

    async def session(self, request):
        user = self.store.web_user(request.cookies.get(COOKIE, ''))
        if user:
            return reply(self.profile(user))
        csrf = secrets.token_urlsafe(32)
        response = reply({'authenticated': False, 'csrf': csrf})
        response.set_cookie('rh_login', csrf, secure=self.settings.secure, httponly=True,
                            samesite='strict', max_age=600, path='/api/login')
        return response

    async def login(self, request):
        ip = request.client.host if request.client else 'unknown'
        if not self.store.rate('web-login:' + digest(ip), 20, 300):
            raise WebError('登录尝试次数过多，请稍后重试。', 429)
        csrf = request.cookies.get('rh_login', '')
        if (request.headers.get('origin') != self.settings.base_url or not csrf or
                not hmac.compare_digest(csrf, request.headers.get('x-csrf-token', ''))):
            raise WebError('请刷新页面后重新登录。', 403)
        data = await self.body(request)
        username, password = data.get('username', ''), data.get('password', '')
        if not isinstance(username, str) or not isinstance(password, str) or len(username) > 64 or len(password) > 256:
            raise WebError('账号或密码格式不正确。')
        if not self.store.rate('user-login:' + digest(username), 20, 300):
            raise WebError('登录尝试次数过多，请稍后重试。', 429)
        user = await asyncio.to_thread(self.store.login, username, password)
        if not user:
            raise WebError('账号或密码错误，或账号已停用。', 401)
        self.store.web_logout(request.cookies.get(COOKIE, ''))
        token, user['csrf'] = self.store.web_session(user['id'])
        response = reply(self.profile(user))
        response.set_cookie(COOKIE, token, secure=self.settings.secure, httponly=True,
                            samesite='strict', max_age=7 * 86400, path='/')
        response.delete_cookie('rh_login', path='/api/login')
        return response

    async def logout(self, request):
        self.user(request, write=True)
        self.store.web_logout(request.cookies.get(COOKIE, ''))
        response = reply({'ok': True})
        response.delete_cookie(COOKIE, path='/')
        return response

    async def search(self, request):
        user = self.user(request, write=True)
        data = await self.body(request)
        options = self.store.preferences(user['id'])
        if 'options' in data:
            options.update(validate_preferences(data['options']))
        result = await self.service.search(user, data.get('query', ''), data.get('request_id', ''), options,
                                           refresh=data.get('refresh', False))
        return reply(result, 429 if result.get('error') == 'daily_limit_reached' else 200)

    async def results(self, request):
        user = self.user(request)
        return reply(self.service.page(user['id'], self.store.search(user['id'], request.path_params['id']), limit=200))

    async def history(self, request):
        user = self.user(request)
        return reply({'items': self.store.recent(user['id'])})

    async def preferences(self, request):
        user = self.user(request, write=True)
        value = self.store.preferences(user['id'])
        value.update(validate_preferences(await self.body(request)))
        return reply(self.store.preferences(user['id'], value))

    async def catalog(self, request):
        self.user(request)
        return reply(await self.upstream.catalog())

    async def password(self, request):
        user = self.user(request, write=True)
        data = await self.body(request)
        old, new = data.get('current_password', ''), data.get('password', '')
        if not isinstance(old, str) or not isinstance(new, str) or len(old) > 256:
            raise WebError('密码格式不正确。')
        if not self.store.rate('password:' + str(user['id']), 10, 300):
            raise WebError('尝试次数过多，请稍后重试。', 429)
        verified = await asyncio.to_thread(self.store.login, user['username'], old)
        if not verified:
            raise WebError('当前密码不正确。')
        self.store.change_user(user['username'], password=new)
        response = reply({'ok': True, 'message': '密码已更新，请重新登录。'})
        response.delete_cookie(COOKIE, path='/')
        return response

    async def users(self, request):
        admin = self.user(request, write=request.method != 'GET', admin=True)
        if request.method == 'GET':
            return reply({'items': self.store.users()})
        data = await self.body(request)
        username = data.get('username', '')
        if not isinstance(username, str):
            raise WebError('账号格式不正确。')
        limit = data.get('daily_limit', self.settings.default_limit)
        if type(limit) is not int:
            raise WebError('每日额度必须是整数。')
        if request.method == 'POST':
            password = data.get('password', '')
            if not isinstance(password, str):
                raise WebError('密码格式不正确。')
            self.store.add_user(username, password, limit, bool(data.get('is_admin', False)))
        else:
            target = next((u for u in self.store.users() if u['username'] == username), None)
            if not target:
                raise WebError('账号不存在。', 404)
            if target['id'] == admin['id'] and (data.get('enabled') is False or data.get('is_admin') is False):
                raise WebError('请使用另一个管理员账号修改当前账号权限。')
            for key in ('enabled', 'is_admin'):
                if key in data and type(data[key]) is not bool:
                    raise WebError('账号状态格式不正确。')
            password = data.get('password') or None
            if password is not None and not isinstance(password, str):
                raise WebError('密码格式不正确。')
            self.store.change_user(username, limit=limit, password=password,
                                   enabled=data.get('enabled'), is_admin=data.get('is_admin'))
        return reply({'ok': True})

    async def bindings(self, request):
        user = self.user(request, write=request.method == 'POST')
        if request.method == 'POST':
            data = await self.body(request)
            provider, label = data.get('provider'), data.get('label', '')
            if not isinstance(label, str) or not isinstance(provider, str):
                raise WebError('请选择搜索源并填写账号名称。')
            label = label.strip()
            if provider not in PROVIDERS or not 1 <= len(label) <= 64:
                raise WebError('请选择搜索源并填写账号名称。')
            catalog = await self.upstream.catalog()
            if provider not in catalog['plugins']:
                raise WebError('管理员尚未启用此搜索源。')
            upstream_hash = await self.upstream.create_binding(provider)
            self.store.add_binding(user['id'], provider, label, upstream_hash)
        return reply({'items': [{k: b[k] for k in ('id', 'provider', 'label', 'created')}
                                for b in self.store.bindings(user['id'])]})

    async def binding_action(self, request):
        user = self.user(request, write=True)
        binding = self.store.binding(user['id'], request.path_params['id'])
        if not binding:
            raise WebError('账号记录不存在。', 404)
        data = await self.body(request)
        action = data.get('action', '')
        if not self.store.rate('binding:' + str(user['id']), 60, 60):
            raise WebError('操作过于频繁，请稍后重试。', 429)
        if action == 'remove':
            result = await self.upstream.binding_action(binding, 'logout', {})
            if not result['success']:
                raise WebError('退出搜索源账号失败，请稍后重试。')
            self.store.remove_binding(user['id'], binding['id'])
            return reply({'success': True})
        if action == 'update_config':
            url = data.get('base_url', '')
            parts = urlsplit(url)
            allowed = set(os.getenv('SOURCE_SITE_HOSTS', '').split(','))
            if (not user['is_admin'] or parts.scheme != 'https' or parts.hostname not in allowed
                    or parts.username or parts.password or parts.query or parts.fragment):
                raise WebError('此站点地址未获管理员允许。', 403)
        if action == 'test_search':
            async def execute(query, timeout):
                response = await self.upstream.request(f"/{binding['provider']}/{binding['upstream_hash']}",
                    {'action': 'test_search', 'keyword': query, 'max_results': 30}, timeout=120)
                if not response.get('success'):
                    raise SearchFailure('搜索源未能完成搜索，本次不扣额度。')
                groups = {}
                for row in response.get('data', {}).get('results', []):
                    for link in row.get('links', []):
                        groups.setdefault(link.get('type', 'others'), []).append({
                            **link, 'note': row.get('title', ''), 'source': binding['provider'],
                            'datetime': row.get('datetime', '')})
                return self.upstream.normalize({'merged_by_type': groups})
            return reply(await self.service.search(user, data.get('keyword', ''), data.get('request_id', ''),
                execute=execute, identity=binding['id']))
        if action in ('set_channels', 'set_user_ids'):
            key = 'channels' if action == 'set_channels' else 'user_ids'
            items = data.get(key)
            if not isinstance(items, list) or len(items) > 80 or any(
                    not isinstance(x, str) or not re.fullmatch(r'[\w@.-]{1,80}', x) for x in items):
                raise WebError('频道或用户 ID 格式不正确。')
        for key, value in data.items():
            if isinstance(value, str) and len(value) > 2048:
                raise WebError('输入内容过长。')
        return reply(await self.upstream.binding_action(binding, action, data))

    async def check_links(self, request):
        user = self.user(request, write=True)
        if not self.store.rate('check:' + str(user['id']), 10, 60):
            raise WebError('检测过于频繁，请稍后重试。', 429)
        data = await self.body(request)
        row = self.store.search(user['id'], data.get('search_id', ''))
        page = self.service.page(user['id'], row, limit=200)
        if 'error' in page:
            raise WebError('请先搜索，再检测结果。')
        urls = data.get('urls', [])
        if not isinstance(urls, list) or not 1 <= len(urls) <= 20 or not all(isinstance(x, str) for x in urls):
            raise WebError('每次可检测 1–20 个结果。')
        rows = {r['url']: r for r in page['results']}
        if any(url not in rows for url in urls):
            raise WebError('只能检测本次搜索返回的链接。', 403)
        hosts = {'quark': {'pan.quark.cn'}, 'baidu': {'pan.baidu.com', 'yun.baidu.com'},
                 'aliyun': {'alipan.com', 'www.alipan.com', 'www.aliyundrive.com'},
                 'tianyi': {'cloud.189.cn'}, 'uc': {'drive.uc.cn'}, '115': {'115.com'},
                 '123': {'www.123pan.com', 'www.123684.com', 'www.123865.com'}}
        results = [{'state': 'unknown', 'summary': '暂不支持检测此链接。'} for _ in urls]
        items, indices = [], []
        for index, url in enumerate(urls):
            parts = urlsplit(url)
            row = rows[url]
            if (parts.scheme == 'https' and parts.hostname in hosts.get(row['cloud_type'], set())
                    and not parts.username and not parts.password and parts.port in (None, 443)):
                items.append({'url': url, 'disk_type': row['cloud_type'], 'password': row.get('password', '')})
                indices.append(index)
        if items:
            checked = await self.upstream.check_links(items)
            for index, result in zip(indices, checked):
                results[index] = result
        return reply({'results': results})

    def wrap(self, handler):
        async def endpoint(request):
            try:
                return await handler(request)
            except WebError as exc:
                return reply({'error': exc.message}, exc.status)
            except (ValueError, sqlite3.IntegrityError):
                return reply({'error': '配置格式不正确、账号已存在或密码长度不足 12 位。'}, 400)
            except SearchFailure as exc:
                return reply({'error': str(exc)}, 502)
        return endpoint

    def routes(self):
        definitions = [('/', self.index, ['GET']), ('/profile', self.index, ['GET']), ('/api/session', self.session, ['GET']),
            ('/api/login', self.login, ['POST']), ('/api/logout', self.logout, ['POST']),
            ('/api/search', self.search, ['POST']), ('/api/results/{id}', self.results, ['GET']),
            ('/api/history', self.history, ['GET']), ('/api/preferences', self.preferences, ['PUT']),
            ('/api/catalog', self.catalog, ['GET']), ('/api/password', self.password, ['POST']),
            ('/api/connections/revoke', self.revoke_connections, ['POST']),
            ('/api/users', self.users, ['GET', 'POST', 'PATCH']),
            ('/api/bindings', self.bindings, ['GET', 'POST']),
            ('/api/bindings/{id}', self.binding_action, ['POST']), ('/api/check', self.check_links, ['POST'])]
        return [Route(path, self.wrap(handler), methods=methods) for path, handler, methods in definitions] + [
            Mount('/assets', StaticFiles(directory=STATIC))]
