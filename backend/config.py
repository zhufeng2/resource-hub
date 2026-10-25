import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    base_url: str
    database: Path
    redirect_uris: tuple[str, ...]
    default_limit: int = 5
    search_timeout: int = 25
    concurrency: int = 4

    @property
    def resource(self):
        return self.base_url + '/mcp'

    @property
    def secure(self):
        return self.base_url.startswith('https://')

    def __post_init__(self):
        parts = urlsplit(self.base_url)
        local = parts.hostname in ('127.0.0.1', 'localhost')
        if (parts.scheme != 'https' and not (parts.scheme == 'http' and local)
                or not parts.hostname or parts.path or parts.query or parts.fragment
                or parts.username or parts.password):
            raise ValueError('PUBLIC_BASE_URL 必须是 HTTPS 域名根地址；仅本机测试允许 HTTP')
        if not self.redirect_uris:
            raise ValueError('至少配置一个 OAUTH_REDIRECT_URIS')
        for uri in self.redirect_uris:
            target = urlsplit(uri)
            if (target.scheme != 'https' or not target.hostname or target.fragment
                    or target.username or target.password):
                raise ValueError('OAuth 回调必须是完整 HTTPS 地址')
        if not (1 <= self.default_limit <= 10000 and 1 <= self.concurrency <= 16
                and 1 <= self.search_timeout <= 30):
            raise ValueError('额度、并发或超时设置超出范围')

    @classmethod
    def from_env(cls):
        base = os.environ.get('PUBLIC_BASE_URL', '').rstrip('/')
        if not base:
            raise ValueError('请配置 PUBLIC_BASE_URL，参见 backend/README.md')
        return cls(
            base_url=base,
            database=Path(os.getenv('DATABASE_PATH', 'backend/data/service.sqlite3')),
            redirect_uris=tuple(x.strip() for x in os.getenv(
                'OAUTH_REDIRECT_URIS',
                'https://chatgpt.com/connector_platform_oauth_redirect').split(',') if x.strip()),
            default_limit=int(os.getenv('DEFAULT_DAILY_LIMIT', '5')),
            search_timeout=int(os.getenv('SEARCH_TIMEOUT', '25')),
            concurrency=int(os.getenv('SEARCH_CONCURRENCY', '4')),
        )
