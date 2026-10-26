import json,sys, tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"/"adaptive_document_reader"))
from card_teaching_core import load_card_queue, locate_candidates, pdf_index, compare_field, canonical_date

class TestCardTeaching(unittest.TestCase):
 def test_fa_date(self):self.assertEqual(canonical_date('۱۴۰۴/۷/۱۹'),'1404/07/19')
 def test_one_card_two_events(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'board_to_log.json';p.write_text(json.dumps({'records':[
    {'source_sheet':'230KV SS','document_index':7,'doc_name':'PROT','letter_reference':'1404/ES/S/3003','send_or_receive':'send','letter_date':'1404/07/19'},
    {'source_sheet':'230KV SS','document_index':7,'doc_name':'PROT','letter_reference':'5104-905','send_or_receive':'receive','letter_date':'1404/08/10'},
   ]}),encoding='utf-8')
   cards=load_card_queue(p);self.assertEqual(len(cards),1);self.assertEqual(len(cards[0]['events']),2)
 def test_find_source_filename_without_claiming_verification(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'send';p.mkdir();(p/'1404-3003.pdf').write_bytes(b'%PDF')
   outcome=locate_candidates({'direction':'send','reference':'1404/ES/S/3003'},pdf_index(Path(d)))
   self.assertEqual(outcome['status'],'SINGLE_CANDIDATE');self.assertEqual(len(outcome['paths']),1)
 def test_missing(self):self.assertEqual(locate_candidates({'direction':'send','reference':'1404/ES/S/3003'},{})['status'],'NOT_FOUND')
 def test_expected_date_match_provisional_only(self):
  x=compare_field('letter_date','تاریخ ۱۴۰۴/۷/۱۹','1404/07/19','1404/07/19')
  self.assertEqual(x['result'],'VALUE_MATCH_CANDIDATE');self.assertFalse(x['source_confirmed'])
 def test_readers_disagree(self):
  self.assertEqual(compare_field('letter_date','1404/07/19','1404/07/02','1404/07/19')['result'],'READER_DISAGREEMENT')
 def test_mismatch(self):self.assertEqual(compare_field('letter_date','1404/07/02','','1404/07/19')['result'],'VALUE_MISMATCH')
 def test_reference(self):self.assertEqual(compare_field('letter_reference','1404/ES/S/3003','','1404/ES/S/3003')['result'],'VALUE_MATCH_CANDIDATE')
 def test_consultant_reference(self):self.assertEqual(compare_field('letter_reference','8104-244','','8104-244')['result'],'VALUE_MATCH_CANDIDATE')
 def test_date_not_a_ref(self):
  from card_teaching_core import references_in_text
  self.assertEqual(references_in_text('Date 1404-07-19'),[])
if __name__=='__main__':unittest.main()
