"""One search and quota path shared by browser sessions and MCP clients."""
import asyncio
import json
import re
import secrets
import time
from urllib.parse import urlsplit

from .errors import SearchFailure

CHECK_HOSTS = {'quark': {'pan.quark.cn'}}


def checkable_url(url, cloud):
    if not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url)
        return (parts.scheme == 'https' and parts.hostname in CHECK_HOSTS.get(cloud, set())
                and not parts.username and not parts.password and parts.port in (None, 443))
    except ValueError:
        return False


def validate_preferences(value):
    if not isinstance(value, dict) or set(value) - {
            'cloud_types', 'channels', 'plugins', 'src', 'page_size', 'view', 'sort', 'theme', 'auto_check', 'hide_invalid', 'include_words', 'exclude_words', 'match_mode', 'verification_defaults_v2'}:
        raise ValueError('配置格式不正确')
    for key in ('cloud_types', 'channels', 'plugins'):
        items = value.get(key, [])
        if (not isinstance(items, list) or len(items) > 80 or
                any(not isinstance(x, str) or not re.fullmatch(r'[\w@.-]{1,80}', x) for x in items)):
            raise ValueError('搜索源名称格式不正确')
    for key in ('include_words', 'exclude_words'):
        if key in value and (not isinstance(value[key], str) or len(value[key]) > 200):
            raise ValueError('关键词筛选需在 200 字符以内')
    if value.get('match_mode', 'any') not in ('any', 'all'):
        raise ValueError('匹配方式不正确')
    for key in ('auto_check', 'hide_invalid', 'verification_defaults_v2'):
        if key in value and type(value[key]) is not bool:
            raise ValueError('检测选项格式不正确')
    for key, allowed in (('src', ('all', 'tg', 'plugin')), ('page_size', (10, 20, 50)),
                         ('view', ('list', 'grid')), ('sort', ('relevance', 'newest')),
                         ('theme', ('light', 'dark', 'system'))):
        if key in value and value[key] not in allowed:
            raise ValueError('配置选项不正确')
    return {**value, 'cloud_types': ['quark']}


def quark_results(rows):
    return [{**row, 'cloud_type': 'quark'} for row in rows
            if isinstance(row, dict) and row.get('cloud_type', 'quark') == 'quark'
            and checkable_url(row.get('url'), 'quark')]


