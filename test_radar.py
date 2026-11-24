import concurrent.futures
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import radar
import server

TRACKED = ('octo', 'demo', 7)
CONFIG = {'github_login': 'tester', 'tracked_pr': TRACKED}
PR_URL = 'https://github.com/octo/demo/pull/7'
DATA = Path(__file__).resolve().parent / 'data'
DATA.mkdir(exist_ok=True)

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=DATA)
        self.root = Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def test_invalid_persisted_selection_fails_closed(self):
        import sqlite3
        d=self.root/'db'; store=radar.Store(d)
        from contextlib import closing
        with closing(sqlite3.connect(store.path)) as db, db: db.execute('UPDATE selection SET issue_id=?', ('<script>alert(1)</script>',))
        before=store.path.read_bytes()
        with self.assertRaises((ValueError, RuntimeError)): radar.Store(d)
        self.assertEqual(store.path.read_bytes(),before)
        with self.assertRaises((ValueError, RuntimeError)): store.selection()

    def test_gh_rejects_unapproved_routes_and_parameters(self):
        with patch('radar.subprocess.run') as run:
            for endpoint, params in [('graphql?x=1',{'query':'mutation {x}'}), ('https://evil.test/x',None), ('repos/a/../issues/1',None), ('--help',None), ('user',{'x':'y'}), ('search/issues',{'q':'x','query':'mutation'}), ('search/issues',{'q':'x\nfoo'})]:
                with self.subTest(endpoint=endpoint,params=params), self.assertRaises(ValueError): radar.gh(endpoint,params)
            run.assert_not_called()

    def test_check_completeness_and_legacy_status(self):
        pr={'html_url':PR_URL,'head':{'sha':'a'*40}}
        run={'status':'completed','conclusion':'success'}
        for checks,status,expected in [({'total_count':101,'check_runs':[run]*100},{'state':'success','total_count':1,'statuses':[{'state':'success'}]},None),({'total_count':0,'check_runs':[]},{'state':'success','total_count':1,'statuses':[{'state':'success'}]},None),({'total_count':1,'check_runs':[run]},{'state':'failure','total_count':1,'statuses':[{'state':'failure'}]},'failure'),({'total_count':1,'check_runs':[run]},{'state':'success','total_count':1,'statuses':[{'state':'success'}]},'success')]:
            with self.subTest(expected=expected), patch('radar.gh',side_effect=[{'login':'other'},pr,checks,status]):
                self.assertEqual(radar.account_pr(CONFIG)[2]['check_status'],expected)

    def test_schema_and_revision_corruption_does_not_overwrite(self):
        import sqlite3
        from contextlib import closing
        for schema, values in [('CREATE TABLE selection (bad TEXT)', None), ('CREATE TABLE selection (singleton INTEGER, issue_id TEXT, revision)', (1,'a/b#1','bad'))]:
            d=self.root/str(len(list(self.root.iterdir()))); d.mkdir(); path=d/'radar.sqlite'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute(schema)
                if values: db.execute('INSERT INTO selection VALUES (?,?,?)', values)
            before=path.read_bytes()
            with self.assertRaises((RuntimeError, sqlite3.DatabaseError)): radar.Store(d)
            self.assertEqual(path.read_bytes(),before)

    def test_ui_displays_unscored_and_safe_text(self):
        js=(Path(__file__).parent/'app.js').read_text(encoding='utf8')
        self.assertIn("'Puanlanmadı'",js)
        self.assertIn("field('Yazar',d.author)",js)
        self.assertIn("field('Oluşturulma',date(d.created_at))",js)
        self.assertIn('node.textContent = String(text)',js)
        self.assertNotIn('innerHTML',js)

    def test_gh_allowed_routes_and_bad_values(self):
        class Fake: returncode=0; stdout=b'{}'
        routes=[('user',None),('search/issues',{'q':'is:issue','per_page':20}),('repos/a/b',None),('repos/a/b/issues/1',None),('repos/a/b/issues/1/comments',{'per_page':20}),('repos/a/b/issues/1/timeline',{'per_page':20}),('repos/a/b/pulls/7',None),('repos/a/b/contents/.github/CONTRIBUTING.md',None),('repos/a/b/commits/'+('a'*40)+'/check-runs',{'per_page':100}),('repos/a/b/commits/'+('a'*40)+'/status',None)]
        with patch('radar.subprocess.run',return_value=Fake()) as run:
            for endpoint,params in routes: radar.gh(endpoint,params)
            self.assertEqual(run.call_count,len(routes))
            run.reset_mock()
            for endpoint,params in [('repos/./b',None),('repos/a/b/pulls/0',None),('repos/a/b/pulls/7/files',None),('repos/a/b/issues/1?x=1',None),('repos/a/b/issues/1#x',None),('repos/a/b/contents/other',None),('search/issues',{'q':'x'*501}),('search/issues',{'q':'x','per_page':101}),('search/issues',{'q':'x','per_page':True})]:
                with self.subTest(endpoint=endpoint), self.assertRaises(ValueError): radar.gh(endpoint,params)
            run.assert_not_called()

    def test_detail_nonstring_author_and_created_unknown(self):
        issue={'html_url':'https://github.com/a/b/issues/1','number':1,'title':'Title','labels':[],'user':{'login':123},'created_at':{}}
        def get(endpoint,params=None):
            if endpoint=='repos/a/b/issues/1': return issue
            if endpoint=='repos/a/b': return {'private':False}
            raise RuntimeError('unavailable')
        with patch('radar.gh',side_effect=get): detail=radar.detail('a/b#1')
        self.assertIsNone(detail['author']); self.assertIsNone(detail['created_at'])

    def test_validate(self):
        for s in ['../a#1','a/b#0','a/b#1?x','a/b#1;foo','a/b#01']:
            with self.assertRaises(ValueError): radar.parse_id(s)
        self.assertEqual(radar.parse_id('abc/xyz#12'), ('abc','xyz',12))
    def test_scan_partial_dedup(self):
        item = dict(html_url='https://github.com/a/b/issues/1',number=1,title='<script>x</script>',labels=[{'name':'good first issue'}],updated_at='x')
        with patch('radar.gh', side_effect=[{'items':[item], 'total_count':1, 'incomplete_results':False}, RuntimeError(), {'items':[item], 'total_count':1, 'incomplete_results':False}]):
            result = radar.scan()
        self.assertEqual(len(result['items']),1); self.assertTrue(result['incomplete']); self.assertTrue(result['warnings'])
        self.assertEqual(result['items'][0]['title'], '<script>x</script>')
    def test_selection_race_and_restart(self):
        store = radar.Store(self.root / 'data')
        def write(n):
            try: return store.select('a/b#'+str(n),0)
            except radar.Conflict: return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: out=list(pool.map(write,[1,2]))
        self.assertEqual(sum(x is not None for x in out),1)
        self.assertEqual(radar.Store(self.root / 'data').selection()['revision'],1)
    def test_corrupt(self):
        d=self.root/'data'; d.mkdir(); (d/'radar.sqlite').write_bytes(b'not sqlite')
        with self.assertRaises(Exception): radar.Store(d)
        self.assertEqual((d/'radar.sqlite').read_bytes(),b'not sqlite')
    def test_pr_and_contribution(self):
        pr={'html_url':PR_URL,'created_at':'2026-11-16T02:00:00Z','title':'x','state':'open','draft':True,'merged':False,'head':{'sha':'a'*40}}
        graph={'data':{'user':{'contributionsCollection':{'pullRequestContributions':{'nodes':[{'pullRequest':{'number':7,'url':pr['html_url'],'repository':{'nameWithOwner':'octo/demo'}}}], 'pageInfo':{'hasNextPage':False}}}}}}
        with patch('radar.gh',side_effect=[{'login':'tester'},pr,{'total_count':1,'check_runs':[{'status':'completed','conclusion':'failure'}]}, {'state':'success','total_count':0,'statuses':[]}]), patch('radar.contribution_graph',return_value=graph,create=True):
            account, warning, result=radar.account_pr(CONFIG)
        self.assertEqual(account,'tester'); self.assertEqual(result['check_status'],'failure'); self.assertIs(result['contribution_visible'],True); self.assertIsNone(warning)
    def test_contribution_false_incomplete_and_error(self):
        def graph(nodes, more):
            return {'data':{'user':{'contributionsCollection':{'pullRequestContributions':{'nodes':nodes,'pageInfo':{'hasNextPage':more}}}}}}
        other={'pullRequest':{'number':7,'url':'https://github.com/other/repo/pull/7','repository':{'nameWithOwner':'other/repo'}}}
        for response, expected in [(graph([other],False),False),(graph([],True),None),({'errors':[{'message':'failure'}]},None),({'data':{}},None),(graph([{}],False),None)]:
            with self.subTest(response=response), patch('radar.contribution_graph',return_value=response):
                self.assertIs(radar.contribution_visible('2026-11-16T00:00:00Z',None,TRACKED,'tester'),expected)
        with patch('radar.contribution_graph',side_effect=RuntimeError()):
            self.assertIsNone(radar.contribution_visible('2026-11-16T00:00:00Z',None,TRACKED,'tester'))
    def test_wrong_account_does_not_query_graph(self):
        pr={'html_url':PR_URL,'created_at':'2026-11-16T00:00:00Z','head':{}}
        with patch('radar.gh',side_effect=[{'login':'other'},pr]), patch('radar.contribution_graph') as graph:
            account, warning, result=radar.account_pr(CONFIG)
        self.assertIsNone(account); self.assertIsNone(result['contribution_visible']); self.assertTrue(warning); graph.assert_not_called()
    def test_graph_query_is_fixed_read_only_and_utc(self):
        class Fake: returncode=0; stdout=b'{}'
        with patch('radar.subprocess.run',return_value=Fake()) as run:
            radar.contribution_graph('2026-11-16T01:00:00+03:00','tester')
        args=run.call_args.args[0]
        self.assertEqual(args[:3],['gh','api','graphql']); self.assertIn('query='+radar.CONTRIBUTION_QUERY,args)
        self.assertIn('login=tester',args); self.assertIn('from=2026-11-15T00:00:00Z',args); self.assertIn('to=2026-11-16T00:00:00Z',args)
        self.assertNotIn('mutation',radar.CONTRIBUTION_QUERY.lower())
        with self.assertRaises(RuntimeError): radar.contribution_graph('2026-11-16T00:00:00Z mutation','tester')
        with self.assertRaises(ValueError): radar.gh('graphql',{'query':'mutation { x }'})
    def test_malformed_search_is_incomplete(self):
        with patch('radar.gh',return_value={'items':[], 'incomplete_results':False, 'total_count':'bad'}):
            result=radar.scan()
        self.assertTrue(result['incomplete']); self.assertTrue(result['warnings'])
    def test_detail_partial_and_query(self):
        issue={'html_url':'https://github.com/a/b/issues/1','number':1,'title':'Title','labels':[],'state':'open','assignees':[],'user':{'login':'<script>x</script>'},'created_at':'2026-01-01T00:00:00Z'}
        meta={'private':False,'default_branch':'main','license':{'spdx_id':'MIT'}}
        calls=[]
        def get(endpoint, params=None):
            calls.append((endpoint,params))
            if endpoint=='repos/a/b/issues/1': return issue
            if endpoint=='repos/a/b': return meta
            if endpoint=='search/issues': return {'items':[], 'total_count':0, 'incomplete_results':True}
            raise RuntimeError('unavailable')
        with patch('radar.gh',side_effect=get): detail=radar.detail('a/b#1')
        self.assertEqual(detail['ai_policy'],'bilinmiyor'); self.assertEqual(detail['license'],'MIT'); self.assertEqual(detail['author'],'<script>x</script>'); self.assertEqual(detail['created_at'],'2026-01-01T00:00:00Z')
        self.assertTrue(any('eksik' in x for x in detail['limitations']))
        self.assertIn('repo:a/b', next(x[1]['q'] for x in calls if x[0]=='search/issues'))
    def test_gh_readonly_args(self):
        class Fake: returncode=0; stdout=b'{}'
        with patch('radar.subprocess.run',return_value=Fake()) as run: radar.gh('search/issues',{'q':'is:issue is:public'})
        args=run.call_args
        self.assertEqual(args.args[0][:4],['gh','api','-X','GET']); self.assertEqual(args.kwargs['timeout'],20); self.assertNotIn('shell',args.kwargs)
    def test_http(self):
        app=server.App(self.root); srv=server.Server(app); thread=threading.Thread(target=srv.serve_forever); thread.start()
        def req(method,path,body=None,headers=None):
            c=http.client.HTTPConnection('127.0.0.1',srv.server_port,timeout=5)
            c.request(method,path,body,headers or {}); r=c.getresponse(); data=r.read(); c.close(); return r.status,json.loads(data)
        try:
            with patch('radar.account_pr',return_value=(None,None,None)):
                status,boot=req('GET','/api/bootstrap'); self.assertEqual(status,200)
                self.assertIsNone(boot['selection']); self.assertEqual(app.store.selection()['revision'],0)
            headers={'Origin':srv.origin,'Content-Type':'application/json','X-Radar-Token':app.key}
            self.assertEqual(req('GET','/api/bootstrap',headers={'Host':'evil.test'})[0],403)
            self.assertEqual(req('POST','/api/scan','{}',dict(headers,Origin='http://evil.test'))[0],403)
            bad=dict(headers); bad['X-Radar-Token']='wrong'; self.assertEqual(req('POST','/api/scan','{}',bad)[0],403)
            self.assertEqual(req('POST','/api/scan','{}',dict(headers,**{'Content-Type':'text/plain'}))[0],415)
            self.assertEqual(req('POST','/api/scan','x',headers)[0],400)
            self.assertEqual(req('POST','/api/scan',' '*32769,headers)[0],400)
            fake={'items':[{'id':'a/b#1'}], 'incomplete':False}
            with patch('radar.scan',return_value=fake): self.assertEqual(req('POST','/api/scan','{}',headers)[0],200)
            issue={'html_url':'https://github.com/a/b/issues/1','number':1,'title':'Title','labels':[], 'user':{'login':'<script>x</script>'},'created_at':'2026-01-01T00:00:00Z'}
            def github(endpoint, params=None):
                if endpoint=='repos/a/b/issues/1': return issue
                if endpoint=='repos/a/b': return {'private':False}
                raise RuntimeError('unavailable')
            with patch('radar.gh', side_effect=github):
                status, payload=req('POST','/api/detail',json.dumps({'id':'a/b#1'}),headers)
            self.assertEqual(status,200); self.assertEqual(payload['detail']['author'],'<script>x</script>'); self.assertEqual(payload['detail']['created_at'],'2026-01-01T00:00:00Z')
            self.assertEqual(req('POST','/api/select',json.dumps({'id':'a/b#1','revision':0}),headers)[0],200)
            self.assertEqual(req('POST','/api/select',json.dumps({'id':'a/b#1','revision':0}),headers)[0],409)
        finally: srv.shutdown(); srv.server_close(); thread.join()

