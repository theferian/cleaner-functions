"""Run from repository root: py -m unittest -q tests.test_mass_reader_v01
Or py -m pytest -q tests/test_mass_reader_v01.py
"""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from urllib.request import urlopen, Request
import threading

from mass_reader_v01.core import Store, Reader, decision, pathmatch
from mass_reader_v01.server import build_server

class MassReaderTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.base=Path(self.t.name)
        self.folder=self.base/'source'
        self.folder.mkdir()
        (self.folder/'a.xlsx').write_text('unchanged document',encoding='utf8')
        (self.folder/'b.PDF').write_bytes(b'%PDF fake')
        (self.folder/'no_extension').write_text('hi')
        (self.folder/'~$temp.xlsx').write_text('skip')
        hidden=self.folder/'Archive';hidden.mkdir()
        (hidden/'locked.xlsx').write_text('approved')
        (hidden/'other.txt').write_text('other')
        second=self.folder/'Nested';second.mkdir()
        (second/'c.csv').write_text('a,b\n1,2')
        self.db=self.base/'working'/'state.sqlite3'
        self.store=Store(self.db)
        self.reader=Reader(self.store)
        self.wid=self.store.create_workspace('Test Department')

    def tearDown(self):self.t.cleanup()

    def scope(self,**kw):
        data=dict(root=str(self.folder),label='Project Folder',recursive=True,include=['*'],exclude=['Archive/**','~$*'],override=[])
        data.update(kw)
        return self.store.save_scope(self.wid,data)

    def start(self,budget=0):
        rid=self.store.create_run(self.wid,budget)
        self.reader.start(rid,budget)
        return rid

    def wait(self,rid,until=None):
        until=until or ('PAUSED','COMPLETED','COMPLETED_WITH_ERRORS','CANCELLED')
        for _ in range(300):
            x=self.store.run(rid)['run']['status']
            if x in until:return x
            time.sleep(.01)
        raise AssertionError('Scan did not finish or pause: '+str(self.store.run(rid)))

    def test_scope_patterns_and_overrides(self):
        self.assertEqual(decision('Archive/x.xlsx',False,['*.xlsx'],['Archive/**'],[]),'EXCLUDED')
        self.assertEqual(decision('Archive/x.xlsx',False,['*.pdf'],['Archive/**'],['Archive/x.xlsx']),'INCLUDED')
        self.assertTrue(pathmatch('Archive','Archive/**',True))
        self.assertTrue(pathmatch('sub/Archive/a.xlsx','**/Archive/**'))
        self.assertEqual(decision('hello.txt',False,['*.xlsx'],[],[]),'OUTSIDE_INCLUDE')

    def test_end_to_end_scope_and_progress(self):
        self.scope()
        rid=self.start();self.assertEqual(self.wait(rid),'COMPLETED')
        r=self.store.run(rid)
        self.assertEqual(r['run']['processed_files'],5)  # Archive skipped, ~temp included as EXCLUDED
        self.assertEqual(r['run']['included_files'],4)
        self.assertEqual(r['run']['excluded_files'],1)
        self.assertEqual(r['areas'][0]['folders_skipped'],1)
        files=self.store.list_files(self.wid,limit=100)['files']
        self.assertIn('UNSUPPORTED_OR_UNKNOWN',[f['file_type'] for f in files])
        self.assertFalse((self.folder/'new_result.xlsx').exists())

    def test_override_tunnels_through_excluded_folder(self):
        self.scope(override=['Archive/locked.xlsx'])
        rid=self.start();self.wait(rid)
        x={f['relative']:f for f in self.store.list_files(self.wid)['files']}
        self.assertEqual(x['Archive/locked.xlsx']['scope_decision'],'INCLUDED')
        self.assertEqual(x['Archive/other.txt']['scope_decision'],'EXCLUDED')

    def test_non_recursive_root_only(self):
        self.scope(recursive=False)
        rid=self.start();self.wait(rid)
        x={f['relative'] for f in self.store.list_files(self.wid)['files']}
        self.assertNotIn('Nested/c.csv',x)
        self.assertIn('a.xlsx',x)

    def test_batch_pause_resume_without_count_inflation(self):
        self.scope()
        rid=self.start(budget=2)
        self.assertEqual(self.wait(rid),'PAUSED')
        self.assertEqual(self.store.run(rid)['run']['processed_files'],2)
        self.reader.start(rid,budget=2)
        self.assertEqual(self.wait(rid),'PAUSED')
        self.reader.start(rid,budget=0)
        self.assertEqual(self.wait(rid),'COMPLETED')
        self.assertEqual(self.store.run(rid)['run']['processed_files'],5)
        with self.store.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM observations WHERE run_id=?',(rid,)).fetchone()[0],5)

    def test_restart_resumes_run_and_preserves_history(self):
        self.scope()
        rid=self.start(budget=1);self.wait(rid)
        newStore=Store(self.db);newReader=Reader(newStore)
        newReader.start(rid,budget=0)
        for _ in range(300):
            if newStore.run(rid)['run']['status']=='COMPLETED':break
            time.sleep(.01)
        self.assertEqual(newStore.run(rid)['run']['status'],'COMPLETED')
        self.assertEqual(newStore.run(rid)['run']['processed_files'],5)
        self.assertTrue(newStore.run(rid)['events'])

    def test_second_run_detects_changes(self):
        self.scope()
        rid1=self.start();self.wait(rid1)
        (self.folder/'a.xlsx').write_text('different new version',encoding='utf8')
        rid2=self.start();self.wait(rid2)
        r=self.store.run(rid2)['run']
        self.assertEqual(r['changed_files'],1)
        self.assertEqual(r['new_files'],0)
        self.assertEqual(r['unchanged_files'],4)
        self.assertNotEqual(rid1,rid2)

    def test_exact_file_root_and_pdf_format(self):
        self.store.save_scope(self.wid,dict(root=str(self.folder/'b.PDF'),recursive=True,include=['*'],exclude=[]))
        rid=self.start();self.assertEqual(self.wait(rid),'COMPLETED')
        fs=self.store.list_files(self.wid)['files'];self.assertEqual(len(fs),1)
        self.assertEqual(fs[0]['file_type'],'PDF')

    def test_scope_mutations_blocked_during_paused_run(self):
        self.scope();rid=self.start(budget=1);self.wait(rid)
        with self.assertRaises(ValueError):self.scope(label='Other')
        self.store.request(rid,'cancel')
        self.scope(label='Other')

    def test_unavailable_root_reports_error(self):
        self.scope(root=str(self.base/'missing'))
        rid=self.start();self.assertEqual(self.wait(rid),'COMPLETED_WITH_ERRORS')
        self.assertEqual(self.store.run(rid)['areas'][0]['folders_failed'],1)

    def test_local_http_api(self):
        srv=build_server(self.store,self.reader,host='127.0.0.1',port=0)
        th=threading.Thread(target=srv.serve_forever,daemon=True);th.start()
        url='http://127.0.0.1:'+str(srv.server_address[1])
        try:
            with urlopen(url+'/api/health',timeout=5) as r:self.assertTrue(json.load(r)['ok'])
            req=Request(url+'/api/workspaces',data=json.dumps({'name':'Remote Workspace'}).encode('utf8'),headers={'Content-Type':'application/json'},method='POST')
            with urlopen(req,timeout=5) as r:self.assertEqual(r.status,201)
            with urlopen(url+'/app.js',timeout=5) as r:self.assertIn(b'function translate()',r.read())
        finally:srv.shutdown();srv.server_close();th.join(timeout=2)

if __name__=='__main__':unittest.main()
