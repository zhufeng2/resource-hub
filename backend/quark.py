"""Tenant-scoped Quark adapter. Credentials travel to Node over stdin, never argv."""
import asyncio
import json
import os
from pathlib import Path
import re
from contextlib import asynccontextmanager

from cryptography.fernet import InvalidToken


class QuarkError(Exception):
    def __init__(self, code, message, status=400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def validate_cookie(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 12000:
        raise QuarkError('invalid_cookie', '请填写一整行有效的夸克 Cookie。')
    value = re.sub(r'^Cookie:\s*', '', value.strip(), flags=re.I)
    parts = value.split(';')
    if any(not re.fullmatch(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+=[\x20-\x7e]*", part.strip())
           for part in parts if part.strip()) or not any('=' in part for part in parts):
        raise QuarkError('invalid_cookie', 'Cookie 格式不正确，不接受换行或完整请求报文。')
    return value


class QuarkService:
    def __init__(self, store):
        self.store = store
        self.runner = Path(__file__).parent / 'quark_client' / 'runner.cjs'
        self.slots = asyncio.Semaphore(4)
        self.inflight = {}
        self.reset_jobs = {}
        self.closing = False

    async def close(self):
        self.closing = True
        tasks = [job['task'] for job in self.reset_jobs.values() if job.get('task')]
        # Let the current bounded slice persist and release its lock on shutdown.
        try:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 50)
        except asyncio.TimeoutError:
            pass

    async def continue_reset(self, user_id, account_id, args, journal, job):
        """Continue authorized slices independently of the originating HTTP request."""
        stagnant = 0
        deadline = asyncio.get_running_loop().time() + 1800
        try:
            for _ in range(600):
                await asyncio.sleep(1)
                if self.closing or asyncio.get_running_loop().time() >= deadline:
                    return
                account = self.store.quark_account(user_id, secret=True)
                if not account or account['id'] != account_id:
                    return
                before = (job['result'].get('verified'), job['result'].get('skipped'))
                result = await self.run(account['cookie'], 'reset_progress', args, journal, True)
                job['result'] = result
                if result.get('error') or result.get('phase') != 'in_progress':
                    return
                after = (result.get('verified'), result.get('skipped'))
                stagnant = stagnant + 1 if before == after else 0
                if stagnant >= 3:
                    return
        except QuarkError as exc:
            job['result'] = {**job['result'], 'error': exc.code, 'message': exc.message}
        except (InvalidToken, OSError, ValueError, KeyError, TypeError, AttributeError):
            job['result'] = {**job['result'], 'error': 'reset_paused',
                             'message': '后台任务暂停，请核对绑定和原操作记录。'}
        finally:
            job['running'] = False

    @asynccontextmanager
    async def available_slot(self):
        try:
            await asyncio.wait_for(self.slots.acquire(), 5)
        except asyncio.TimeoutError:
            raise QuarkError('quark_busy', '网盘服务繁忙，请稍后用原请求编号重试。', 503) from None
        try:
            yield
        finally:
            self.slots.release()

    def status(self, user_id):
        account = self.store.quark_account(user_id)
        return {'bound': bool(account), **(account or {})}

    def saved_cookie(self, user_id):
        # Only the authenticated, CSRF-protected web reveal endpoint calls this.
        try:
            account = self.store.quark_account(user_id, secret=True)
        except (InvalidToken, OSError, ValueError, KeyError, TypeError, AttributeError):
            raise QuarkError('credential_unavailable', '无法读取已保存的 Cookie，请重新绑定。', 422) from None
        if not account:
            raise QuarkError('quark_not_bound', '尚未绑定夸克账号。', 404)
        return account['cookie']

    async def run(self, cookie, action, args=None, journal=None, execute=False):
        payload = {'cookie': cookie, 'action': action, 'args': args or {},
                   'journal': str(journal) if journal else None, 'execute': execute}
        async with self.available_slot():
            try:
                process = await asyncio.create_subprocess_exec(
                    os.environ.get('QUARK_NODE_BINARY', 'node'), str(self.runner),
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, cwd=self.runner.parent,
                    env={key: value for key, value in os.environ.items() if key.upper() in {
                        'PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'SYSTEMDRIVE', 'TEMP', 'TMP', 'LANG', 'LC_ALL'}})
            except OSError:
                raise QuarkError('runtime_unavailable', '夸克操作运行环境不可用，请联系管理员。', 503) from None
            try:
                stdout, _ = await asyncio.wait_for(process.communicate(json.dumps(payload, ensure_ascii=False).encode()), 45)
            except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
                if process.returncode is None:
                    process.kill()
                await process.wait()
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise QuarkError('outcome_unknown', '操作超时；写操作不要换请求编号重提，请先查询原记录。', 504) from None
        try:
            if len(stdout) > 2 * 1024 * 1024:
                raise ValueError('response_limit')
            result = json.loads(stdout)
            if not isinstance(result, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            raise QuarkError('invalid_response', '夸克操作未返回有效结果，请先核对原记录。', 502) from None
        return result

    async def bind(self, user_id, cookie):
        cookie = validate_cookie(cookie)
        result = await self.run(cookie, 'space')
        if result.get('error'):
            raise QuarkError('binding_failed', '夸克凭据校验未成功，原有绑定保持不变。请检查 Cookie 或稍后重试。', 422)
        self.store.bind_quark(user_id, cookie)
        return self.status(user_id)

    def journal(self, user_id, account_id, request_id):
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', request_id):
            raise QuarkError('invalid_request_id', '请求编号需为 1–80 位字母、数字、下划线或短横线。')
        directory = self.store.path.parent / 'quark-operations' / str(user_id) / account_id
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        return directory / (request_id + '.json')

    async def call(self, user_id, action, args=None, request_id='', execute=False):
        if self.inflight.get(user_id, 0) >= 2:
            return {'error': 'quark_busy', 'message': '当前账号已有操作进行中，请稍后用原请求编号重试。'}
        try:
            account = self.store.quark_account(user_id, secret=True)
        except (InvalidToken, OSError, ValueError, KeyError, TypeError, AttributeError):
            return {'error': 'credential_unavailable', 'message': '无法读取夸克凭据，请在个人主页重新绑定。'}
        if not account:
            return {'error': 'quark_not_bound', 'message': '请在个人主页的安全与连接中绑定夸克账号。'}
        try:
            journal = None
            if action in ('save', 'operation', 'create_folder', 'create_text', 'save_entries', 'rename', 'move', 'reset_progress'):
                journal = self.journal(user_id, account['id'], request_id)
            key = (user_id, account['id'], request_id)
            existing = self.reset_jobs.get(key)
            if existing and (action == 'operation' or action == 'reset_progress' and execute):
                if action == 'reset_progress' and existing['args'] != args:
                    return {'error': 'plan_conflict', 'request_id': request_id}
                if existing['running'] or action == 'operation':
                    return {**existing['result'], 'request_id': request_id,
                            'background_running': existing['running'],
                            'message': ('后台自动继续处理；稍后查询进度即可。' if existing['running']
                                        else existing['result'].get('message', '后台任务已停止。'))}
            reset_job = None
            if action == 'reset_progress' and execute:
                active = [k for k, j in self.reset_jobs.items() if j['running']]
                if len(active) >= 2 or any(k[0] == user_id for k in active):
                    return {'error': 'quark_busy', 'message': '已有归零任务运行，请稍后查询进度。'}
                # Reserve before the first await, including the initial slice.
                reset_job = {'args': dict(args), 'running': True,
                             'result': {'phase': 'in_progress', 'message': '正在核对指定目录。'}}
                # Keep completed results on disk; bound the in-memory job registry.
                self.reset_jobs = {k: j for k, j in self.reset_jobs.items() if j['running']}
                self.reset_jobs[key] = reset_job
            if action == 'operation' and not journal.is_file():
                return {'error': 'operation_not_found', 'message': '当前绑定下没有这条操作记录。'}
            self.inflight[user_id] = self.inflight.get(user_id, 0) + 1
            try:
                result = await self.run(account['cookie'], action, args, journal, execute)
                if reset_job:
                    reset_job['result'] = result
                    if result.get('phase') == 'in_progress' and not result.get('error'):
                        reset_job['task'] = asyncio.create_task(self.continue_reset(
                            user_id, account['id'], dict(args), journal, reset_job))
                        result = {**result, 'background_running': True,
                                  'message': '后台自动继续处理；用 quark_operation_status 查询，无需逐批调用归零工具。'}
                    else:
                        reset_job['running'] = False
            finally:
                if reset_job and not reset_job.get('task'):
                    reset_job['running'] = False
                self.inflight[user_id] -= 1
                if not self.inflight[user_id]:
                    del self.inflight[user_id]
            if journal:
                result['request_id'] = request_id
            return result
        except QuarkError as exc:
            return {'error': exc.code, 'message': exc.message, 'request_id': request_id or None}
