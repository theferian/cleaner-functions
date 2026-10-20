import csv
import tempfile
import unittest
from pathlib import Path

import CHRONOLOGY_TEST_SUITE_V01 as cs


def evt(rev='Z', direction='send', date='1400/10/27', ref='1400/ES/S/2739', pos=1,
        date_cell='D3', status='', project='YSK'):
    return dict(project=project,run_id='t',sheet='Yasookand',document_index='1',document='LIST OF DOCUMENTS',
        wbs='1.5.1',revision=rev,direction=direction,letter_date=date,letter_reference=ref,
        doc_status=status,date_source=date_cell,reference_source='D4',status_source='',
        source_cell_order_rank=str(pos),date_order_rank='',original_log_sequence=str(pos))


def card(rev='Z',s=1,r=1):
    return dict(project='YSK',sheet='Yasookand',document_index='1',document='LIST OF DOCUMENTS',
                wbs='1.5.1',revision=rev,send_count=str(s),receive_count=str(r))


def onlytest(rows,tid):return [r for r in rows if r['test_id']==tid]

class ChronologySuiteTests(unittest.TestCase):
    def test_jalali_real_leap_cycle(self):
        for y in (1395,1399,1403,1408):
            self.assertEqual(cs.jalali_date(f'{y}/12/30')[1],'VALID')
        for y in (1400,1404):
            self.assertEqual(cs.jalali_date(f'{y}/12/30')[1],'INVALID_DAY')
        self.assertEqual(cs.jalali_date('1405/04/31')[1],'VALID')
        self.assertEqual(cs.jalali_date('1405/07/31')[1],'INVALID_DAY')

    def test_out_of_source_order_but_different_revision_is_not_error(self):
        e=[evt(rev='A',date='1400/11/18',pos=1),evt(rev='Z',date='1400/10/01',pos=2)]
        issues,_,_=cs.evaluate(e,[card('A',1,0),card('Z',1,0)],'1405/07/22')
        self.assertFalse(onlytest(issues,'C04'))
        self.assertFalse(onlytest(issues,'C02'))

    def test_inversion_inside_revision_observation_only(self):
        e=[evt(date='1400/11/18',pos=1),evt(date='1400/10/01',pos=2)]
        issues,ordered,_=cs.evaluate(e,[card('Z',2,0)],'1405/07/22')
        self.assertEqual(len(onlytest(issues,'C04')),1)
        self.assertEqual(onlytest(issues,'C04')[0]['category'],'OBSERVE')
        self.assertEqual([x['chronology_rank_verified'] for x in ordered],[2,1])
        self.assertEqual([x['source_cell_order_rank'] for x in ordered],['1','2'])

    def test_single_response_before_send_is_investigation_not_proven_error(self):
        e=[evt(date='1400/10/27'),evt(direction='receive',date='1400/10/01',ref='1234',pos=2,date_cell='E3',status='A')]
        issues,_,_=cs.evaluate(e,[card()], '1405/07/22')
        self.assertEqual(onlytest(issues,'C02')[0]['category'],'INVESTIGATE')
        self.assertFalse([i for i in issues if i['test_id']=='C02' and i['category']=='ACTION'])

    def test_same_day_is_only_observation(self):
        e=[evt(),evt(direction='receive',ref='1234',pos=2,date_cell='E3',status='A')]
        issues,_,_=cs.evaluate(e,[card()], '1405/07/22')
        self.assertEqual(onlytest(issues,'C06')[0]['category'],'OBSERVE')

    def test_multiple_send_one_receive_is_not_error_by_itself(self):
        e=[evt(),evt(date='1400/10/28',ref='1400/ES/S/2740',pos=2,date_cell='G3'),
           evt(direction='receive',date='1400/10/29',ref='987',pos=3,date_cell='H3',status='A')]
        issues,_,_=cs.evaluate(e,[card(s=2,r=1)],'1405/07/22')
        self.assertFalse(onlytest(issues,'C05'))
        self.assertFalse(onlytest(issues,'C02'))

    def test_undated_evidence_for_team_investigation(self):
        e=[evt(date='')]
        issues,_,_=cs.evaluate(e,[card(s=1,r=0)],'1405/07/22')
        self.assertEqual(onlytest(issues,'C07')[0]['category'],'INVESTIGATE')

    def test_source_event_count_mismatch_is_action(self):
        issues,_,_=cs.evaluate([evt()],[card(s=2,r=0)],'1405/07/22')
        self.assertEqual(onlytest(issues,'C05')[0]['category'],'ACTION')

    def test_same_reference_different_positions_is_preserved(self):
        e=[evt(),evt(date='1400/10/28',pos=2,date_cell='G3')]
        issues,_,_=cs.evaluate(e,[card(s=2,r=0)],'1405/07/22')
        self.assertEqual(onlytest(issues,'C09')[0]['category'],'OBSERVE')

    def test_bad_year_vs_send_reference_review_not_autofix(self):
        issues,_,_=cs.evaluate([evt(date='1401/10/27')],[card(s=1,r=0)],'1405/07/22')
        self.assertEqual(onlytest(issues,'C08')[0]['category'],'INVESTIGATE')

    def test_status_cutoff(self):
        issues,_,_=cs.evaluate([evt(date='1405/07/23',ref='1405/ES/S/1')],[card(s=1,r=0)],'1405/07/22')
        self.assertEqual(onlytest(issues,'C11')[0]['category'],'OBSERVE')

    def test_csv_to_report_readonly(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source=root/'phase1';source.mkdir();out=root/'report'
            cs.write_csv(source/'event_orderings.csv',[evt()],cs.EVENT_FIELDS)
            cs.write_csv(source/'card_morphology_catalog.csv',[card(s=1,r=0)],
                ['project','sheet','document_index','document','wbs','revision','send_count','receive_count'])
            before=(source/'event_orderings.csv').read_bytes()
            results=cs.run(source,out,'1405/07/22')
            self.assertEqual(results['records'],1)
            self.assertTrue((out/'chronology_exception_gallery.html').exists())
            self.assertTrue((out/'chronology_team_investigations.csv').exists())
            self.assertEqual((source/'event_orderings.csv').read_bytes(),before)

if __name__=='__main__':unittest.main()
