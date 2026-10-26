import asyncio
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .config import Settings
from gpt.oauth import OAuth
from gpt.server import bearer, build_server
from .store import Store
from .service import SearchService
from .upstream import Upstream
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
            deadline = asyncio.get_running_loop().time() + 15
            while True:
                try:
                    message = await asyncio.wait_for(receive(), max(0, deadline - asyncio.get_running_loop().time()))
                except asyncio.TimeoutError:
                    return await JSONResponse({'error': 'request_timeout'}, status_code=408)(scope, receive, send)
                if message['type'] == 'http.disconnect':
                    return
                body.extend(message.get('body', b''))
                if len(body) > 16384:
                    return await JSONResponse({'error': 'request_too_large'}, status_code=413)(scope, receive, send)
                if not message.get('more_body', False):
                    break
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
    mcp, transport = build_server(settings, store, service)

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
                cleanup_task.cancel()
                try:
                    await cleanup_task
                except asyncio.CancelledError:
                    pass

    async def health(request):
        return JSONResponse({'status': 'ok'})

    oauth = OAuth(settings, store)
    web = Web(settings, store, service, upstream)
    app = Starlette(routes=[*web.routes(), Route('/healthz', health), *oauth.routes(),
                            Mount('/', app=transport)], lifespan=lifespan)
    app.state.store, app.state.settings, app.state.mcp = store, settings, mcp
    app.state.service, app.state.upstream = service, upstream
    app.add_middleware(Guard, settings=settings, store=store)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(settings.base_url).hostname])
    return app