class Config(unittest.TestCase):
    def test_load_config_defaults_env_and_file(self):
        with tempfile.TemporaryDirectory(dir=DATA) as tmp:
            self.assertEqual(radar.load_config(tmp, {}), {'github_login': None, 'tracked_pr': None})
            (Path(tmp) / 'config.json').write_text(json.dumps({'github_login': 'filelogin', 'tracked_pr': 'octo/demo#7'}), encoding='utf-8')
            self.assertEqual(radar.load_config(tmp, {}), {'github_login': 'filelogin', 'tracked_pr': ('octo', 'demo', 7)})
            env = {'RADAR_GITHUB_LOGIN': 'envlogin', 'RADAR_TRACKED_PR': 'a/b#1'}
            self.assertEqual(radar.load_config(tmp, env), {'github_login': 'envlogin', 'tracked_pr': ('a', 'b', 1)})

    def test_load_config_rejects_bad_values(self):
        with tempfile.TemporaryDirectory(dir=DATA) as tmp:
            for env in [{'RADAR_TRACKED_PR': 'not-a-pr'}, {'RADAR_TRACKED_PR': '../x#1'}, {'RADAR_GITHUB_LOGIN': 'bad login!'}]:
                with self.subTest(env=env), self.assertRaises(ValueError): radar.load_config(tmp, env)
            (Path(tmp) / 'config.json').write_text('[1]', encoding='utf-8')
            with self.assertRaises(ValueError): radar.load_config(tmp, {})

    def test_no_tracked_pr_means_no_pr_requests(self):
        with patch('radar.gh', side_effect=[{'login': 'anyone'}]) as gh:
            account, warning, pr = radar.account_pr({'github_login': None, 'tracked_pr': None})
        self.assertEqual(account, 'anyone'); self.assertIsNone(pr); self.assertIsNone(warning); self.assertEqual(gh.call_count, 1)

    def test_expected_login_mismatch_is_not_trusted(self):
        with patch('radar.gh', side_effect=[{'login': 'someone-else'}]):
            account, warning, pr = radar.account_pr({'github_login': 'tester', 'tracked_pr': None})
        self.assertIsNone(account); self.assertTrue(warning)

    def test_no_personal_identifiers_in_source(self):
        root = Path(__file__).resolve().parent
        for name in ('radar.py', 'server.py', 'app.js', 'index.html', 'README.md'):
            text = (root / name).read_text(encoding='utf-8').lower()
            for needle in ('kemalg', 'rizgarozan', 'turkish-rag-eval'):
                self.assertNotIn(needle, text, name)

