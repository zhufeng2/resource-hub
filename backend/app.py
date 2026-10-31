import asyncio
import json
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .config import Settings
from backend.mcp.oauth import OAuth
from backend.mcp.server import bearer, build_server
from .store import Store
from .service import SearchService
from .upstream import Upstream
from .quark import QuarkService
from web.app import Web


class Guard:
    """Pure ASGI guard: authenticate transport requests before the MCP SDK handles them."""
    def __init__(self, app, settings, store):
        self.app, self.settings, self.store = app, settings, store

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = {k.decode('latin1').lower(): v.decode('latin1') for k, v in scope['headers']}
        path = scope['path']
        if path.rstrip('/') == '/mcp':
            user = self.store.authenticate(bearer(headers), self.settings.resource)
            if not user:
                response = JSONResponse({'error': '需要连接并登录资源搜索服务。'}, status_code=401,
                    headers={'WWW-Authenticate': f'Bearer resource_metadata="{self.settings.base_url}/.well-known/oauth-protected-resource", scope="search"',
                             'Cache-Control': 'no-store'})
                return await response(scope, receive, send)
            if not self.store.rate('mcp:' + str(user['id']), 120, 60):
                return await JSONResponse({'error': 'rate_limit_exceeded'}, status_code=429,
                    headers={'Retry-After': '60', 'Cache-Control': 'no-store'})(scope, receive, send)
        # Limit bodies before form parsing or JSON decoding, including chunked uploads.
        if scope['method'] in ('POST', 'PUT', 'PATCH', 'DELETE'):
            body = bytearray()
            is_mcp = path.rstrip('/') == '/mcp'
            transport_limit = 256 * 1024 if is_mcp else 16 * 1024
            deadline = asyncio.get_running_loop().time() + 15
            while True:
                try:
                    message = await asyncio.wait_for(receive(), max(0, deadline - asyncio.get_running_loop().time()))
                except asyncio.TimeoutError:
                    return await JSONResponse({'error': 'request_timeout'}, status_code=408)(scope, receive, send)
                if message['type'] == 'http.disconnect':
                    return
                body.extend(message.get('body', b''))
                if len(body) > transport_limit:
                    return await JSONResponse({'error': 'request_too_large'}, status_code=413)(scope, receive, send)
                if not message.get('more_body', False):
                    break
            if len(body) > 16 * 1024:
                # Allow JSON escaping overhead only for the text creation tool.
                # The tool separately enforces the decoded UTF-8 content limit.
                try:
                    envelope = json.loads(body)
                    larger_text = (is_mcp and isinstance(envelope, dict)
                        and envelope.get('method') == 'tools/call'
                        and isinstance(envelope.get('params'), dict)
                        and envelope['params'].get('name') == 'quark_create_text_file')
                except (ValueError, UnicodeError):
                    larger_text = False
                if not larger_text:
                    return await JSONResponse({'error': 'request_too_large'}, status_code=413)(scope, receive, send)
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
                return await receive()

            return await self.app(scope, replay, send)
        return await self.app(scope, receive, send)


def create_app(settings=None, backend=None, upstream=None):
    settings = settings or Settings.from_env()
    store = Store(settings.database)
    upstream = upstream or Upstream()
    service = SearchService(settings, store, backend or upstream)
    quark = QuarkService(store)
    mcp, transport = build_server(settings, store, service, quark)

    async def janitor():
        while True:
            store.cleanup()
            await asyncio.sleep(300)

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            cleanup_task = asyncio.create_task(janitor())
            try:
                yield
            finally:
                await quark.close()
                cleanup_task.cancel()
                try:
                    await cleanup_task
                except asyncio.CancelledError:
                    pass

    async def health(request):
        return JSONResponse({'status': 'ok'})

    oauth = OAuth(settings, store)
    web = Web(settings, store, service, upstream, quark)
    app = Starlette(routes=[*web.routes(), Route('/healthz', health), *oauth.routes(),
                            Mount('/', app=transport)], lifespan=lifespan)
    app.state.store, app.state.settings, app.state.mcp = store, settings, mcp
    app.state.service, app.state.upstream = service, upstream
    app.state.quark = quark
    app.add_middleware(Guard, settings=settings, store=store)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(settings.base_url).hostname])
    return app
