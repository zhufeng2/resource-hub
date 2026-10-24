#!/usr/bin/env python3
"""Unified search and metadata verification entry point. Never saves cloud files."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit
import progress
from urllib.error import HTTPError, URLError

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

# 关键词里的修饰词会显著降低召回；命中时在输出里提示改用片名。
QUERY_NOISE = ('4k', '8k', '1080p', '720p', '高清', '超清', '蓝光', '臻彩', '杜比', 'hdr',
               '国语', '粤语', '中字', '双语', '字幕', '全集', '合集', '完整版', '未删减',
               '最新', '更新', '更至', '完结', 'mkv', 'mp4', '迅雷', '网盘', '下载')
try:
    from common import base_url
    from search import login, post, api_token
    from common import unwrap
except Exception:  # 批量检测不可用时退回逐条核验
    base_url = login = post = None


def run_json(script, args, timeout=360):
    result = subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('调用失败：' + (result.stderr.strip() or script))
    return json.loads(result.stdout)


def batch_check(rows, timeout=60):
    end = time.monotonic() + timeout
    def remaining():
        left = end - time.monotonic()
        if left <= 0:
            raise TimeoutError("批量检测达到时限")
        return left
    """一次登录 + 一次批量检测所有候选，避免每个候选重复登录。"""
    if not rows:
        return []
    if login is None:
        raise RuntimeError('batch_check_unavailable')
    base = base_url()
    token = login(base, remaining())
    payload = {'items': [{'disk_type': r['cloud_type'], 'url': r['url'],
                          'password': r.get('password') or ''} for r in rows]}
    data = None
    for attempt in range(2):
        try:
            data = post(base, '/api/check/links', payload, remaining(), token)
            break
        except HTTPError as exc:
            if exc.code == 401 and attempt == 0 and not api_token():
                token = login(base, remaining(), use_cache=False)
                continue
            if exc.code < 500 or attempt == 1:
                raise
        except (URLError, TimeoutError):
            if attempt == 1:
                raise
        time.sleep(min(0.3, remaining()))
    data = unwrap(data)
    results = data.get('results')
    if not isinstance(results, list) or len(results) != len(rows):
        raise RuntimeError('检测响应格式不兼容')
    return [{'state': r.get('state'), 'summary': r.get('summary') or ''} for r in results]


def verify(row, link, args):
    output = dict(row)
    output['link_check'] = link
    output['content_status'] = 'unverified'
    # 检测服务不可用时仍尝试直接枚举目录（分享链接本身可核验内容）。
    if link.get('state') == 'bad' or row['cloud_type'] != 'quark':
        return output
    try:
        if progress.get('cooldown', 'quark-public', 300):
            return dict(output, next_action='official_share_detail', reason='公开目录接口暂时受限，请使用夸克官方核验')
        cmd = [row['url'], '--max-files', str(args.max_files),
               '--max-requests', str(args.max_requests)]
        if row.get('password'):
            cmd += ['--password', row['password']]
        if args.no_cache:
            cmd += ['--no-cache']
        metadata = run_json('inspect_share.py', cmd, timeout=max(0.01, args.end_time - time.monotonic()))
        output['content'] = metadata
        output['content_status'] = 'metadata_observed'
        if not metadata.get('files') and metadata.get('listing_complete'):
            output['content_status'] = 'empty'
    except subprocess.TimeoutExpired:
        output['verification_error'] = '核验超时'
    except (RuntimeError, ValueError, KeyError) as exc:
        if re.search(r'(?<!\d)(403|429)(?!\d)', str(exc)):
            progress.put('cooldown', 'quark-public', {'restricted': True})
        output['verification_error'] = '核验未完成：%s' % str(exc)[:120]
        output['next_action'] = 'official_share_detail'
        output['reason'] = '公开目录接口失败；使用夸克官方 share-detail 复核，不能判失效'
    return output


def canonical(url):
    """把 .../s/<id>uc 与 .../s/<id> 视为同一分享。"""
    u = url.strip()
    parsed = urlsplit(u)
    if parsed.hostname == 'pan.quark.cn':
        match = re.fullmatch(r'/s/([a-fA-F0-9]+)(?:uc)?/?', parsed.path)
        if match:
            return 'https://pan.quark.cn/s/' + match.group(1)
    return u.rstrip('/')



JUNK = re.compile(r'星期[一二三四五六日]|\d{4}年\d{1,2}月\d{1,2}日|公众号|更多资源')


def relevance(title, query):
    """标题与片名的贴合度：命中词按长度加权，前缀/包含加分，日期流水标题减分。"""
    tokens = [t for t in re.split(r'[\s·|/、，,]+', query) if t]
    score = sum(len(t) for t in tokens if t in title)
    if title.startswith(query):
        score += 20
    elif query in title:
        score += 10
    return score - 20 if JUNK.search(title) else score


def select(paired, query, limit):
    """明确失效以外的候选均保留；优先核验 ok，其次 uncertain/unverified。"""
    usable = [pair for pair in paired if pair[1].get('state') != 'bad'
              and pair[0]['cloud_type'] == 'quark']
    usable.sort(key=lambda pair: (pair[1].get('state') == 'ok',
                                  relevance(pair[0]['title'], query)), reverse=True)
    return usable[:limit]


def dedupe(rows):
    seen, out = set(), []
    for row in rows:
        key = canonical(row['url'])
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    search = sub.add_parser('search', help='Search then check bounded candidates concurrently')
    search.add_argument('query')
    search.add_argument('--candidates', type=int, default=10)
    search.add_argument('--inspect', type=int, default=5, help='实际做目录核验的条数（默认 5）')
    search.add_argument('--results', type=int, default=0, help='本次候选池大小；0 为全部')
    search.add_argument('--offset', type=int, default=0, help='在完整排序候选池中接续的位置')
    search.add_argument('--cloud-types', nargs='+', default=['quark'])
    search.add_argument('--workers', type=int, default=4)
    search.add_argument('--deadline', type=float, default=60)
    search.add_argument('--max-files', type=int, default=300)
    search.add_argument('--max-requests', type=int, default=8)
    search.add_argument('--no-cache', action='store_true')
    search.add_argument('--task', help='同一系列及别名共用的任务名')
    search.add_argument('--recheck', action='store_true', help='绕过本地搜索缓存复查；每任务每关键词最多两次')
    search.add_argument('--search-only', action='store_true', help='只搜候选，暂不检链或枚举目录')
    state = sub.add_parser('progress', help='查看任务或记录覆盖清单与已验证的转存结果')
    state.add_argument('--task', required=True)
    state.add_argument('--record', help='JSON 文件，仅接受 coverage 和 saved 数组')
    auth = sub.add_parser('auth-test', help='验证当前凭据与搜索权限')
    auth.add_argument('--timeout', type=float, default=60)
    for name in ['setup', 'check', 'inspect']:
        child = sub.add_parser(name, add_help=False)
        child.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command == 'progress':
        record = json.loads(Path(args.record).read_text()) if args.record else None
        if record is not None and (not isinstance(record, dict) or set(record) - {'coverage', 'saved', 'verified'}):
            raise ValueError('只接受 coverage、saved 和 verified 字段')
        updates = (record or {}).get('verified', [])
        if not isinstance(updates, list):
            raise ValueError('verified 必须是数组')
        validated = []
        for item in updates:
            if not isinstance(item, dict) or not isinstance(item.get('url'), str) or item.get('content_status') not in ('metadata_observed', 'empty', 'unavailable'):
                raise ValueError('verified 需要 url 与 content_status')
            content = item.get('content', {})
            if not isinstance(content, dict) or not isinstance(content.get('files'), list):
                raise ValueError('官方核验记录需要 content.files')
            if item['content_status'] == 'empty' and (content['files'] or content.get('listing_complete') is not True):
                raise ValueError('empty 需要完整且空的文件列表')
            url = canonical(item['url'])
            clean = {'url': url, 'content_status': item['content_status'], 'verified_by': 'official',
                     'link_check': {'state': 'bad' if item['content_status'] == 'unavailable' else 'ok'},
                     'content': {'listing_complete': content.get('listing_complete', False),
                                 'files': [{k:v for k,v in f.items() if k in ('name','path','size','fid','is_video')} for f in content['files'] if isinstance(f,dict)]}}
            key = base_url() + '\0' + url + '\0' + item.get('password', '')
            validated.append((key, clean))
        value = progress.update_task(args.task, record=record)
        for key, clean in validated:
            progress.put('verification', key, clean)
        print(json.dumps(value, ensure_ascii=False))
        return
    if args.command != 'search':
        script = {'setup': 'search.py', 'auth-test': 'search.py', 'check': 'check.py', 'inspect': 'inspect_share.py'}[args.command]
        extra = ['--auth-test', '--timeout', str(args.timeout)] if args.command == 'auth-test' else ['--setup', *args.arguments] if args.command == 'setup' else args.arguments
        sys.exit(subprocess.call([sys.executable, str(SCRIPTS / script), *extra]))
    if not 1 <= args.workers <= 8:
        parser.error('workers 必须为 1–8')
    if not 1 <= args.candidates <= 100:
        parser.error('candidates 必须为 1–100')
    if not 1 <= args.inspect <= 10:
        parser.error('inspect 必须为 1–10')
    if args.results < 0 or args.offset < 0 or args.deadline <= 0:
        parser.error('results、offset 不能为负数，deadline 必须大于 0')
    started = time.monotonic()
    args.end_time = started + args.deadline
    noise = [w for w in QUERY_NOISE if w.casefold() in args.query.casefold()]
    search_args = [args.query, '--limit', '0', '--timeout', str(args.deadline),
                   '--cloud-types', *args.cloud_types]
    task = args.task or args.query
    refresh_key = json.dumps([base_url(), task, args.query], ensure_ascii=False)
    refreshes = progress.get('refresh', refresh_key, 600) or {'count': 0}
    if args.recheck and refreshes['count'] >= 2:
        raise ValueError('本任务该关键词已复查两次；请处理候选或换有依据的别名，稍后再查')
    if args.no_cache or args.recheck:
        search_args.append('--no-cache')
    data = run_json('search.py', search_args, timeout=args.deadline)
    if args.recheck:
        progress.put('refresh', refresh_key, {'count': refreshes['count'] + 1})
    search_done = time.monotonic()
    incoming = []
    for row in data['results']:
        row['url'] = canonical(row['url'])
        incoming.append(row)
    state = progress.update_task(task, rows=incoming, query=args.query)
    allowed = set(args.cloud_types)
    pooled = sorted((r for r in state['candidates'].values()
                     if 'all' in allowed or r['cloud_type'] in allowed),
                    key=lambda r: max(relevance(t, args.query) for t in (r.get('titles') or [r['title']])),
                    reverse=True)
    # Offset remains a legacy view control; task queue is the supported resume mechanism.
    rows = pooled[args.offset:args.offset + args.results] if args.results else pooled[args.offset:]
    results, pending, inspected, checked, reused = {}, [], 0, 0, 0
    for row in rows:
        key = base_url() + '\0' + row['url'] + '\0' + row.get('password', '')
        previous = None if args.no_cache else progress.get('verification', key, progress.TTL)
        if previous and previous.get('next_action') and not progress.get('verification', key, 300):
            previous = None
        if previous:
            results[row['url']] = dict(previous, **row, reused=True)
            reused += 1
        else:
            pending.append((key, row))
    stop_reason = 'search_only' if args.search_only else 'candidate_pool_exhausted'
    while pending and not args.search_only:
        remaining = args.end_time - time.monotonic()
        if remaining <= 0:
            stop_reason = 'deadline'
            break
        batch = pending[:args.candidates]
        links = []
        missing = []
        for key, row in batch:
            link = None if args.no_cache else progress.get('link', key, progress.TTL)
            links.append(link)
            if link is None:
                missing.append((len(links)-1, key, row))
        if missing:
            try:
                fresh = batch_check([r for _,_,r in missing], timeout=min(20, remaining/2))
                checked += len(fresh)
                for (idx,key,_), link in zip(missing, fresh):
                    links[idx] = link
                    progress.put('link', key, link)
            except Exception as exc:
                for idx,_,_ in missing:
                    links[idx] = {'state': 'unverified', 'summary': '批量检测未完成：%s' % str(exc)[:80]}
        picked = select([(row,link) for (_,row),link in zip(batch,links)], args.query, args.inspect)
        outputs = {}
        for (key,row),link in zip(batch,links):
            if link.get('state') == 'bad' or row['cloud_type'] != 'quark':
                outputs[row['url']] = dict(row, link_check=link, content_status='unverified', reason='link_bad' if link.get('state') == 'bad' else 'unsupported_cloud')
        if picked:
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = [(row,executor.submit(verify,row,link,args)) for row,link in picked]
                for row,future in futures:
                    outputs[row['url']] = future.result()
            inspected += len(picked)
        consumed = set(outputs)
        for key,row in batch:
            if row['url'] in outputs:
                output = outputs[row['url']]
                results[row['url']] = output
                # A timeout stays pending on the next invocation; successful metadata
                # and official handoffs can be reused across aliases.
                if not output.get('verification_error') or output.get('next_action'):
                    progress.put('verification', key, output)
        pending = [(key,row) for key,row in pending if row['url'] not in consumed]
        observed = any(r.get('content_status') == 'metadata_observed' and r.get('content',{}).get('files') for r in outputs.values())
        official = any(r.get('next_action') == 'official_share_detail' for r in outputs.values())
        if observed or official:
            stop_reason = 'review_metadata' if observed else 'official_verification_required'
            break
    for _,row in pending:
        results[row['url']] = dict(row, link_check={'state':'unverified'}, content_status='unverified', reason='not_inspected')
    ordered = [results[r['url']] for r in rows]
    unfinished = [r['url'] for r in ordered if r.get('reason') == 'not_inspected' or (r.get('verification_error') and not r.get('next_action'))]
    handoff = [r['url'] for r in ordered if r.get('next_action') == 'official_share_detail']
    if handoff and stop_reason == 'candidate_pool_exhausted':
        stop_reason = 'official_verification_required'
    if unfinished and stop_reason == 'candidate_pool_exhausted':
        stop_reason = 'verification_incomplete'
    data.update(results=ordered, matched_count=len(pooled), returned_count=len(ordered),
                task=task, queries=state['queries'], coverage=state['coverage'], saved=state['saved'],
                candidates_checked=checked, directories_inspected=inspected, reused_count=reused,
                pending_urls=unfinished, official_pending_urls=handoff,
                offset=args.offset, next_offset=None, has_more=bool(unfinished or handoff), stop_reason=stop_reason,
                scope='本任务已搜关键词和网盘类型；API 完整性未知不等于穷尽来源',
                timing_seconds={'search': round(search_done-started,3), 'total': round(time.monotonic()-started,3)})
    progress.put('task-result', task, {'pending_urls': unfinished, 'official_pending_urls': handoff,
                                     'stop_reason': stop_reason})
    if noise:
        suggestion = args.query
        for word in noise:
            suggestion = re.sub(re.escape(word), '', suggestion, flags=re.I)
        suggestion = ' '.join(suggestion.split())[:24] or args.query[:24]
        data['query_note'] = ('关键词含修饰词 %s，容易搜不到；建议只用片名重搜，例如「%s」。'
                              % ('、'.join(noise), suggestion))
    print(json.dumps(data, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({'error': 'search_failed',
                          'message': '搜索失败，不等于零结果；%s' % str(exc)[:160]},
                         ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
