#!/usr/bin/env python3
"""本 Skill 共用的配置、HTTP 与缓存工具，供 search/check/inspect/resource 复用。"""
import hashlib
import json
import os
import time
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

DEFAULT_URL = 'https://my-pansou-api.onrender.com'
CONFIG = Path.home() / '.config/pansou/credentials.json'
CACHE_ROOT = Path(os.getenv('RESOURCE_HUB_CACHE', str(Path.home() / '.cache/resource-hub')))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_config():
    try:
        data = json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def base_url():
    """取 PanSou 服务地址；必须是不含凭据、查询或片段的 HTTPS 地址。"""
    base = (os.getenv('PANSOU_BASE_URL') or load_config().get('base_url') or DEFAULT_URL).rstrip('/')
    parts = urlsplit(base)
    if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment):
        raise ValueError('config_invalid: 服务地址必须为不含凭据、查询或片段的 HTTPS 地址')
    return base


def request(url, payload=None, headers=None, timeout=60):
    """发 JSON 请求并解析响应体；payload 为 None 时发 GET。"""
    merged = {'Accept': 'application/json'}
    if payload is not None:
        merged['Content-Type'] = 'application/json'
    merged.update(headers or {})
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(url, data=data, headers=merged)
    with build_opener(NoRedirect()).open(req, timeout=timeout) as response:
        parsed = json.load(response)
    if not isinstance(parsed, dict):
        raise ValueError('response_invalid: 预期 JSON 对象')
    return parsed


def unwrap(data):
    """剥掉 {code, message, data} 外壳；业务错误统一抛 ValueError。"""
    if not isinstance(data, dict) or 'data' not in data or 'merged_by_type' in data or 'results' in data:
        return data
    code = data.get('code')
    bad = (isinstance(code, str) and ('ERROR' in code.upper() or 'INVALID' in code.upper())) \
        or (isinstance(code, int) and code not in (0, 200))
    if bad:
        raise ValueError('response_invalid: 服务返回业务错误')
    inner = data['data']
    if not isinstance(inner, dict):
        raise ValueError('response_invalid: 响应 data 字段格式不正确')
    return inner


def cache_path(kind, key):
    return CACHE_ROOT / kind / (hashlib.sha256(key.encode()).hexdigest() + '.json')


def cache_get(path, ttl):
    try:
        payload = json.loads(path.read_text())
        if isinstance(payload, dict) and time.time() - float(payload.get('ts', 0)) <= ttl:
            return payload
    except (OSError, ValueError, TypeError):
        pass
    return None


def cache_put(path, payload):
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
            tmp = Path(stream.name)
            os.chmod(tmp, 0o600)
            json.dump(payload, stream, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass
