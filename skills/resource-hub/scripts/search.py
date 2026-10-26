#!/usr/bin/env python3
"""PanSou 搜索：片名进，链接出。仅用标准库。"""
import argparse
import getpass
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError

from common import CONFIG, base_url, cache_get, cache_path, cache_put, load_config, request, unwrap

TOKEN_TTL = 1500
SEARCH_TTL = 600
EARLY_TTL = 15


def api_token():
    token = os.getenv('PANSOU_API_TOKEN', '').strip()
    if token:
        return token
    data = load_config()
    for key in ('api_token', 'token'):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ''


def credentials():
    username, password = os.getenv('PANSOU_USERNAME'), os.getenv('PANSOU_PASSWORD')
    if username is not None or password is not None:
        if not username or not password:
            raise ValueError('credentials_missing: 两个凭据环境变量必须同时配置')
        return username, password
    data = load_config()
    username, password = data.get('username'), data.get('password')
    if not all(isinstance(v, str) and v for v in (username, password)):
        raise ValueError('credentials_missing: 请在自己的终端运行脚本 --setup')
    return username, password


def setup():
    base_url()  # Validate the destination before saving credentials.
    username = input('PanSou 用户名：').strip()
    password = getpass.getpass('PanSou 密码（不显示）：')
    if not username or not password:
        raise ValueError('用户名和密码不能为空')
    CONFIG.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    existing = load_config()
    existing.update(username=username, password=password)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(CONFIG, flags, 0o600)
    with os.fdopen(fd, 'w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(existing, stream)
    cache_path('token', base_url() + '\0' + username).unlink(missing_ok=True)
    print('凭据已保存到本机；未进行登录验证。')


def post(base, path, payload, timeout, token=None):
    return request(base + path, payload, {'Authorization': 'Bearer ' + token} if token else None, timeout)


def login(base, timeout, use_cache=True):
    token = api_token()
    if token:
        return token
    username, password = credentials()
    path = cache_path('token', base + '\0' + username)
    if use_cache:
        cached = cache_get(path, TOKEN_TTL)
        if cached and isinstance(cached.get('token'), str) and cached['token']:
            return cached['token']
    data = post(base, '/api/auth/login', {'username': username, 'password': password}, timeout)
    token = data.get('token')
    if not isinstance(token, str) or not token:
        raise ValueError('login_failed: 登录响应缺少 token')
    cache_put(path, {'ts': time.time(), 'token': token})
    return token


def normalize(data, args):
    """merged_by_type → {title, url, cloud_type, password}。"""
    body = unwrap(data)
    groups = body.get('merged_by_type')
    if groups is None and body.get('total') == 0:
        groups = {}
    if not isinstance(groups, dict):
        raise ValueError('response_invalid: 缺少 merged_by_type')
    seen, results = {}, []
    for cloud, rows in groups.items():
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            url = str(row.get('url') or '').split('|')[0].strip()
            if not url:
                continue
            if url in seen:
                previous = seen[url]
                previous['sources'] = sorted(set(previous['sources']) | ({row['source']} if row.get('source') else set()))
                previous['password'] = previous['password'] or row.get('password') or ''
                continue
            results.append({'title': str(row.get('note') or ''), 'url': url,
                            'cloud_type': cloud, 'password': row.get('password') or '',
                            'source': row.get('source') or '', 'sources': [row['source']] if row.get('source') else [],
                            'datetime': row.get('datetime') or ''})
            seen[url] = results[-1]
    offset = getattr(args, 'offset', 0)
    selected = results[offset:offset + args.limit] if args.limit else results[offset:]
    return {'query': args.query, 'matched_count': len(results),
            'returned_count': len(selected), 'offset': offset,
            'has_more': offset + len(selected) < len(results), 'results': selected,
            'completeness': ('final' if body.get('is_final') is True else
                             'partial' if body.get('is_final') is False else 'unknown')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query', nargs='?')
    parser.add_argument('--auth-test', action='store_true', help='绕过旧 token，验证当前配置的认证与搜索权限')
    parser.add_argument('--setup', action='store_true', help='保存用户名密码到本机')
    parser.add_argument('--limit', type=int, default=0, help='0 返回全部候选')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--cloud-types', nargs='+', default=['quark'])
    parser.add_argument('--no-cache', action='store_true')
    parser.add_argument('--timeout', type=float, default=60)
    args = parser.parse_args()
    if args.setup:
        setup()
        return
    if args.auth_test:
        base = base_url()
        token = login(base, args.timeout, use_cache=False)
        probe = post(base, '/api/search', {'kw': '单挑荒野', 'cloud_types': ['quark']}, args.timeout, token)
        args.query, args.limit, args.offset = '单挑荒野', 0, 0
        normalize(probe, args)
        print(json.dumps({'authenticated': True, 'mode': 'api_token' if api_token() else 'password', 'fresh_login': not bool(api_token())}))
        return
    if not args.query or not args.query.strip():
        parser.error('必须提供非空搜索关键词')
    if args.limit < 0 or args.offset < 0:
        parser.error('limit 和 offset 不能为负数')

    base = base_url()
    payload = {'kw': args.query.strip(), 'cloud_types': [] if args.cloud_types == ['all'] else args.cloud_types}
    cache_file = cache_path('search', base + '\0' + json.dumps(payload, sort_keys=True, ensure_ascii=False))
    cached = None if args.no_cache else cache_get(cache_file, SEARCH_TTL)
    if cached:
        status = normalize(cached['data'], args)
        ttl = SEARCH_TTL if status['completeness'] == 'final' and status['matched_count'] else EARLY_TTL
        if time.time() - cached.get('ts', 0) > ttl:
            cached = None
    data = cached.get('data') if cached else None
    if data is None:
        token = login(base, args.timeout)
        try:
            data = post(base, '/api/search', payload, args.timeout, token)
        except HTTPError as exc:
            if exc.code != 401 or api_token():
                raise
            data = post(base, '/api/search', payload, args.timeout, login(base, args.timeout, use_cache=False))
        normalize(data, args)  # 不缓存格式错误或业务错误响应
        cache_put(cache_file, {'ts': time.time(), 'data': data})
    print(json.dumps(normalize(data, args), ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except HTTPError as exc:
        print('{"error":"http_error","status":%d}' % exc.code, file=sys.stderr)
    except (URLError, TimeoutError):
        print('{"error":"network_error","message":"连接失败或超时"}', file=sys.stderr)
    except (ValueError, OSError) as exc:
        print(json.dumps({'error': 'search_failed', 'message': str(exc)[:160]}, ensure_ascii=False),
              file=sys.stderr)
    else:
        sys.exit(0)
    sys.exit(1)
