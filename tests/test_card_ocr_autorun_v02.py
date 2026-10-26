import json, os, sys, tempfile, threading, unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]/'tools'/'adaptive_document_reader'
sys.path.insert(0,str(SRC))
from ocr_auto_core_v02 import (
    append_journal, load_completed, event_key, readiness, make_queue,
    extract_regional_fields,
)

class TestCore(unittest.TestCase):
    def test_event_key_stable(self):
        c={'sheet':'LINE','index':3};e={'direction':'send','reference':'1404/ES/S/3003','date':'1404/07/19'}
        self.assertEqual(event_key(c,e,Path('foo.pdf')), event_key(c,e,Path('foo.pdf')))
    def test_persistent_resume(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'journal.jsonl'
            append_journal(p,{'event_key':'a','processing_status':'COMPLETED'})
            append_journal(p,{'event_key':'b','processing_status':'NEEDS_REVIEW'})
            append_journal(p,{'event_key':'c','processing_status':'LOCATOR_REVIEW'})
            self.assertEqual(load_completed(p), {'a'})
    def test_missing_ocr_proposals_pause(self):
        self.assertFalse(readiness({}, {'operational':True})[0])
    def test_no_unreviewed_family_transfer(self):
        b={'letter_date':[1], 'letter_reference':[2]}
        self.assertFalse(readiness(b, {'operational':False})[0])
    def test_alignment_quality_gate(self):
        b={'letter_date':[1], 'letter_reference':[2]}
        self.assertFalse(readiness(b, {'operational':True,'alignment':'normalized-page fallback'})[0])
        self.assertTrue(readiness(b, {'operational':True,'alignment':'normalized-page fallback'},require_alignment=False)[0])
        self.assertTrue(readiness(b, {'operational':True,'alignment':'ORB + homography','inliers':12},min_inliers=10)[0])
        self.assertFalse(readiness(b, {'operational':True,'alignment':'ORB + homography','inliers':9},min_inliers=10)[0])
    def test_queue_skips_missing_and_ambiguous(self):
        cards=[{'sheet':'LINE','index':'3','name':'DOC','events':[{'direction':'send','reference':'1404/ES/S/3003','date':'1404/07/19'}]}]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'send';path.mkdir();(path/'1404-3003.pdf').write_bytes(b'pdf')
            q=make_queue(cards,{'send':[path/'1404-3003.pdf']})
            self.assertEqual(len(q),1)
            self.assertEqual(q[0]['locator'],'SINGLE_CANDIDATE')
            self.assertTrue(q[0]['event_key'])
    def test_stop_prior_to_open(self):
        from reportlab.pdfgen import canvas
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.pdf';c=canvas.Canvas(str(p));c.drawString(50,700,'1404/07/19');c.showPage();c.save()
            stop=threading.Event();stop.set()
            v=extract_regional_fields(p,{}, {}, stop=stop)
            self.assertFalse(v['complete']);self.assertEqual(v['reason'],'STOPPED')
    def test_ocr_native_and_crop(self):
        from reportlab.pdfgen import canvas
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.pdf'
            c=canvas.Canvas(str(p),pagesize=(595,842))
            c.setFont('Helvetica',16)
            c.drawString(80,760,'1404/07/19');c.drawString(80,710,'1404/ES/S/3003');c.save()
            # get_text / crop use top-based coordinates
            box={'letter_date':[70,62,240,96], 'letter_reference':[70,113,305,146]}
            v=extract_regional_fields(p,box,{'letter_date':'1404/07/19','letter_reference':'1404/ES/S/3003'},
                tesseract='tesseract',langs='eng',psm=6,dpi=300)
            self.assertTrue(v['complete'])
            self.assertEqual(len(v['fields']),2)
            self.assertTrue(v['pdf_sha256'])
            self.assertIn(v['fields'][0]['result'],('VALUE_MATCH_CANDIDATE','READER_DISAGREEMENT'))
            self.assertEqual(v['fields'][1]['native_candidates'],['1404ESS3003'])
            self.assertFalse(v['fields'][0]['source_confirmed'])

if __name__=='__main__':unittest.main()
