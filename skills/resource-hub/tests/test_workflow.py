import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import common
import progress
import resource as r
import search


def row(n, **kw):
    return dict(title='作品', url='https://pan.quark.cn/s/%012x' % n, cloud_type='quark', password='', **kw)


def metadata(row, link, args):
    return dict(row, link_check=link, content_status='metadata_observed', content={'files':[{'name':'正片.mp4'}], 'listing_complete':True})


class Workflow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [patch.object(common,'CACHE_ROOT',root), patch.object(progress,'CACHE_ROOT',root),
                        patch.object(search,'CONFIG',root/'credentials.json'), patch.object(common,'CONFIG',root/'credentials.json'),
                        patch.dict(os.environ, {}, clear=True)]
        for p in self.patches: p.start()
    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()
    def invoke(self, args, rows=None, verifier=metadata):
        out=io.StringIO()
        with patch.object(sys,'argv',['resource.py',*args]), contextlib.redirect_stdout(out), \
             patch.object(r,'run_json',return_value={'results':rows or [], 'matched_count':len(rows or []), 'completeness':'unknown'}), \
             patch.object(r,'batch_check',side_effect=lambda rows,timeout: [{'state':'ok'} for _ in rows]) as check, \
             patch.object(r,'verify',side_effect=verifier) as verify:
            r.main()
        return json.loads(out.getvalue()),check.call_count,verify.call_count
    def test_resume_keeps_second_half_of_batch(self):
        rows=[row(n) for n in range(12)]
        first,_,count=self.invoke(['search','作品','--task','series'],rows)
        self.assertEqual(count,5)
        self.assertEqual(len(first['pending_urls']),7)
        second,checks,count=self.invoke(['search','别名','--task','series'],rows)
        self.assertEqual(count,5)
        self.assertEqual(second['reused_count'],5)
        self.assertEqual(len(second['pending_urls']),2)
        third,_,count=self.invoke(['search','英文名','--task','series'],rows)
        self.assertEqual(count,2)
        self.assertFalse(third['pending_urls'])
        self.assertEqual(third['queries'],['作品','别名','英文名'])
    def test_empty_first_five_does_not_skip_sixth(self):
        seen=[]
        def inspect(item,link,args):
            seen.append(item['url'])
            return metadata(item,link,args) if item['url']==row(6)['url'] else dict(item,content_status='empty',content={'files':[], 'listing_complete':True})
        result,_,_=self.invoke(['search','作品'],[row(n) for n in range(1,11)],inspect)
        self.assertEqual(len(seen),10)
        self.assertTrue(any(x['content_status']=='metadata_observed' for x in result['results']))
    def test_alias_union_and_source_merge(self):
        self.invoke(['search','作品','--task','series','--search-only'],[row(1,source='plugin:a')])
        result,_,_=self.invoke(['search','别名','--task','series','--search-only'],[row(1,source='plugin:b'),row(2)])
        self.assertEqual(result['matched_count'],2)
        self.assertEqual(result['results'][0]['sources'],['plugin:a','plugin:b'])
    def test_verification_reused_across_tasks(self):
        self.invoke(['search','作品','--task','one'],[row(1)])
        result,checks,count=self.invoke(['search','作品','--task','two'],[row(1)])
        self.assertEqual((checks,count),(0,0))
        self.assertEqual(result['reused_count'],1)
    def test_recheck_is_bounded(self):
        for _ in range(2): self.invoke(['search','作品','--recheck','--search-only'],[row(1)])
        with self.assertRaisesRegex(ValueError,'两次'):
            self.invoke(['search','作品','--recheck'],[row(1)])
    def test_cooldown_and_expiry(self):
        args=type('Args',(),dict(max_files=300,max_requests=8,no_cache=False,end_time=time.monotonic()+60))()
        with patch.object(r,'run_json',side_effect=RuntimeError('HTTP Error 403')) as run:
            r.verify(row(1),{'state':'ok'},args)
            r.verify(row(2),{'state':'ok'},args)
            self.assertEqual(run.call_count,1)
        with patch.object(progress.time,'time',return_value=time.time()+301), patch.object(r,'run_json',return_value={'files':[],'listing_complete':True}) as run:
            self.assertEqual(r.verify(row(3),{'state':'ok'},args)['content_status'],'empty')
            self.assertEqual(run.call_count,1)
    def test_timeout_stays_pending(self):
        result,_,_=self.invoke(['search','作品'],[row(1)],lambda row,link,args:dict(row,verification_error='核验超时',content_status='unverified'))
        self.assertEqual(result['pending_urls'],[row(1)['url']])
        self.assertEqual(result['stop_reason'],'verification_incomplete')
    def test_setup_preserves_config_and_invalidates_token(self):
        search.CONFIG.write_text(json.dumps({'base_url':'https://example.org','username':'alice','password':'old','custom':'keep'}))
        token=common.cache_path('token','https://example.org\0alice')
        common.cache_put(token,{'ts':time.time(),'token':'old-token'})
        with patch('builtins.input',return_value='alice'),patch.object(search.getpass,'getpass',return_value='new'),contextlib.redirect_stdout(io.StringIO()): search.setup()
        self.assertEqual(json.loads(search.CONFIG.read_text())['base_url'],'https://example.org')
        self.assertEqual(json.loads(search.CONFIG.read_text())['password'],'new')
        self.assertFalse(token.exists())
        self.assertEqual(search.CONFIG.stat().st_mode & 0o777,0o600)
    def test_auth_test_forces_login_and_checks_search(self):
        with patch.object(sys,'argv',['search.py','--auth-test']),patch.object(search,'login',return_value='token') as login,patch.object(search,'post',return_value={'total':0}),contextlib.redirect_stdout(io.StringIO()) as out:
            search.main()
        self.assertFalse(login.call_args.kwargs['use_cache'])
        self.assertTrue(json.loads(out.getvalue())['authenticated'])
        self.assertNotIn('token',out.getvalue())
    def test_unknown_cache_short_final_cache_long(self):
        for flag,should_fetch in [(None,True),(False,True),(True,False)]:
            body={'merged_by_type':{'quark':[dict(url=row(1)['url'],note='作品')]}}
            if flag is not None: body['is_final']=flag
            with patch.object(sys,'argv',['search.py','作品']),patch.object(search,'cache_get',return_value={'ts':time.time()-30,'data':body}),patch.object(search,'login',return_value='token'),patch.object(search,'post',return_value=body) as post,contextlib.redirect_stdout(io.StringIO()):
                search.main()
            self.assertEqual(post.called,should_fetch)
    def test_zero_is_short_cached_even_if_final(self):
        body={'total':0,'is_final':True}
        with patch.object(sys,'argv',['search.py','作品']),patch.object(search,'cache_get',return_value={'ts':time.time()-30,'data':body}),patch.object(search,'login',return_value='token'),patch.object(search,'post',return_value=body) as post,contextlib.redirect_stdout(io.StringIO()): search.main()
        self.assertTrue(post.called)
    def test_normalize_preserves_sources_and_date(self):
        args=type('Args',(),dict(query='作品',limit=0,offset=0))()
        result=search.normalize({'merged_by_type':{'quark':[dict(url=row(1)['url'],source='plugin:a',datetime='2026-01-01'),dict(url=row(1)['url'],source='plugin:b')]}},args)
        self.assertEqual(result['results'][0]['sources'],['plugin:a','plugin:b'])
        self.assertEqual(result['results'][0]['datetime'],'2026-01-01')
        self.assertEqual(result['completeness'],'unknown')
    def test_task_coverage_and_official_result(self):
        self.invoke(['search','作品','--task','series','--search-only'],[row(1)])
        record=Path(self.tmp.name)/'record.json'
        record.write_text(json.dumps({'coverage':[{'series':'作品','missing':[2]}],'saved':[{'path':'AI转存/作品/01.mp4','task_status':'success'}], 'verified':[dict(row(1),content_status='metadata_observed',content={'files':[{'name':'01.mp4','access_token':'should-not-save'}],'listing_complete':True})]}))
        state,_,_=self.invoke(['progress','--task','series','--record',str(record)])
        self.assertEqual(state['coverage'][0]['missing'],[2])
        result,checks,count=self.invoke(['search','作品','--task','series'],[row(1)])
        self.assertEqual((checks,count),(0,0))
        self.assertEqual(result['results'][0]['verified_by'],'official')
        self.assertNotIn('access_token',json.dumps(result))
    def test_query_parameters_dedupe(self):
        self.assertEqual(r.canonical(row(1)['url']+'?utm_source=test'),row(1)['url'])
    def test_auth_entrypoint_forwards_timeout(self):
        with patch.object(sys,'argv',['resource.py','auth-test','--timeout','7']),patch.object(r.subprocess,'call',return_value=0) as call:
            with self.assertRaises(SystemExit) as done: r.main()
        self.assertEqual(done.exception.code,0)
        self.assertEqual(call.call_args.args[0][-3:],['--auth-test','--timeout','7.0'])
    def test_concurrent_aliases_preserve_candidates(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as executor:
            list(executor.map(lambda n: progress.update_task('shared',rows=[row(n)],query=str(n)),range(12)))
        state=progress.update_task('shared')
        self.assertEqual(len(state['candidates']),12)
        self.assertEqual(len(state['queries']),12)
    def test_empty_title_is_valid_candidate(self):
        item=row(1); item['title']=''
        result,_,_=self.invoke(['search','作品','--search-only'],[item])
        self.assertEqual(result['matched_count'],1)
    def test_all_bad_first_batch_continues(self):
        out=io.StringIO()
        rows=[row(n) for n in range(15)]
        def checks(items,timeout):
            return [{'state':'bad' if item['url'] in {x['url'] for x in rows[:10]} else 'ok'} for item in items]
        with patch.object(sys,'argv',['resource.py','search','作品']),contextlib.redirect_stdout(out),patch.object(r,'run_json',return_value={'results':rows}),patch.object(r,'batch_check',side_effect=checks),patch.object(r,'verify',side_effect=metadata) as verify:
            r.main()
        self.assertEqual(verify.call_count,5)
        self.assertEqual(json.loads(out.getvalue())['candidates_checked'],15)
    def test_errors_are_not_empty_results(self):
        args=type('Args',(),dict(query='作品',limit=0,offset=0))()
        with self.assertRaises(ValueError): search.normalize({'code':500,'data':{}},args)

if __name__=='__main__': unittest.main()
