#!/usr/bin/env python3
"""Read public Quark share file metadata without browser automation or account cookies."""
import argparse
from collections import deque
import json
import re
import sys
import time
from pathlib import PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit

from common import cache_get, cache_path, cache_put, request

ROOT = 'https://drive-pc.quark.cn/1/clouddrive/share/sharepage/'
VIDEO = {'.mp4', '.mkv', '.avi', '.mov', '.flv', '.ts', '.m4v', '.webm', '.wmv'}
CACHE_TTL = 1800


def api(route, params, body=None):
    url = ROOT + route + '?' + urlencode({'pr': 'ucpro', 'fr': 'pc', **params})
    data = request(url, body, {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://pan.quark.cn/'},
                   timeout=12)
    if data.get('code') != 0 or not isinstance(data.get('data'), dict):
        raise ValueError('share_api_failed: 分享失效、提取码不正确或访问受限；未确认内容')
    return data


def _inspect(url, password='', max_files=300, max_requests=12, max_depth=3):
    parts = urlsplit(url)
    match = re.fullmatch(r'/s/([A-Za-z0-9]+)', parts.path.rstrip('/'))
    if parts.scheme != 'https' or parts.netloc != 'pan.quark.cn' or not match:
        raise ValueError('unsupported_url: 当前只支持标准夸克 HTTPS 分享链接')
    share_id = match.group(1)
    password = password or parse_qs(parts.query).get('pwd', [''])[0]
    token = api('token', {}, {'pwd_id': share_id, 'passcode': password})['data'].get('stoken')
    if not isinstance(token, str) or not token:
        raise ValueError('share_api_failed: 无法取得分享访问令牌')

    queue, seen = deque([('0', '', 0, 1)]), {'0'}
    files, folders, requests, incomplete = [], [], 0, False
    while queue and requests < max_requests and len(files) < max_files:
        fid, path, depth, page = queue.popleft()
        result = api('detail', {'pwd_id': share_id, 'stoken': token, 'pdir_fid': fid,
                                '_page': page, '_size': 50, '_fetch_total': 1})
        requests += 1
        rows = result['data'].get('list')
        if not isinstance(rows, list):
            raise ValueError('response_invalid: 缺少文件列表')
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('file_name'), str):
                raise ValueError('response_invalid: 文件条目格式不正确')
            name = row['file_name']
            full = path + '/' + name if path else name
            if row.get('dir') is True:
                folders.append(full)
                child = row.get('fid')
                if not isinstance(child, str) or not child:
                    incomplete = True
                elif child not in seen:
                    seen.add(child)
                    if depth < max_depth:
                        queue.append((child, full, depth + 1, 1))
                    else:
                        incomplete = True
            else:
                if len(files) >= max_files:
                    incomplete = True
                    break
                ext = PurePosixPath(name).suffix.lower()
                files.append({'path': full, 'size': row.get('size'), 'is_video': ext in VIDEO})
        total = (result.get('metadata') or {}).get('_total')
        more = page * 50 < total if isinstance(total, int) else len(rows) == 50
        if more:
            queue.append((fid, path, depth, page + 1))

    videos = [f for f in files if f['is_video']
              and isinstance(f['size'], (int, float)) and f['size'] > 0]
    return {'listing_complete': not (incomplete or queue),
            'file_count': len(files), 'video_count': len(videos),
            'folders': folders, 'files': files}


def inspect(url, password='', max_files=300, max_requests=12, max_depth=3,
            use_cache=True, cache_ttl=CACHE_TTL):
    # v2 前缀：输出字段精简后，旧缓存不可复用
    key = '\0'.join(['v2', url, password, str(max_files), str(max_requests), str(max_depth)])
    path = cache_path('inspect', key)
    if use_cache:
        cached = cache_get(path, cache_ttl)
        if cached and isinstance(cached.get('data'), dict):
            return cached['data']
    data = _inspect(url, password, max_files, max_requests, max_depth)
    if use_cache:
        cache_put(path, {'ts': time.time(), 'data': data})
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--password', default='')
    parser.add_argument('--max-files', type=int, default=300)
    parser.add_argument('--max-requests', type=int, default=12)
    parser.add_argument('--max-depth', type=int, default=3)
    parser.add_argument('--no-cache', action='store_true')
    parser.add_argument('--cache-ttl', type=int, default=CACHE_TTL)
    args = parser.parse_args()
    if (not 1 <= args.max_files <= 1000 or not 1 <= args.max_requests <= 30
            or not 0 <= args.max_depth <= 6 or not 0 <= args.cache_ttl <= 86400):
        parser.error('max-files: 1–1000; max-requests: 1–30; max-depth: 0–6; cache-ttl: 0–86400')
    print(json.dumps(inspect(args.url, args.password, args.max_files, args.max_requests,
                             args.max_depth, use_cache=not args.no_cache,
                             cache_ttl=args.cache_ttl), ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except HTTPError as exc:
        print(json.dumps({'error': 'http_error', 'status': exc.code}), file=sys.stderr)
        sys.exit(1)
    except (URLError, TimeoutError, OSError):
        print('{"error":"network_error","message":"内容核验失败；不能当作没有文件或有效资源"}', file=sys.stderr)
        sys.exit(1)
    except ValueError:
        print('{"error":"share_or_response_invalid","message":"分享访问失败或格式不兼容；未确认内容"}', file=sys.stderr)
        sys.exit(1)
