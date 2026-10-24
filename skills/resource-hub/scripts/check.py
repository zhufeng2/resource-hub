#!/usr/bin/env python3
"""Check one PanSou candidate; does not verify file contents."""
import argparse
import json
import sys
from urllib.error import HTTPError, URLError

from common import base_url, unwrap
from search import login, post, api_token


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--type', required=True, dest='disk_type')
    parser.add_argument('--password', default='')
    args = parser.parse_args()

    base = base_url()
    token = login(base, 60)
    payload = {'items': [{'disk_type': args.disk_type, 'url': args.url, 'password': args.password}]}
    for attempt in range(2):
        try:
            data = post(base, '/api/check/links', payload, 60, token)
            break
        except HTTPError as exc:
            if exc.code != 401 or attempt or api_token():
                raise
            token = login(base, 60, use_cache=False)
    data = unwrap(data)
    results = data.get('results')
    if not isinstance(results, list) or len(results) != 1:
        raise ValueError('检测响应格式不兼容')
    item = results[0]
    print(json.dumps({'state': item.get('state'), 'summary': item.get('summary') or ''},
                     ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except HTTPError as exc:
        print(json.dumps({'error': 'http_error', 'status': exc.code}), file=sys.stderr)
        sys.exit(1)
    except (ValueError, OSError, URLError):
        print('{"error":"check_failed","message":"无法完成检测，不应视为有效链接"}', file=sys.stderr)
        sys.exit(1)
