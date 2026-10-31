"""Browser UI and authenticated, same-origin JSON endpoints."""
import asyncio
import hmac
from pathlib import Path
import re
import secrets
import sqlite3

from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from backend.errors import SearchFailure
from backend.email_verification import VerificationMailer, normalize_email, code_identity
from backend.service import checkable_url, validate_preferences
from backend.store import digest
from backend.quark import QuarkError

STATIC = Path(__file__).parent / 'static'
COOKIE = 'rh_session'


class WebError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def reply(data, status=200):
    return JSONResponse(data, status_code=status, headers={'Cache-Control': 'no-store'})


class Web:
    def __init__(self, settings, store, service, upstream, quark=None):
        self.settings, self.store, self.service, self.upstream = settings, store, service, upstream
        self.quark = quark
        self.mailer = VerificationMailer()

    async def quark_account(self, request):
        user = self.user(request, write=request.method != 'GET')
        if request.method == 'POST':
            if not self.store.rate('quark-bind:' + str(user['id']), 10, 300):
                raise WebError('绑定操作过于频繁，请稍后重试。', 429)
            data = await self.body(request)
            # Ownership always comes from the authenticated browser session.
            if set(data) - {'cookie'}:
                raise WebError('绑定参数不正确。')
            return reply(await self.quark.bind(user['id'], data.get('cookie')))
        if request.method == 'DELETE':
            self.store.unbind_quark(user['id'])
        return reply(self.quark.status(user['id']))

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

    async def reveal_quark_cookie(self, request):
        user = self.user(request, write=True)
        if await self.body(request):
            raise WebError('请求参数不正确。')
        return reply({'cookie': self.quark.saved_cookie(user['id'])})

    async def body(self, request):
        try:
            data = await request.json()
        except ValueError:
            raise WebError('请求格式不正确。')
        if not isinstance(data, dict):
            raise WebError('请求格式不正确。')
        return data

    def profile(self, user):
        return {'id': str(user['id']), 'account_status': 'active', 'username': user['username'], 'is_admin': bool(user['is_admin']), 'can_manage_users': bool(user['is_admin']) and user['username'] == 'admin',
                'quota': self.store.quota(user['id']), 'preferences': self.store.preferences(user['id']),
                'csrf': user['csrf'], 'mcp_url': self.settings.resource,
                'preview': bool(getattr(self.upstream, 'preview', False)),
                'email': user.get('email'), 'email_binding_enabled': self.mailer.ready}

    async def revoke_connections(self, request):
        user = self.user(request, write=True)
        with self.store.connection(True) as db:
            db.execute('DELETE FROM tokens WHERE user_id=?', (user['id'],))
            db.execute('DELETE FROM codes WHERE user_id=?', (user['id'],))
        return reply({'ok': True})

    async def mcp_token(self, request):
        user = self.user(request, write=request.method != 'GET')
        data = {'mcp_url': self.settings.resource}
        if request.method == 'POST':
            # Always derive ownership from the session; never accept a target username.
            data['token'] = self.store.issue_mcp_token(user['username'], self.settings.resource)
        elif request.method == 'DELETE':
            self.store.revoke_mcp_token(user['username'])
        return reply({**data, **self.store.mcp_token_status(user['id'], self.settings.resource, reveal=True)})

    async def index(self, request):
        source = (STATIC / 'index.html').read_text(encoding='utf-8')
        # Version each asset by content, so a fresh HTML page never reuses stale CSS/JS.
        def version_asset(match):
            asset = match.group(2)
            version = digest((STATIC / asset).read_text(encoding='utf-8'))[:12]
            return match.group(1) + asset + '?v=' + version + match.group(3)
        source = re.sub(r'((?:src|href)="/assets/)([A-Za-z0-9_.-]+\.(?:css|js))(")', version_asset, source)
        return HTMLResponse(source, headers={
            'Cache-Control': 'no-cache', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'same-origin', 'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})

    async def session(self, request):
        user = self.store.web_user(request.cookies.get(COOKIE, ''))
        if user:
            return reply(self.profile(user))
        csrf = secrets.token_urlsafe(32)
        response = reply({'authenticated': False, 'csrf': csrf, 'registration_enabled': self.mailer.registration_open})
        response.delete_cookie('rh_login', path='/api/login')
        response.set_cookie('rh_login', csrf, secure=self.settings.secure, httponly=True,
                            samesite='strict', max_age=600, path='/api')
        return response

    def registration_csrf(self, request):
        if not self.mailer.registration_open:
            raise WebError('注册暂未开放。', 503)
        csrf = request.cookies.get('rh_login', '')
        if (request.headers.get('origin') != self.settings.base_url or not csrf or len(csrf) > 128 or
                not hmac.compare_digest(csrf, request.headers.get('x-csrf-token', ''))):
            raise WebError('请刷新页面后重试。', 403)
        return csrf

    def email_limit(self, request, action, maximum, window):
        ip = request.client.host if request.client else 'unknown'
        if not self.store.rate('email:' + action + ':' + digest(ip), maximum, window):
            raise WebError('操作过于频繁，请稍后再试。', 429)

    async def email_code(self, request):
        binding = request.url.path == '/api/email/code'
        if binding:
            user = self.user(request, write=True)
            if user.get('email'):
                raise WebError('账号已绑定邮箱。')
            if not self.mailer.ready:
                raise WebError('邮件服务暂不可用。', 503)
            csrf, purpose = user['csrf'], 'bind:' + str(user['id'])
        else:
            csrf, purpose = self.registration_csrf(request), 'register'
        self.email_limit(request, 'send', 3, 600)
        self.email_limit(request, 'send-day', 10, 86400)
        data = await self.body(request)
        if set(data) != {'email'}:
            raise WebError('请求参数不正确。')
        email = normalize_email(data['email'])
        # Mailbox limits apply across IPs, browser sessions, and both purposes.
        if (not self.store.rate('mail-minute:' + digest(email), 1, 60) or
                not self.store.rate('mail-day:' + digest(email), 5, 86400) or
                not self.store.rate('mail-global', 100, 3600)):
            raise WebError('验证码发送过于频繁，请稍后再试。', 429)
        result = {'ok': True, 'message': '如邮箱可用，验证码将发送至该邮箱，请检查收件箱和垃圾邮件。'}
        if not self.store.email_available(email):
            return reply(result)
        code = f'{secrets.randbelow(1000000):06d}'
        key, proof = code_identity(email, purpose, csrf, code)
        self.store.save_email_code(key, proof)
        try:
            await self.mailer.send(email, code)
        except Exception:
            self.store.remove_email_code(key, proof)
            raise WebError('邮件发送失败，请稍后重试或联系管理员。', 503) from None
        return reply(result)

    async def register_account(self, request):
        csrf = self.registration_csrf(request)
        self.email_limit(request, 'verify', 20, 300)
        if not self.store.rate('email-verify-global', 120, 300):
            raise WebError('操作过于频繁，请稍后再试。', 429)
        data = await self.body(request)
        if set(data) != {'username', 'email', 'password', 'code'}:
            raise WebError('注册参数不正确。')
        username, password, code = data['username'], data['password'], data['code']
        if (not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{2,63}', username)
                or username.lower() in {'admin', 'administrator', 'root', 'system', 'support'}):
            raise WebError('账号需为 3–64 位字母、数字、下划线、点或短横线，不能使用保留名称。')
        if not isinstance(password, str) or not 12 <= len(password) <= 256:
            raise WebError('密码需为 12–256 个字符。')
        if not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code):
            raise WebError('请输入 6 位邮箱验证码。')
        email = normalize_email(data['email'])
        key, proof = code_identity(email, 'register', csrf, code)
        try:
            verified = await asyncio.to_thread(self.store.verify_email_account, key, proof, email,
                username=username, password=password, limit=self.settings.default_limit)
        except sqlite3.IntegrityError:
            raise WebError('账号或邮箱已被使用。') from None
        if not verified:
            raise WebError('验证码错误、已过期或尝试次数过多，请重新获取。')
        return reply({'ok': True, 'message': '注册成功，请登录。'}, 201)

    async def bind_email(self, request):
        user = self.user(request, write=True)
        if not self.mailer.ready:
            raise WebError('邮件服务暂不可用。', 503)
        self.email_limit(request, 'verify', 20, 300)
        if not self.store.rate('email-verify-global', 120, 300):
            raise WebError('操作过于频繁，请稍后再试。', 429)
        data = await self.body(request)
        if set(data) != {'email', 'code'}:
            raise WebError('请求参数不正确。')
        email, code = normalize_email(data['email']), data['code']
        if not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code):
            raise WebError('请输入 6 位邮箱验证码。')
        key, proof = code_identity(email, 'bind:' + str(user['id']), user['csrf'], code)
        try:
            verified = self.store.verify_email_account(key, proof, email, user_id=user['id'])
        except sqlite3.IntegrityError:
            raise WebError('邮箱已被使用。') from None
        if not verified:
            raise WebError('验证码错误、已过期或邮箱已绑定。')
        return reply({'ok': True, 'email': email})

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
        response.delete_cookie('rh_login', path='/api')
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

    async def delete_history(self, request):
        user = self.user(request, write=True)
        ids = self.store.delete_history(user['id'], request.path_params.get('id'))
        if ids is None:
            raise WebError('搜索记录不存在或已删除', 404)
        return reply({'deleted_ids': ids, 'items': self.store.recent(user['id'])})

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
        if admin['username'] != 'admin':
            raise WebError('仅 admin 账号可以管理用户。', 403)
        if request.method == 'GET':
            query = request.query_params.get('q', '').strip()
            try:
                page = int(request.query_params.get('page', '1'))
                page_size = int(request.query_params.get('page_size', '20'))
            except ValueError:
                raise WebError('分页参数不正确。')
            if len(query) > 254 or not 1 <= page <= 1000000 or not 1 <= page_size <= 100:
                raise WebError('搜索或分页参数不正确。')
            return reply(self.store.user_page(query, page, page_size))
        data = await self.body(request)
        username = data.get('username', '')
        if not isinstance(username, str):
            raise WebError('账号格式不正确。')
        limit = data.get('daily_limit', self.settings.default_limit)
        if 'is_admin' in data and type(data['is_admin']) is not bool:
            raise WebError('账号状态格式不正确。')
        if type(limit) is not int:
            raise WebError('每日额度必须是整数。')
        if request.method == 'POST':
            password = data.get('password', '')
            if not isinstance(password, str):
                raise WebError('密码格式不正确。')
            self.store.add_user(username, password, limit, bool(data.get('is_admin', False)))
        else:
            target = self.store.managed_user(username)
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
        results = [{'state': 'unknown', 'summary': '暂不支持检测此链接。'} for _ in urls]
        items, indices = [], []
        for index, url in enumerate(urls):
            row = rows[url]
            if checkable_url(url, row['cloud_type']):
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
            except QuarkError as exc:
                return reply({'error': exc.message, 'code': exc.code}, exc.status)
            except (ValueError, sqlite3.IntegrityError):
                return reply({'error': '配置格式不正确、账号已存在或密码长度不足 12 位。'}, 400)
            except SearchFailure as exc:
                return reply({'error': str(exc)}, 502)
        return endpoint

    def routes(self):
        definitions = [('/', self.index, ['GET']), ('/profile', self.index, ['GET']), ('/api/session', self.session, ['GET']),
            ('/api/login', self.login, ['POST']), ('/api/logout', self.logout, ['POST']),
            ('/api/register/code', self.email_code, ['POST']), ('/api/register', self.register_account, ['POST']),
            ('/api/email/code', self.email_code, ['POST']), ('/api/email', self.bind_email, ['POST']),
            ('/api/search', self.search, ['POST']), ('/api/results/{id}', self.results, ['GET']),
            ('/api/history', self.history, ['GET']), ('/api/history', self.delete_history, ['DELETE']),
            ('/api/history/{id}', self.delete_history, ['DELETE']),
            ('/api/preferences', self.preferences, ['PUT']),
            ('/api/catalog', self.catalog, ['GET']), ('/api/password', self.password, ['POST']),
            ('/api/connections/revoke', self.revoke_connections, ['POST']),
            ('/api/mcp-token', self.mcp_token, ['GET', 'POST', 'DELETE']),
            ('/api/quark-account', self.quark_account, ['GET', 'POST', 'DELETE']),
            ('/api/quark-account/reveal', self.reveal_quark_cookie, ['POST']),
            ('/api/users', self.users, ['GET', 'POST', 'PATCH']),
            ('/api/check', self.check_links, ['POST'])]
        return [Route(path, self.wrap(handler), methods=methods) for path, handler, methods in definitions] + [
            Mount('/assets', StaticFiles(directory=STATIC))]