class SearchService:
    def __init__(self, settings, store, provider):
        self.settings, self.store, self.provider = settings, store, provider
        self.slots = asyncio.Semaphore(settings.concurrency)

    def page(self, user_id, row, offset=0, limit=20):
        if not row or not row['result'] or time.time() - row['created'] > 86400:
            return {'error': 'search_expired_or_not_found', 'message': '搜索记录已过期或不存在。'}
        if not 0 <= offset <= 200 or not 1 <= limit <= 200:
            return {'error': 'invalid_pagination'}
        result = json.loads(row['result'])
        original = result.pop('results')
        rows = quark_results(original)
        if len(rows) != len(original):
            result['matched_count'] = len(rows)
        if isinstance(result.get('options'), dict):
            result['options'] = {**result['options'], 'cloud_types': ['quark']}
        result.pop('source_binding', None)
        return {**result, 'search_id': row['id'], 'request_id': row['request_id'],
                'results': rows[offset:offset + limit], 'offset': offset,
                'returned_count': len(rows[offset:offset + limit]), 'available_count': len(rows),
                'has_more': offset + limit < len(rows), 'quota': self.store.quota(user_id)}

    async def verify_page(self, data, limit=20, drop_invalid=True):
        """Annotate and optionally remove dead links before MCP clients see them."""
        if not isinstance(data, dict) or data.get('error') or not isinstance(data.get('results'), list):
            return data
        rows = data['results']
        for row in rows:
            if isinstance(row, dict) and not isinstance(row.get('link_check'), dict):
                row['link_check'] = {'state': 'unknown', 'summary': '暂不支持检测此链接。'}
        candidates, indices = [], []
        if hasattr(self.provider, 'check_links'):
            for index, row in enumerate(rows[:limit]):
                url = str(row.get('url') or '')
                cloud = str(row.get('cloud_type') or '')
                if checkable_url(url, cloud):
                    candidates.append({'url': url, 'disk_type': cloud, 'password': row.get('password', '')})
                    indices.append(index)
        if not candidates:
            data['verification'] = '当前结果不支持自动核验；文件内容未核验。'
            return data
        try:
            checked = await self.provider.check_links(candidates)
        except Exception:
            data['verification'] = '链接核验服务暂时不可用；以下结果未经核验。'
            return data
        if not isinstance(checked, list) or len(checked) != len(candidates):
            data['verification'] = '链接核验返回异常；以下结果未经核验。'
            return data
        for index, result in zip(indices, checked):
            state = str(result.get('state') or 'unknown') if isinstance(result, dict) else 'unknown'
            summary = str(result.get('summary') or '')[:160] if isinstance(result, dict) else ''
            rows[index]['link_check'] = {'state': state, 'summary': summary}
        valid = sum(1 for index in indices if rows[index]['link_check']['state'] in ('ok', 'good'))
        bad = sum(1 for index in indices if rows[index]['link_check']['state'] == 'bad')
        unverified = len(rows) - valid - bad
        if drop_invalid:
            kept = [row for row in rows
                    if not (isinstance(row.get('link_check'), dict) and row['link_check'].get('state') == 'bad')]
            dropped = len(rows) - len(kept)
            data['results'] = kept
            if dropped and isinstance(data.get('available_count'), int):
                data['available_count'] = max(0, data['available_count'] - dropped)
        data['returned_count'] = len(data['results'])
        note = f'已核验 {len(candidates)} 条链接：{valid} 条有效，{bad} 条失效'
        if unverified:
            note += f'；{unverified} 条未核验'
        data['verification'] = note + '；文件内容未核验。'
        return data

    async def search(self, user, query, request_id='', options=None, refresh=False):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 120 or any(ord(c) < 32 for c in query):
            return {'error': 'invalid_query', 'message': '请输入 1–120 个字符的搜索词。'}
        query = query.strip()
        if not isinstance(request_id, str) or (request_id and not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', request_id)):
            return {'error': 'invalid_request_id'}
        options = validate_preferences(options or self.store.preferences(user['id']))
        if type(refresh) is not bool:
            return {'error': 'invalid_refresh'}
        options = {**options, 'refresh': refresh}
        request_id = request_id or secrets.token_urlsafe(24)
        selection = {k: options.get(k) for k in ('cloud_types', 'channels', 'plugins', 'src')}
        key = json.dumps({'query': query, 'source': '', 'refresh': refresh, **selection}, sort_keys=True, ensure_ascii=False)
        if not self.store.rate('search-calls:' + str(user['id']), 30, 60):
            return {'error': 'rate_limit_exceeded', 'message': '请求过于频繁，请稍后再试。'}
        try:
            await asyncio.wait_for(self.slots.acquire(), timeout=1)
        except asyncio.TimeoutError:
            return {'error': 'server_busy', 'request_id': request_id, 'message': '服务繁忙，请稍后重试。'}
        row, owned = None, False
        try:
            row, owned = self.store.reserve(user['id'], request_id, key)
            if owned:
                # Keep the injected two-argument backend interface for offline tests and integrations.
                if hasattr(self.provider, 'search'):
                    result = await self.provider.search(query, self.settings.search_timeout, options)
                else:
                    result = await self.provider(query, self.settings.search_timeout)
                if not isinstance(result, dict) or not isinstance(result.get('results'), list):
                    raise SearchFailure('搜索返回格式异常。')
                result['results'] = quark_results(result['results'])
                result['query'] = query
                result['options'] = {k: v for k, v in options.items() if k != 'refresh'}
                self.store.finish(row['id'], result)
            return self.page(user['id'], self.store.search(user['id'], row['id']))
        except ValueError as exc:
            messages = {'daily_limit_reached': '今日搜索额度已用完，明天再来。',
                        'search_in_progress': '这次搜索仍在进行，请稍后查看。',
                        'request_id_conflict': '搜索参数已变化，请重新搜索。'}
            return {'error': str(exc), 'message': messages.get(str(exc), '暂时无法搜索。'),
                    'request_id': request_id, 'quota': self.store.quota(user['id'])}
        except SearchFailure as exc:
            return {'error': 'search_failed', 'request_id': request_id, 'message': str(exc)}
        except Exception:
            return {'error': 'search_failed', 'request_id': request_id, 'message': '搜索暂时不可用，本次不扣额度。'}
        finally:
            if row and owned:
                self.store.fail(row['id'])
            self.slots.release()