class Live(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('RADAR_LIVE') == '1', 'live read not requested')
    def test_live(self):
        with tempfile.TemporaryDirectory(dir=DATA) as tmp:
            app=server.App(Path(tmp)); srv=server.Server(app)
            thread=threading.Thread(target=srv.serve_forever); thread.start()
            try:
                c=http.client.HTTPConnection('127.0.0.1',srv.server_port,timeout=120)
                c.request('GET','/api/bootstrap'); r=c.getresponse(); boot=json.loads(r.read()); self.assertEqual(r.status,200); c.close()
                c=http.client.HTTPConnection('127.0.0.1',srv.server_port,timeout=120)
                headers={'Origin':srv.origin,'Content-Type':'application/json','X-Radar-Token':boot['token']}
                c.request('POST','/api/scan','{}',headers); r=c.getresponse(); obj=json.loads(r.read()); self.assertEqual(r.status,200); c.close()
                result=obj['scan']; self.assertEqual(len(result['queries']),3)
                print('LIVE account=', boot['account'], 'PR=',bool(boot['pr']), 'check=',boot['pr']['check_status'] if boot['pr'] else None, 'contribution=',boot['pr']['contribution_visible'] if boot['pr'] else None, 'warnings=',boot['warning'], 'items=',len(result['items']), 'incomplete=',result['incomplete'], 'scan_warnings=',result['warnings'])
                self.assertGreater(len(result['items']),0)
                ident=result['items'][0]['id']
                c=http.client.HTTPConnection('127.0.0.1',srv.server_port,timeout=120)
                c.request('POST','/api/detail',json.dumps({'id':ident}),headers); r=c.getresponse(); detail=json.loads(r.read()); self.assertEqual(r.status,200); c.close()
                self.assertEqual(detail['detail']['id'],ident); print('LIVE detail=',ident,'limitations=',len(detail['detail']['limitations']))
            finally: srv.shutdown(); srv.server_close(); thread.join()

if __name__=='__main__': unittest.main()
