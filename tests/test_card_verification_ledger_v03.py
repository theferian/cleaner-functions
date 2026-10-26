import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'/'adaptive_document_reader'))
from verification_ledger_v03 import (_valid_date, _reference, reconstruct_field,
    compare_manual, evidence_hash, build_ledger, make_review, overview, export_csv)
from ocr_auto_core_v02 import append_journal


def fixture_event(date='1404/06/16', ref='1404/ES/S/2605', reader_date='۱۴۰۴/۰۶/۱۶',
                  reader_ref='۱۴۰۴/ES/S/۲۶۰۵', sourcehash='abcdef'*10+'abcd', bbox=None):
    source={'direction':'send','date':date,'reference':ref}
    fields=[dict(field='letter_date',native_text=reader_date,ocr_text='',
                 bbox_pdf=bbox or [2,3,20,13],page=1,ocr_status='OCR_OK',result='VALUE_MATCH_CANDIDATE'),
            dict(field='letter_reference',native_text=reader_ref,ocr_text='',
                 bbox_pdf=[2,14,35,24],page=1,ocr_status='OCR_OK',result='VALUE_MATCH_CANDIDATE')]
    return {'schema':'cleaner.card_field_autorun/0.2','event_key':'k1',
            'source_pdf':'x.pdf','source_event':source,'processing_status':'COMPLETED',
            'evidence':{'complete':True,'pdf_sha256':sourcehash,'fields':fields}}


def fixture_queue(ref='1404/ES/S/2605'):
    return [dict(event_key='k1',locator='SINGLE_CANDIDATE',path=Path('x.pdf'),
                 card=dict(sheet='LINE',index='3',name='DOCUMENT',wbs='1.3'),
                 event=dict(direction='send',date='1404/06/16',reference=ref))]


class TestNormalization(unittest.TestCase):
    def test_persian_date(self):
        self.assertEqual(_valid_date('۱۴۰۴/۰۶/۱۶'),'1404/06/16')
        self.assertEqual(_valid_date('1404:6:16'),'1404/06/16')
        self.assertEqual(_valid_date('۱۴۰۴۰۶۱۶'),'1404/06/16')
    def test_reject_invalid_year_and_month(self):
        self.assertIsNone(_valid_date('۴:۴/۶/۱۶'))
        self.assertIsNone(_valid_date('1404/19/16'))
    def test_full_persian_reference(self):
        self.assertEqual(_reference('۱۴۰۴/ES/S/۲۶۰۵'),'1404ESS2605')
    def test_conservative_short_reference(self):
        r=reconstruct_field('letter_reference','1404-2605','', '1404/ES/S/2605')
        self.assertEqual(r['machine_outcome'],'SHORT_REFERENCE_COMPATIBLE_UNCONFIRMED')
    def test_not_reconstruct_broken_from_expected(self):
        r=reconstruct_field('letter_date','۴:۴/۶/۱۶','', '1404/06/16')
        self.assertEqual(r['machine_outcome'],'UNREADABLE_NEEDS_REVIEW')
        self.assertFalse(r['verified'])
        self.assertEqual(r['expected_guided_hint']['basis'],'EXPECTED_GUIDED_NOT_EVIDENCE')
    def test_disagreement_not_averaged(self):
        r=reconstruct_field('letter_date','1404/06/16','1404/06/17','1404/06/16')
        self.assertEqual(r['machine_outcome'],'READER_CONFLICT')
    def test_normalized_candidate_no_auto_verify(self):
        r=reconstruct_field('letter_date','۱۴۰۴/۰۶/۱۶','', '1404/06/16')
        self.assertEqual(r['machine_outcome'],'EXACT_CANDIDATE_MATCH')
        self.assertFalse(r['verified'])
    def test_manual_correct_and_error(self):
        self.assertEqual(compare_manual('letter_date','۱۴۰۴/۶/۱۶','1404/06/16'),'HUMAN_MATCH')
        self.assertEqual(compare_manual('letter_date','1404/06/17','1404/06/16'),'HUMAN_MISMATCH')
        self.assertEqual(compare_manual('letter_reference','1404-2605','1404/ES/S/2605'),'PARTIAL_REFERENCE_REVIEW')

