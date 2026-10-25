"""PanSou adapter. The shared upstream credential never leaves this process."""
import asyncio
import os
import re
import time
from urllib.parse import urlsplit

import httpx

from .backend import SearchFailure

PROVIDERS = {'qqpd': 'QQ 频道', 'gying': '观影', 'panlian': '盘链', 'weibo': '微博', 'woniu': '蜗牛'}


class Upstream:
    def __init__(self):
        self.base = os.getenv('PANSOU_BASE_URL', 'https://pan.sysscitech.com').rstrip('/')
        parts = urlsplit(self.base)
        if (not parts.hostname or parts.username or parts.password or parts.query or parts.fragment
                or parts.scheme not in ('https', 'http')
                or (parts.scheme == 'http' and os.getenv('PANSOU_ALLOW_HTTP') != 'true')):
            raise ValueError('PanSou 地址需使用 HTTPS；内部 HTTP 部署需设置 PANSOU_ALLOW_HTTP=true')
        self._token = ''
        self._expires = 0
        self._lock = asyncio.Lock()

    async def token(self, force=False):
        fixed = os.getenv('PANSOU_API_TOKEN', '').strip()
        if fixed:
            return fixed
        async with self._lock:
            if not force and self._token and self._expires > time.time():
                return self._token
            username, password = os.getenv('PANSOU_USERNAME'), os.getenv('PANSOU_PASSWORD')
            if not username or not password:
                raise SearchFailure('搜索服务尚未配置，请联系管理员。')
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                response = await client.post(self.base + '/api/auth/login', json={'username': username, 'password': password})
                response.raise_for_status()
                data = response.json()
                data = data.get('data', data) if isinstance(data, dict) else {}
                token = data.get('token')
                if not isinstance(token, str) or not token:
                    raise SearchFailure('搜索服务认证失败，请联系管理员。')
                self._token, self._expires = token, time.time() + 1200
                return token

    async def request(self, path, payload=None, *, method='POST', timeout=30, raw=False):
        if not path.startswith('/') or path.startswith('//'):
            raise ValueError('无效接口地址')
        try:
            for attempt in range(2):
                token = await self.token(force=bool(attempt))
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                    response = await client.request(method, self.base + path, json=payload,
                                                    headers={'Authorization': 'Bearer ' + token})
                if response.status_code == 401 and attempt == 0 and not os.getenv('PANSOU_API_TOKEN'):
                    continue
                if raw:
                    return response
                response.raise_for_status()
                if len(response.content) > 4_000_000:
                    raise ValueError('response too large')
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError('invalid response')
                return data
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchFailure('搜索源暂时不可用，请稍后重试。') from exc

    async def catalog(self):
        data = await self.request('/api/health', method='GET', timeout=10)
        data = data.get('data', data)
        return {key: [x for x in data.get(key, [])[:100] if isinstance(x, str) and
                      re.fullmatch(r'[\w@.-]{1,80}', x)] for key in ('plugins', 'channels')}

    @staticmethod
    def normalize(data):
        if 'code' in data and data['code'] not in (0, 200, '0', '200', 'SUCCESS'):
            raise SearchFailure('搜索源未能完成搜索，本次不扣额度。')
        data = data.get('data', data)
        groups = data.get('merged_by_type')
        if groups is None and data.get('total') == 0:
            groups = {}
        if not isinstance(groups, dict):
            raise SearchFailure('搜索结果格式异常，本次不扣额度。')
        rows, seen = [], set()
        for cloud, items in groups.items():
            if not isinstance(items, list):
                continue
            for item in items:
                url = str(item.get('url') or '').split('|')[0]
                if (url in seen or len(url) > 4096 or
                        not url.startswith(('https://', 'http://', 'magnet:', 'ed2k:'))):
                    continue
                seen.add(url)
                rows.append({'title': str(item.get('note') or item.get('title') or '未命名资源')[:1000],
                             'url': url, 'cloud_type': cloud, 'password': str(item.get('password') or '')[:128],
                             'source': str(item.get('source') or '')[:160], 'datetime': str(item.get('datetime') or '')[:80]})
        return {'results': rows[:200], 'matched_count': len(rows), 'truncated': len(rows) > 200,
                'completeness': 'final' if data.get('is_final') else 'unknown',
                'verification': '链接有效性及文件内容未核验。'}

    async def search(self, query, timeout, options=None):
        options = options or {}
        payload = {'kw': query, 'res': 'merge', 'src': options.get('src', 'all'),
                   'cloud_types': options.get('cloud_types', ['quark']), 'refresh': options.get('refresh', False)}
        for key in ('channels', 'plugins'):
            if options.get(key):
                payload[key] = options[key]
        return self.normalize(await self.request('/api/search', payload, timeout=timeout + 10))

    async def create_binding(self, provider):
        import secrets
        # Generate a private per-binding namespace, never derive it from a public username.
        identity = secrets.token_hex(24)
        response = await self.request(f'/{provider}/{identity}', method='GET', raw=True)
        location = response.headers.get('location', '')
        parts = urlsplit(location)
        if (parts.netloc and parts.netloc != urlsplit(self.base).netloc) or parts.query or parts.fragment:
            raise SearchFailure('搜索源返回了无效的账号地址。')
        match = re.fullmatch(rf'/{provider}/([a-f0-9]{{64}})', parts.path)
        if response.status_code not in (301, 302, 303, 307, 308) or not match:
            raise SearchFailure('当前搜索源未提供账号绑定接口。')
        return match.group(1)

    async def binding_action(self, binding, action, payload):
        provider = binding['provider']
        allowed = {'get_status', 'logout'}
        if provider in ('qqpd', 'weibo'):
            allowed |= {'refresh_qrcode', 'check_login', 'set_channels' if provider == 'qqpd' else 'set_user_ids'}
        else:
            allowed |= {'login'}
        if provider == 'panlian':
            allowed |= {'captcha', 'confirm_email'}
        if provider in ('gying', 'woniu'):
            allowed |= {'get_config', 'update_config'}
        if action not in allowed:
            raise ValueError('不支持此操作')
        fields = {'login': ('username', 'password', 'captcha_id', 'captcha_code'),
                  'confirm_email': ('username', 'password', 'confirm_id', 'email'),
                  'set_channels': ('channels',), 'set_user_ids': ('user_ids',), 'update_config': ('base_url',)}
        body = {'action': action, **{k: payload[k] for k in fields.get(action, ()) if k in payload}}
        data = await self.request(f"/{provider}/{binding['upstream_hash']}", body, timeout=120 if action == 'login' else 25)
        # Explicit response allowlist; upstream cookie and token fields never reach the browser.
        safe_fields = {'logged_in', 'status', 'qq_masked', 'username', 'uid', 'login_time', 'expire_time',
                       'expires_in_days', 'channels', 'channel_count', 'user_ids', 'user_id_count',
                       'qrcode_base64', 'login_status', 'captcha_id', 'image', 'need_email', 'confirm_id',
                       'email_hint', 'captcha_required', 'captcha_invalid', 'base_url', 'default_url'}
        details = data.get('data') or {}
        return {'success': bool(data.get('success')), 'message': str(data.get('message') or '')[:200],
                'data': {k: v for k, v in details.items() if k in safe_fields} if isinstance(details, dict) else {}}

    async def check_links(self, items):
        response = await self.request('/api/check/links', {'items': items}, timeout=25)
        result = response.get('data', response).get('results')
        if not isinstance(result, list) or len(result) != len(items):
            raise SearchFailure('暂时无法检测链接。')
        return [{'state': str(r.get('state', 'unknown')), 'summary': str(r.get('summary') or '')[:160]} for r in result]
