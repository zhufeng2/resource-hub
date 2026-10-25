"""Public-client OAuth authorization code + S256 PKCE, DCR and rotating refresh tokens."""
import asyncio
import hmac
import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from .store import digest

NO_STORE = {'Cache-Control': 'no-store', 'Pragma': 'no-cache'}


def error(name, status=400):
    return JSONResponse({'error': name}, status_code=status, headers=NO_STORE)


def callback(uri, params):
    parts = urlsplit(uri)
    query = parse_qsl(parts.query, keep_blank_values=True) + list(params.items())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))


def login_page(ticket, message='', status=200):
    message, ticket = html.escape(message), html.escape(ticket, quote=True)
    response = HTMLResponse(f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>连接 Resource Hub</title>
<link rel="stylesheet" href="/assets/style.css"><body>
<header class="header"><a class="brand" href="/"><span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span><span>Resource Hub<span class="brand-caption">资源检索</span></span></a></header>
<main><section class="login-view"><div class="login-card"><span class="eyebrow">CONNECT YOUR WORKSPACE</span><h1>连接资源搜索</h1>
<p class="muted">登录后，允许 ChatGPT 使用此账号搜索资源。</p>
<p class="form-error" role="alert">{message}</p><form method="post" action="/oauth/authorize">
<input type="hidden" name="ticket" value="{ticket}">
<label for="username">账号<input id="username" name="username" autocomplete="username" maxlength="64" required></label>
<label for="password">密码<input id="password" type="password" name="password" autocomplete="current-password" maxlength="256" required></label>
<button class="primary full" name="action" value="allow">登录并授权搜索 ↗</button>
<button class="text-button full" name="action" value="deny" formnovalidate>取消</button></form>
<p class="login-help">需要账号或忘记密码？请联系管理员。</p></div></section></main></body></html>''',
        status_code=status, headers={**NO_STORE, 'Referrer-Policy': 'no-referrer',
            'Content-Security-Policy': "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            'X-Frame-Options': 'DENY', 'X-Content-Type-Options': 'nosniff'})
    return response


class OAuth:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store

    def limited(self, request, area, maximum=30, window=300):
        # Only trust proxy-derived client addresses when uvicorn is configured for the known proxy.
        ip = request.client.host if request.client else 'unknown'
        return not self.store.rate(area + ':' + digest(ip), maximum, window)

    async def resource_metadata(self, request):
        return JSONResponse({'resource': self.settings.resource,
            'authorization_servers': [self.settings.base_url], 'scopes_supported': ['search'],
            'bearer_methods_supported': ['header'], 'resource_name': 'Resource Hub 搜索'})

    async def metadata(self, request):
        base = self.settings.base_url
        return JSONResponse({'issuer': base, 'authorization_response_iss_parameter_supported': True,
            'authorization_endpoint': base + '/oauth/authorize', 'token_endpoint': base + '/oauth/token',
            'registration_endpoint': base + '/oauth/register', 'revocation_endpoint': base + '/oauth/revoke',
            'response_types_supported': ['code'], 'grant_types_supported': ['authorization_code', 'refresh_token'],
            'token_endpoint_auth_methods_supported': ['none'], 'revocation_endpoint_auth_methods_supported': ['none'],
            'code_challenge_methods_supported': ['S256'], 'scopes_supported': ['search']})

    async def register(self, request):
        if self.limited(request, 'register', 10, 3600):
            return error('rate_limit_exceeded', 429)
        try:
            data = await request.json()
        except ValueError:
            return error('invalid_client_metadata')
        if not isinstance(data, dict):
            return error('invalid_client_metadata')
        redirects = data.get('redirect_uris')
        if (not isinstance(redirects, list) or not 1 <= len(redirects) <= 5
                or any(not isinstance(uri, str) or uri not in self.settings.redirect_uris for uri in redirects)):
            return error('invalid_redirect_uri')
        grants = data.get('grant_types', ['authorization_code', 'refresh_token'])
        if (data.get('token_endpoint_auth_method', 'none') != 'none'
                or data.get('response_types', ['code']) != ['code']
                or not isinstance(grants, list) or not all(isinstance(g, str) for g in grants)
                or not set(grants).issubset(
                    {'authorization_code', 'refresh_token'})):
            return error('invalid_client_metadata')
        client_id = self.store.register(redirects)
        return JSONResponse({'client_id': client_id, 'redirect_uris': redirects,
            'token_endpoint_auth_method': 'none', 'grant_types': ['authorization_code', 'refresh_token'],
            'response_types': ['code'], 'scope': 'search'}, status_code=201, headers=NO_STORE)

    async def authorize_get(self, request):
        if self.limited(request, 'authorize', 60):
            return error('rate_limit_exceeded', 429)
        p = dict(request.query_params)
        # Never redirect errors to an unregistered or no longer allowlisted URI.
        if (p.get('redirect_uri') not in self.settings.redirect_uris
                or p.get('redirect_uri') not in self.store.client_redirects(p.get('client_id', ''))):
            return error('invalid_client_or_redirect_uri')
        invalid = None
        if p.get('response_type') != 'code':
            invalid = 'unsupported_response_type'
        elif p.get('resource') != self.settings.resource:
            invalid = 'invalid_target'
        elif p.get('scope', 'search') != 'search':
            invalid = 'invalid_scope'
        elif (p.get('code_challenge_method') != 'S256'
                or not re.fullmatch(r'[A-Za-z0-9_-]{43}', p.get('code_challenge', ''))
                or len(p.get('state', '')) > 1024):
            invalid = 'invalid_request'
        if invalid:
            return self.redirect(p, error=invalid)
        ticket = self.store.ticket(p)
        response = login_page(ticket)
        response.set_cookie('rh_authorize', ticket, max_age=600, httponly=True,
                            secure=self.settings.secure, samesite='lax', path='/oauth/authorize')
        return response

    def redirect(self, p, **values):
        return RedirectResponse(callback(p['redirect_uri'], {
            **values, 'state': p.get('state', ''), 'iss': self.settings.base_url}),
            status_code=303, headers=NO_STORE)

    async def authorize_post(self, request):
        if self.limited(request, 'login', 20):
            return error('rate_limit_exceeded', 429)
        if request.headers.get('origin', self.settings.base_url) != self.settings.base_url:
            return error('invalid_origin', 403)
        form = await request.form()
        ticket = str(form.get('ticket', ''))
        cookie = request.cookies.get('rh_authorize', '')
        p = self.store.ticket_params(ticket)
        if (not ticket or not hmac.compare_digest(ticket, cookie) or not p
                or p['redirect_uri'] not in self.settings.redirect_uris):
            return error('authorization_expired_or_invalid', 403)
        if form.get('action') == 'deny':
            with self.store.connection(True) as db:
                db.execute('DELETE FROM tickets WHERE id=?', (digest(ticket),))
            response = self.redirect(p, error='access_denied')
            response.delete_cookie('rh_authorize', path='/oauth/authorize')
            return response
        username, password = str(form.get('username', '')), str(form.get('password', ''))
        if len(username) > 64 or len(password) > 256 or form.get('action') != 'allow':
            return error('invalid_request')
        if not self.store.rate('user-login:' + digest(username), 20, 300):
            return login_page(ticket, '尝试次数过多，请稍后重试。', 429)
        user = await asyncio.to_thread(self.store.login, username, password)
        if not user:
            return login_page(ticket, '账号或密码错误，或账号已停用。', 401)
        try:
            code, p = self.store.authorize(ticket, user['id'])
        except ValueError:
            return error('authorization_expired_or_invalid', 403)
        response = self.redirect(p, code=code)
        response.delete_cookie('rh_authorize', path='/oauth/authorize')
        return response

    async def token(self, request):
        if self.limited(request, 'token', 100):
            return error('rate_limit_exceeded', 429)
        form = await request.form()
        p = {k: str(v) for k, v in form.items()}
        if p.get('grant_type') not in ('authorization_code', 'refresh_token'):
            return error('unsupported_grant_type')
        if not self.store.client_redirects(p.get('client_id', '')):
            return error('invalid_client', 401)
        if p.get('resource') != self.settings.resource:
            return error('invalid_target')
        if p.get('scope', 'search') != 'search':
            return error('invalid_scope')
        try:
            return JSONResponse(self.store.exchange(p, self.settings.resource), headers=NO_STORE)
        except ValueError:
            return error('invalid_grant')

    async def revoke(self, request):
        if self.limited(request, 'revoke', 100):
            return error('rate_limit_exceeded', 429)
        form = await request.form()
        self.store.revoke(str(form.get('token', '')), str(form.get('client_id', '')))
        return Response(status_code=200, headers=NO_STORE)

    def routes(self):
        return [
            Route('/.well-known/oauth-protected-resource', self.resource_metadata),
            Route('/.well-known/oauth-protected-resource/mcp', self.resource_metadata),
            Route('/.well-known/oauth-authorization-server', self.metadata),
            Route('/oauth/register', self.register, methods=['POST']),
            Route('/oauth/authorize', self.authorize_get, methods=['GET']),
            Route('/oauth/authorize', self.authorize_post, methods=['POST']),
            Route('/oauth/token', self.token, methods=['POST']),
            Route('/oauth/revoke', self.revoke, methods=['POST']),
        ]
