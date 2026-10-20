"""Focused checks for CARDS phase-one report. Run: py -m unittest -q test_card_morphology_gallery_v01.py"""
import json
import tempfile
import unittest
from pathlib import Path
import CARD_MORPHOLOGY_GALLERY_V01 as m


def rec(i,rev,side,date,ref,status=None,cell='D3'):
    return {'source_sheet':'SS','document_index':i,'doc_rev':rev,'doc_name':f'Document {i}',
            'doc_wbs':'1.2','send_or_receive':side,'letter_date':date,'letter_reference':ref,
            'doc_status':status,'source_row':int(cell[1:]),'source_col':4,
            'date_source':cell,'reference_source':cell[0]+str(int(cell[1:])+1),
            'status_source':'F3:F4' if status else None}


class MorphTests(unittest.TestCase):
    def test_shapes(self):
        self.assertEqual(m.case_morphology(1,1),'STANDARD_PAIR')
        self.assertEqual(m.case_morphology(3,1),'MULTIPLE_SEND_ONE_RECEIVE')
        self.assertEqual(m.case_morphology(1,3),'ONE_SEND_MULTIPLE_RECEIVE')
        self.assertEqual(m.case_morphology(1,0),'SEND_ONLY')

    def test_variation_does_not_imply_error(self):
        self.assertFalse(m.needs_investigation({'MERGED_STATUS'},'STANDARD_PAIR',{}))
        self.assertFalse(m.needs_investigation({'REPEATED_INTERACTIONS'},'MULTIPLE_SEND_ONE_RECEIVE',{}))
        self.assertTrue(m.needs_investigation({'SOURCE_SLOT_ISSUE'},'STANDARD_PAIR',{}))
        self.assertFalse(m.needs_investigation(set(),'NO_DATED_EVENTS',{'slots':[]}))
        self.assertTrue(m.needs_investigation(set(),'NO_DATED_EVENTS',{'slots':[{'value':'text'}]}))

    def test_narrative_and_meeting(self):
        self.assertFalse(m.is_narrative_reference('1404/ES/S/3844'))
        self.assertFalse(m.is_narrative_reference('صورتجلسه'))
        self.assertTrue(m.is_narrative_reference('به علت تأمین توسط کارفرما بلاموضوع است.'))

    def test_missing_board_does_not_fake_empty_documents(self):
        with tempfile.TemporaryDirectory() as d:
            directory=Path(d)
            (directory/'card_maps.json').write_text('{"sheets": {"SS": {"cards": [{"record_index": 1}]}}}',encoding='utf-8')
            rows,cases,state=m.build_records('AZD','run',directory)
            self.assertEqual(rows,[])
            self.assertIn('MISSING_ARTIFACTS',state['status'])

    def test_fixture_end_to_end_and_three_orders(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            run=root/'runs'/m.RUN_IDS['AZD'];run.mkdir(parents=True)
            records=[rec(1,'A','receive','1404/01/03','R1','A.N','E3'),
                     rec(1,'A','send','1404/01/02','S1',None,'D3'),
                     rec(2,'B','send','1404/03/01','S2',None,'G8'),
                     rec(2,'B','send','1404/03/02','S3',None,'G10'),
                     rec(2,'B','receive','1404/03/03','R3','A','H8')]
            cards=[{'record_index':i,'sheet':'SS','start_row':3 if i==1 else 8,
                    'end_row':4 if i==1 else 12,'data_range':f'D{3 if i==1 else 8}:L{4 if i==1 else 12}',
                    'data_start_col':4,'data_end_col':12,'slots':[]} for i in (1,2)]
            (run/'card_maps.json').write_text(json.dumps({'sheets':{'SS':{'cards':cards}}}))
            (run/'board_to_log.json').write_text(json.dumps({'records':records,'issues':[]}))
            (run/'slot_schema.json').write_text(json.dumps({'sheets':{'SS':{'block_width':3}}}))
            out=root/'output'
            summary=m.execute(root,out,['AZD'],2)
            self.assertEqual(summary['cards'],2)
            self.assertEqual(summary['candidates'],0) # repeated sends: not an error
            text=(out/'card_exception_gallery.html').read_text(encoding='utf-8')
            self.assertIn('MULTIPLE_SEND_ONE_RECEIVE',text)
            self.assertIn('G8',text)
            with (out/'event_orderings.csv').open(encoding='utf-8-sig') as fh:
                event_rows=__import__('csv').DictReader(fh)
                events=list(event_rows)
            self.assertEqual(len(events),5)
            # Original extraction list starts with RECEIVE, but date order differs.
            self.assertEqual(events[0]['date_order_rank'],'2')
            self.assertEqual(events[1]['date_order_rank'],'1')
            self.assertEqual(events[0]['revision'],'A')


if __name__=='__main__':unittest.main()
