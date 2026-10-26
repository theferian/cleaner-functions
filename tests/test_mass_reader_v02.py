"""Stop/resume and non-jumping dashboard regressions for V02."""
from pathlib import Path
import tempfile
import time
import unittest
from mass_reader_v01.core import Reader,Store

class StopRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.root=self.base/'source';self.root.mkdir()
        for n in range(100):
            (self.root/f'{n:04d}.txt').write_text('sample',encoding='utf8')
        self.db=self.base/'state.sqlite3'
        self.store=Store(self.db)
        self.reader=Reader(self.store)
        self.wid=self.store.create_workspace('Example')
        self.store.save_scope(self.wid,dict(root=str(self.root),label='source',include=['*'],exclude=[],override=[],recursive=True))
        old=self.reader._observe_file
        def slow(*args,**kwargs):
            time.sleep(.008)
            return old(*args,**kwargs)
        self.reader._observe_file=slow

    def tearDown(self):
        self.tmp.cleanup()

    def await_status(self,rid,allowed,timeout=6):
        until=time.monotonic()+timeout
        while time.monotonic()<until:
            x=self.store.run(rid)['run']['status']
            if x in allowed:return x
            time.sleep(.006)
        self.fail('Timed out: '+str(self.store.run(rid)['run']))

    def start(self):
        r=self.store.create_run(self.wid,0)
        self.reader.start(r,0)
        end=time.monotonic()+6
        while time.monotonic()<end:
            if self.store.run(r)['run']['processed_files']>=3:return r
            time.sleep(.005)
        self.fail('did not process test files')

    def assert_no_processing_folders(self,rid):
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM dirs WHERE run_id=? AND status='PROCESSING'",(rid,)).fetchone()[0],0)

    def test_pause_stops_file_processing_and_resumes_without_duplicates(self):
        rid=self.start()
        self.store.request(rid,'pause')
        self.assertIn(self.store.run(rid)['run']['status'],('PAUSING','PAUSED'))
        self.assertEqual(self.await_status(rid,{'PAUSED'}),'PAUSED')
        stopped=self.store.run(rid)['run']['processed_files']
        self.assertLess(stopped,100)
        time.sleep(.08)
        self.assertEqual(self.store.run(rid)['run']['processed_files'],stopped)
        self.assert_no_processing_folders(rid)
        self.reader.start(rid,0)
        self.assertEqual(self.await_status(rid,{'COMPLETED'}),'COMPLETED')
        self.assertEqual(self.store.run(rid)['run']['processed_files'],100)

    def test_cancel_stops_without_discarding_records(self):
        rid=self.start()
        self.store.request(rid,'cancel')
        self.assertIn(self.store.run(rid)['run']['status'],('CANCELLING','CANCELLED'))
        self.assertIsNotNone(self.store.active(self.wid))
        self.assertEqual(self.await_status(rid,{'CANCELLED'}),'CANCELLED')
        stopped=self.store.run(rid)['run']['processed_files']
        self.assertLess(stopped,100)
        time.sleep(.07)
        self.assertEqual(self.store.run(rid)['run']['processed_files'],stopped)
        self.assert_no_processing_folders(rid)
        self.assertIsNone(self.store.active(self.wid))
        self.assertEqual(len(self.store.list_files(self.wid)['files']),stopped)

    def test_restart_recovers_stop_in_progress(self):
        rid=self.store.create_run(self.wid)
        with self.store.connect() as db:
            db.execute("UPDATE runs SET status='PAUSING',pause_requested=1 WHERE id=?",(rid,))
            db.execute("UPDATE dirs SET status='PROCESSING' WHERE run_id=?",(rid,))
        recovered=Store(self.db)
        self.assertEqual(recovered.run(rid)['run']['status'],'PAUSED')
        self.assertEqual(recovered.run(rid)['areas'][0]['folders_pending'],1)
        with recovered.connect() as db:
            db.execute("UPDATE runs SET status='CANCELLING',cancel_requested=1 WHERE id=?",(rid,))
        recovered=Store(self.db)
        self.assertEqual(recovered.run(rid)['run']['status'],'CANCELLED')

    def test_dashboard_poll_is_non_destructive(self):
        app=(Path(__file__).parents[1]/'mass_reader_v01/static/app.js').read_text()
        self.assertIn('loadDetail(true)',app)
        self.assertIn('host.dataset.renderedRun',app)
        self.assertNotIn("$('runDetail').innerHTML=''",app)
        self.assertIn("r.status==='PAUSED'?'PAUSED'",app)

if __name__=='__main__':unittest.main()
