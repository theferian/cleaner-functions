import json
from pathlib import Path
import tempfile
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'/'adaptive_document_reader'))
from card_workbench_core_v04 import (scoped, normalise_rects, signature, save_draft, load_draft, export_machine_results)
from verification_ledger_v03 import build_ledger
from ocr_auto_core_v02 import append_journal
from card_source_workbench_v04 import success_keys

class TestWorkbench(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.pdf=self.root/'sample.pdf';self.pdf.write_bytes(b'fake source marker')
        self.drafts=self.root/'drafts'
    def test_scoped_direction(self):
        q=[{'event': {'direction':'send'}},{'event':{'direction':'receive'}}]
        self.assertEqual(len(scoped(q,'Outgoing (our letters)')),1)
        self.assertEqual(scoped(q,'Incoming (consultant)')[0]['event']['direction'],'receive')
        self.assertEqual(len(scoped(q,'Both directions')),2)
    def test_draft_restore_after_reopen(self):
        boxes={'letter_date':[10,12,40,22], 'letter_reference':[5,25,65,38]}
        save_draft(self.drafts,self.pdf,'OFFICIAL_OUTGOING',boxes,100,100)
        data=load_draft(self.drafts,self.pdf,'OFFICIAL_OUTGOING',200,200)
        self.assertEqual([round(v) for v in data['boxes']['letter_date']],[20,24,80,44])
    def test_different_families_are_separate(self):
        save_draft(self.drafts,self.pdf,'A',{'letter_date':[1,2,3,4]},100,100)
        self.assertIsNone(load_draft(self.drafts,self.pdf,'B',100,100))
    def test_changed_pdf_invalidates_drawing(self):
        save_draft(self.drafts,self.pdf,'A',{'letter_date':[1,2,3,4]},100,100)
        self.pdf.write_bytes(b'new source text longer')
        self.assertIsNone(load_draft(self.drafts,self.pdf,'A',100,100))
    def test_approval_removed_when_boxes_shift(self):
        boxes={'letter_date':[1,2,3,4]}
        _,d=save_draft(self.drafts,self.pdf,'A',boxes,100,100)
        _,d=save_draft(self.drafts,self.pdf,'A',boxes,100,100,prior_approval=d['box_signature'])
        self.assertTrue(d['extraction_approved'])
        boxes['letter_date']=[2,2,3,4]
        _,d=save_draft(self.drafts,self.pdf,'A',boxes,100,100,prior_approval=d['approved_box_signature'])
        self.assertFalse(d['extraction_approved'])
    def test_invalid_rect_rejected(self):
        with self.assertRaises(ValueError):normalise_rects({'date':[4,3,2,1]},100,100)
    def test_missing_engine_result_is_retryable(self):
        journal=self.root/'ocr.jsonl'
        append_journal(journal,{'event_key':'A', 'processing_status':'COMPLETED',
            'evidence':{'complete':True,'fields':[{'ocr_status':'OCR_UNAVAILABLE'},{'ocr_status':'OCR_UNAVAILABLE'}]}})
        append_journal(journal,{'event_key':'B', 'processing_status':'COMPLETED',
            'evidence':{'complete':True,'fields':[{'ocr_status':'OCR_OK'},{'ocr_status':'OCR_OK'}]}})
        self.assertEqual(success_keys(journal),{'B'})
    def test_export_json_csv(self):
        event={'direction':'send','date':'1404/06/16','reference':'1404/ES/S/2605'}
        queue=[{'event_key':'k1','locator':'SINGLE_CANDIDATE','path':self.pdf,'card':{'sheet':'LINE','index':5,'name':'Drawing','wbs':'1.2'},'event':event}]
        journal=self.root/'ocr.jsonl'
        append_journal(journal, {'event_key':'k1','at':'x','processing_status':'COMPLETED','evidence':{
          'pdf_sha256':'abc','complete':True,'fields':[{'field':'letter_date','native_text':'1404/06/16','ocr_text':'','ocr_status':'OCR_UNAVAILABLE','bbox_pdf':[1,2,3,4]}]}})
        rows=build_ledger(queue,journal,self.root/'reviews.jsonl')
        j,c,s=export_machine_results(rows,self.root/'export',run_dir=self.root,scope='send')
        self.assertEqual(len(j.read_text(encoding='utf-8').splitlines()),1)
        data=json.loads(j.read_text(encoding='utf-8').splitlines()[0])
        self.assertEqual(data['status'],'NEEDS_REVIEW')
        self.assertFalse(data['machine_output_is_approved'])
        self.assertIn('letter_reference',data['fields'])
        self.assertIn('event_key',c.read_text(encoding='utf-8-sig'))
        self.assertTrue(json.loads(s.read_text())['read_only'])

if __name__=='__main__': unittest.main()
