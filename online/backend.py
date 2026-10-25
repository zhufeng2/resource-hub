"""Run the existing search-only entry point; never load the Quark skill or runtime."""
import asyncio
import json
import os
from pathlib import Path
import sys

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/resource-hub/scripts/search.py'


class SearchFailure(Exception):
    pass


async def search_pansou(query, timeout):
    if not (os.getenv('PANSOU_API_TOKEN') or
            (os.getenv('PANSOU_USERNAME') and os.getenv('PANSOU_PASSWORD'))):
        raise SearchFailure('搜索服务尚未配置，请联系管理员。')
    process = await asyncio.create_subprocess_exec(
        sys.executable, str(SCRIPT), '--cloud-types', 'quark',
        '--limit', '200', '--timeout', str(timeout), '--', query,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        # Password authentication can involve login + search + one token retry.
        stdout, _stderr = await asyncio.wait_for(process.communicate(), 3 * timeout + 10)
        if process.returncode or len(stdout) > 2_000_000:
            raise SearchFailure('搜索服务暂时不可用，本次不扣额度。请稍后重试或联系管理员。')
        result = json.loads(stdout)
        if not isinstance(result, dict) or not isinstance(result.get('results'), list):
            raise ValueError('invalid result')
        # No provider error text, credentials or unbounded arbitrary metadata reaches the model.
        rows = []
        for item in result['results'][:200]:
            if not isinstance(item, dict):
                raise ValueError('invalid row')
            url = str(item.get('url', ''))
            if not url.startswith('https://'):
                continue
            rows.append({k: str(item.get(k) or '')[:2048] for k in
                         ('title', 'url', 'cloud_type', 'password', 'source', 'datetime')})
        return {'query': query, 'results': rows,
                'matched_count': result.get('matched_count', len(rows)),
                'completeness': result.get('completeness', 'unknown'),
                'truncated': bool(result.get('has_more')),
                'verification': '链接有效性及文件内容未核验。'}
    except (ValueError, asyncio.TimeoutError) as exc:
        raise SearchFailure('搜索超时或返回格式异常，本次不扣额度。') from exc
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