class TestJournal(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.ocr=self.root/'ocr.jsonl';self.review=self.root/'reviews.jsonl'
        append_journal(self.ocr,fixture_event())
    def rows(self):return build_ledger(fixture_queue(),self.ocr,self.review)
    def test_machine_candidate_not_verified(self):
        row=self.rows()[0]
        self.assertEqual(row['status'],'MACHINE_MATCH_UNVERIFIED')
        self.assertIsNotNone(row['evidence_hash'])
        self.assertEqual(overview([row])['HUMAN_VERIFIED'],0)
        self.assertEqual(overview([row])['CARDS_TOTAL'],1)
        self.assertEqual(overview([row])['CARDS_FULLY_VERIFIED'],0)
    def test_review_both_matches(self):
        row=self.rows()[0]
        append_journal(self.review,make_review(row,manual_date='1404/06/16',manual_reference='۱۴۰۴/ES/S/۲۶۰۵'))
        self.assertEqual(self.rows()[0]['status'],'VERIFIED_CORRECT')
        self.assertEqual(overview(self.rows())['HUMAN_VERIFIED'],1)
        self.assertEqual(overview(self.rows())['CARDS_FULLY_VERIFIED'],1)
    def test_review_error_is_not_correction(self):
        row=self.rows()[0]
        rec=make_review(row,manual_date='1404/06/17',manual_reference='1404/ES/S/2605')
        self.assertEqual(rec['field_decisions']['letter_date'],'HUMAN_MISMATCH')
        self.assertFalse(rec['writes_to_general_doc'])
        append_journal(self.review,rec)
        self.assertEqual(self.rows()[0]['status'],'VERIFIED_ERROR')
    def test_partial_review(self):
        row=self.rows()[0]
        append_journal(self.review,make_review(row,manual_date='1404/06/16'))
        self.assertEqual(self.rows()[0]['status'],'PARTIALLY_REVIEWED')
    def test_incremental_reviews_preserve_first_field(self):
        row=self.rows()[0]
        append_journal(self.review,make_review(row,manual_date='1404/06/16'))
        append_journal(self.review,make_review(row,manual_reference='1404/ES/S/2605'))
        result=self.rows()[0]
        self.assertEqual(result['status'],'VERIFIED_CORRECT')
        self.assertEqual(len(result['review']['manual']),2)
    def test_short_reference_cannot_verify(self):
        row=self.rows()[0]
        append_journal(self.review,make_review(row,manual_date='1404/06/16',manual_reference='1404-2605'))
        self.assertEqual(self.rows()[0]['status'],'PARTIALLY_REVIEWED')
    def test_changed_pdf_invalidates_approval(self):
        row=self.rows()[0]
        append_journal(self.review,make_review(row,manual_date='1404/06/16',manual_reference='1404/ES/S/2605'))
        append_journal(self.ocr,fixture_event(sourcehash='beef'*16))
        self.assertEqual(self.rows()[0]['status'],'STALE_REVIEW')
    def test_changed_box_invalidates_approval(self):
        row=self.rows()[0]
        append_journal(self.review,make_review(row,manual_date='1404/06/16',manual_reference='1404/ES/S/2605'))
        append_journal(self.ocr,fixture_event(bbox=[3,3,20,13]))
        self.assertEqual(self.rows()[0]['status'],'STALE_REVIEW')
    def test_changed_expected_date_not_silently_approved(self):
        row=self.rows()[0]
        append_journal(self.review,make_review(row,manual_date='1404/06/16',manual_reference='1404/ES/S/2605'))
        event=fixture_event(date='1404/06/17');append_journal(self.ocr,event)
        self.assertEqual(self.rows()[0]['status'],'STALE_REVIEW')
    def test_ocr_failure_not_verified(self):
        append_journal(self.ocr,{'event_key':'k1','processing_status':'NEEDS_REVIEW',
                                 'evidence':{'complete':False,'reason':'OCR_TIMEOUT'}})
        self.assertEqual(self.rows()[0]['status'],'NEEDS_REVIEW')
        with self.assertRaises(ValueError):make_review(self.rows()[0],manual_date='1404/06/16')
    def test_missing_source_and_not_checked(self):
        rows=build_ledger([dict(fixture_queue()[0],event_key='z',locator='NOT_FOUND')],self.ocr,self.review)
        self.assertEqual(rows[0]['status'],'SOURCE_MISSING')
    def test_csv_export(self):
        p=self.root/'ledger.csv';export_csv(self.rows(),p)
        with p.open(encoding='utf-8-sig',newline='') as f:records=list(csv.DictReader(f))
        self.assertEqual(records[0]['date_status'],'EXACT_CANDIDATE_MATCH')
        self.assertEqual(records[0]['overall_status'],'MACHINE_MATCH_UNVERIFIED')
    def test_bad_jsonl_ignored(self):
        with self.ocr.open('a',encoding='utf8') as f:f.write('not json\n')
        self.assertEqual(self.rows()[0]['status'],'MACHINE_MATCH_UNVERIFIED')

if __name__=='__main__':unittest.main()
