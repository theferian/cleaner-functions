import contextlib
from dataclasses import replace
import importlib
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cleaner_v07 import runtime as r
import RUN_GENERAL_DOCUMENT_V07 as launcher
from functions.board_to_log.contracts import LogRecord
from functions.engineering_control import three_lists as lists


def record(side,row,day,event=1,block=0,status=None):
    return LogRecord(project_id='AZD',source_run_id='test_v07',source_workbook='source.xlsx',
        source_sheet='230KV SS',document_index=1,doc_name='Document',doc_wbs='1',
        send_or_receive=side,doc_rev='A',event_index=event,block_index=block,source_row=row,
        date_source=f'D{row}' if row else None,letter_date=day,doc_status=status)

class Tests(unittest.TestCase):
    def setUp(self):
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.patch=patch.object(r,'ROOT',self.root);self.patch.start();self.addCleanup(self.patch.stop)
        self.original=lists.build_three_engineering_lists;self.key=lists._sequence_key
        import functions.engineering_control as exp
        self.export=exp.build_three_engineering_lists
        self.addCleanup(lambda:setattr(lists,'build_three_engineering_lists',self.original))
        self.addCleanup(lambda:setattr(lists,'_sequence_key',self.key))
        self.addCleanup(lambda:setattr(exp,'build_three_engineering_lists',self.export))
        r.install_ordering()
    def build(self,records):
        return lists.build_three_engineering_lists(records,status_date='1405/07/29')
    def test_response_after_repeated_submissions(self):
        result=self.build([record('send',10,'1405/07/01',1),record('send',14,'1405/07/05',2),record('receive',18,'1405/07/08',1,status='CM')])
        self.assertEqual(len(result.consultant_delay),0)
        self.assertEqual(len(result.company_delay),1)
        self.assertEqual(result.company_delay[0].last_action_date,'1405/07/08')
    def test_submission_after_response(self):
        result=self.build([record('send',10,'1405/07/01'),record('receive',14,'1405/07/05',status='CM'),record('send',18,'1405/07/08',2)])
        self.assertEqual(len(result.company_delay),0)
        self.assertEqual(len(result.consultant_delay),1)
    def test_later_revision_starts_at_top(self):
        result=self.build([record('send',30,'1405/07/01'),record('receive',34,'1405/07/05',status='CM'),record('send',10,'1405/07/08',block=1)])
        self.assertEqual(len(result.consultant_delay),1)
    def test_conflicting_date_requires_review(self):
        result=self.build([record('send',10,'1405/07/10'),record('receive',14,'1405/07/05',status='CM')])
        self.assertFalse(result.company_delay or result.consultant_delay)
        self.assertTrue(any(d['kind']=='CHRONOLOGY_DATE_POSITION_CONFLICT' for d in result.diagnostics))
    def test_overlapping_send_and_receive_lanes_are_not_a_conflict(self):
        result=self.build([
            record('send',93,'1404/09/18',1),record('receive',93,'1405/02/06',1,status='A.N'),
            record('send',95,'1404/11/26',2),record('receive',95,'1405/02/06',2,status='A.N'),
        ])
        self.assertFalse(any(d['kind']=='CHRONOLOGY_DATE_POSITION_CONFLICT' for d in result.diagnostics))
    def test_each_document_requires_one_wbs(self):
        rows=[record('send',10,'1405/07/01')]
        rows[0]=replace(rows[0],doc_wbs=None)
        result=lists.build_three_engineering_lists(rows,status_date='1405/07/29',document_inventory=[dict(source_sheet='230KV SS',document_index=1,doc_name='Document',doc_wbs=None)])
        self.assertFalse(result.not_sent or result.company_delay or result.consultant_delay)
        self.assertTrue(any(d['kind']=='DOCUMENT_WBS_REQUIRED' for d in result.diagnostics))
    def test_document_cannot_have_conflicting_wbs_values(self):
        rows=[record('send',10,'1405/07/01',1),record('send',14,'1405/07/02',2)]
        rows[1]=replace(rows[1],doc_wbs='2')
        result=lists.build_three_engineering_lists(rows,status_date='1405/07/29',document_inventory=[dict(source_sheet='230KV SS',document_index=1,doc_name='Document',doc_wbs='1')])
        self.assertFalse(result.not_sent or result.company_delay or result.consultant_delay)
        self.assertTrue(any(d['kind']=='DOCUMENT_WBS_CONFLICT' for d in result.diagnostics))
    def test_geometry_missing_not_false_not_sent(self):
        result=lists.build_three_engineering_lists([record('send',None,'1405/07/01')],status_date='1405/07/29',document_inventory=[dict(source_sheet='230KV SS',document_index=1)])
        self.assertFalse(result.not_sent or result.company_delay or result.consultant_delay)
        self.assertTrue(result.diagnostics)
    def test_merged_anchor_uses_start_row(self):
        x=replace(record('receive',None,'1405/07/08'),date_source='H11:H18')
        self.assertEqual(r.start_row(x),11)
    def test_same_row_receive_after_send(self):
        result=self.build([record('receive',10,'1405/07/01',status='CM'),record('send',10,'1405/07/01')])
        self.assertEqual(len(result.company_delay),1)
    def test_narrative_receive_below_latest_submission(self):
        result=self.build([record('send',10,'1405/07/01'),record('send',14,'1405/07/05',2),record('receive',18,'جلسه هماهنگی',status='CM')])
        self.assertFalse(result.consultant_delay)
        self.assertEqual(result.company_delay[0].calculation_status,'NEEDS_DATE')
    def test_duplicate_geometry_requires_review(self):
        result=self.build([record('send',10,'1405/07/01'),record('send',10,'1405/07/02',2)])
        self.assertFalse(result.consultant_delay)
        self.assertTrue(any(x['kind']=='CHRONOLOGY_POSITION_TIE' for x in result.diagnostics))
    def test_same_day_warning_removed_without_removing_rows(self):
        def upstream(*a,**k):
            result=self.original(*a,**k)
            result.diagnostics.append(dict(kind='SAME_DAY_DIRECTION_ORDER_UNVERIFIED',source_sheet='230KV SS',document_index=1))
            result.diagnostics.append(dict(kind='OTHER_DATA_ERROR'))
            return result
        lists.build_three_engineering_lists=upstream
        r.install_ordering()
        result=self.build([record('send',10,'1405/07/01'),record('receive',10,'1405/07/01',status='CM')])
        self.assertEqual(len(result.company_delay),1)
        self.assertFalse(any(d.get('kind')=='SAME_DAY_DIRECTION_ORDER_UNVERIFIED' for d in result.diagnostics))
        self.assertTrue(any(d.get('kind')=='OTHER_DATA_ERROR' for d in result.diagnostics))
    def test_report_date_required_and_valid(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit): launcher.parse(['--project','AZD','--new-run','--workbook','a.xlsx'])
            with self.assertRaises(SystemExit): launcher.parse(['--project','AZD','--new-run','--workbook','a.xlsx','--status-date','1405/07/31'])
        a=launcher.parse(['--project','AZD','--new-run','--workbook','a.xlsx','--status-date','1405/07/29'])
        self.assertEqual(a.status_date,'1405/07/29')
    def test_staging_preserves_retrieval(self):
        p=self.root/'source.xlsx';p.write_bytes(b'original')
        with patch.object(launcher,'ROOT',self.root):
            book=launcher.stage(SimpleNamespace(run_id=None,workbook=str(p),project='AZD',status_date='1405/07/29'))
        book.write_bytes(b'working')
        self.assertEqual(p.read_bytes(),b'original')
        self.assertEqual(r.load(book.parent/'source_lineage.json')['status_date'],'1405/07/29')
    def test_resume_preserves_workbook_and_date(self):
        d=self.root/'runs'/'azd_1';d.mkdir(parents=True)
        source=self.root/'s.xlsx';source.write_bytes(b's')
        r.save(d/'run_manifest.json',dict(profile_name='AZD',workbook={'path':str(source)}))
        r.save(d/'general_doc_auto_progress.json',dict(status_date='1405/07/29'))
        a=SimpleNamespace(run_id='azd_1',project='AZD',workbook=None,status_date='1405/07/29')
        with patch.object(launcher,'ROOT',self.root):
            # Windows paths are case-insensitive, while pathlib.Path equality
            # compares their spelling. Compare the actual filesystem identity.
            self.assertTrue(os.path.samefile(launcher.stage(a),source))
            a.status_date='1405/07/30'
            with self.assertRaises(ValueError):launcher.stage(a)
    def test_excel_visibility_failure_does_not_abort_and_closes_only_owned(self):
        class Book:
            def __init__(self):self.closed=0
            def Close(self,**kwargs):self.closed+=1
        class App:
            def __init__(self):self.book=Book();self.quit=0;self.Workbooks=SimpleNamespace(Open=lambda *a,**k:self.book)
            @property
            def Visible(self): return False
            @Visible.setter
            def Visible(self,value):raise AttributeError('Visible cannot be set')
            def Quit(self):self.quit+=1
        app=App();unrelated=App()
        owner=r.ExcelOwner(factory=lambda:app);owner.open(self.root/'x.xlsx');owner.close();owner.close()
        self.assertEqual((app.book.closed,app.quit),(1,1))
        self.assertEqual((unrelated.book.closed,unrelated.quit),(0,0))
    def test_busy_excel_retry(self):
        class Busy(Exception): hresult=-2147418111
        count=[0]
        def work():
            count[0]+=1
            if count[0]<3:raise Busy('busy')
            return 3
        with patch.object(r.time,'sleep'):self.assertEqual(r.retry(work),3)
        self.assertEqual(count[0],3)
    def test_other_excel_error_not_retried(self):
        count=[0]
        def work(): count[0]+=1;raise ValueError('bad target')
        with self.assertRaises(ValueError):r.retry(work)
        self.assertEqual(count[0],1)
    def test_materialization_cached_and_tamper_detected(self):
        source=self.root/'source.xlsx';source.write_bytes(b'original')
        run=SimpleNamespace(run_dir=self.root,workbook={'path':str(source)},state=lambda:{})
        with patch('functions.cleaner.service.finalize_run',return_value=run):
            p=r.materialize(self.root);self.assertEqual(p.read_bytes(),b'original')
            p.write_bytes(b'changed')
            p2=r.materialize(self.root);self.assertEqual(p2.read_bytes(),b'original')
        self.assertEqual(source.read_bytes(),b'original')
        self.assertEqual(r.load(self.root/'working_copy_execution.json')['status'],'VERIFIED')
    def test_physical_fix_saved_reopened_and_audit_uses_cleaned_bytes(self):
        import json
        source=self.root/'source.xlsx';source.write_text(json.dumps({'value':'old'}))
        state={'value_overrides':{'S!A1':dict(sheet='S',target='A1',value='new',expected_old_value='old')}}
        run=SimpleNamespace(run_dir=self.root,workbook={'path':str(source)},state=lambda:state)
        owners=[]
        class Book:
            def __init__(self,path):
                self.path=Path(path); self.Value2=json.loads(self.path.read_text())['value'];self.Address='$A$1';self.MergeCells=False
                self.Cells=SimpleNamespace(Count=1,Item=lambda index:self);self.closed=False
            def Worksheets(self,sheet):return self
            def Range(self,target):return self
            def Save(self):self.path.write_text(json.dumps({'value':self.Value2}))
            def Close(self,**kwargs):self.closed=True
        class Owner:
            def __init__(self):self.app=self;self.books=[];self.closed=False;owners.append(self)
            def open(self,path,readonly=False):
                b=Book(path);self.books.append(b);return b
            def close(self):
                for b in self.books:b.Close()
                self.closed=True
        from functions.cleaner import executor
        old=executor.create_cleaned_copy_com
        self.addCleanup(lambda:setattr(executor,'create_cleaned_copy_com',old))
        with patch('functions.cleaner.service.finalize_run',return_value=run),patch.object(r,'ExcelOwner',Owner):
            cleaned=r.materialize(self.root)
            self.assertEqual(json.loads(cleaned.read_text())['value'],'new')
            self.assertEqual(json.loads(source.read_text())['value'],'old')
            self.assertTrue(all(o.closed for o in owners))
            r.install_executor()
            app,book,out,execution=executor.create_cleaned_copy_com(run,output_path=self.root/'audit.xlsx')
            self.assertEqual(book.Value2,'new')
            self.assertEqual(execution['working_copy'],str(cleaned))
            r.cleanup()
        self.assertEqual(r.load(self.root/'working_copy_execution.json')['execution']['applied_count'],1)

    def test_known_date_rule_uses_actual_reviewer_and_persists(self):
        # Use the installed review implementation, with isolated project registry.
        import shutil
        source=Path(importlib.import_module('dev.review_findings').__file__)
        (self.root/'dev').mkdir();shutil.copyfile(source,self.root/'dev'/'review_findings.py')
        raw='عطف به صورتجلسه مورخ 04/06/03'
        def queue(value):
            from cleaner_core.field_schema import normalize_embedded_jalali_text
            normalized=normalize_embedded_jalali_text(value)[0]
            return dict(profile={'profile_name':'AZD'},summary={},items=[dict(review_id='test1',review_state='PENDING',source={'test_id':'FIELD_VALIDATION','status':'FAIL'},
                location={'sheet':'230KV SS','target':'H11:H12'},observed=value,evidence={'audit_kind':'EXPLANATION_DATE','field_role':'explanation'},
                machine_suggestion={'suggested_fix':{'action':'SET_VALUE','parameters':{'sheet':'230KV SS','target':'H11:H12','value':normalized}}},reusable_resolution=None,current_policy={})])
        path=self.root/'q.json';out=self.root/'d.json'
        r.save(path,queue(raw));r.auto_known(path,out)
        d=r.load(out)['decisions'][0]['decision']
        self.assertEqual(d['parameters']['value'],'عطف به صورتجلسه مورخ 1404/06/03')
        self.assertEqual(d['parameters']['expected_old_value'],raw)
        self.assertTrue((self.root/'project_solutions'/'AZD.solutions.json').exists())
        r.save(path,queue('مورخ 04/13/03'));r.auto_known(path,out)
        self.assertEqual(r.load(path)['summary']['pending_review'],1)

if __name__=='__main__':unittest.main()
