import unittest
from pathlib import Path
import tempfile
from GENERAL_DOC_REAL_SCREENSHOT_GALLERY_V02 import read_csv, parsed_range, select_range, rule_text, matching_overrides, get_paths, build, parse_args, apply_approved_overlays

HERE=Path(__file__).resolve().parent

class GalleryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.groups=read_csv(HERE/'GENERAL_DOC_REVIEW_GROUPS.csv')
        cls.findings=read_csv(HERE/'GENERAL_DOC_FINDINGS_103.csv')
        cls.cards=read_csv(HERE/'GENERAL_DOC_CARD_CATALOG.csv')
    def test_58_groups(self):self.assertEqual(len(self.groups),58)
    def test_103_findings(self):self.assertEqual(len(self.findings),103)
    def test_eight_projects(self):self.assertEqual(len(set(x['project'] for x in self.groups)),8)
    def test_groups_link_findings(self):
        ids={r['group_id'] for r in self.groups}
        self.assertEqual({r['group_id'] for r in self.findings},ids)
    def test_parse_range(self):
        self.assertEqual(parsed_range('D339:AA340'),(4,339,27,340))
    def test_expansion_for_azd(self):
        r=next(x for x in self.groups if x['group_id']=='GD-AZD-001')
        self.assertEqual(select_range(r,self.cards),'D339:AA340')
    def test_missing_locations_resolved_from_card_catalog(self):
        for id in ('GD-JND-006','GD-EYV-005'):
            g=next(x for x in self.groups if x['group_id']==id)
            self.assertIsNotNone(select_range(g,self.cards))
    def test_rules_present(self):
        for r in self.groups:
            for rule in rule_text(r):
                self.assertTrue(rule['title'] and rule['fix'])
    def test_overlay_intersection(self):
        state={'value_overrides':{'MOBILE SS!G7':{'sheet':'MOBILE SS','target':'G7'},
              'MOBILE SS!K99':{'sheet':'MOBILE SS','target':'K99'}}}
        self.assertEqual(matching_overrides(state,'MOBILE SS','G7:G8'),['MOBILE SS!G7'])
    def test_guarded_overlay_respects_existing_value(self):
        class Cell:
            def __init__(self,value):self.Value=value
            @property
            def MergeArea(self):return self
            @property
            def Cells(self):return self
            @property
            def Count(self):return 1
        class WS:
            def __init__(self):self.data={'G7':Cell('1404/09/1404'),'G8':Cell('1404/ES/S/3844')}
            def Range(self,addr):return self
            def __init_cells(self):pass
            def __getattr__(self,key):
                if key=='Cells':return self
                raise AttributeError(key)
            def __call__(self,r,c):return self.data['G7']
        class Book:
            def __init__(self):self.cell=Cell('1404/09/1404')
            def Worksheets(self,s):return self
            def Range(self,t):return self
            def __getattribute__(self,name):
                if name=='Cells':return lambda r,c:self.cell
                return object.__getattribute__(self,name)
        book=Book();log=[]
        state={'value_overrides':{'MOBILE SS!G7':{'sheet':'MOBILE SS','target':'G7',
            'action':'SET_VALUE','expected_old_value':'1404/09/1404','value':'1404/09/18'}}}
        changes=apply_approved_overlays(book,state,log,{'MOBILE SS!G7'})
        self.assertEqual(book.cell.Value,'1404/09/18')
        self.assertEqual(len(changes),1)
        wrong=Book();wrong.cell.Value='1404/09/17';log=[]
        changes=apply_approved_overlays(wrong,state,log,{'MOBILE SS!G7'})
        self.assertEqual(changes,[])
        self.assertEqual(wrong.cell.Value,'1404/09/17')
        self.assertEqual(log[0]['status'],'SKIPPED_PRECONDITION')

    def test_inventory_integrity(self):
        with tempfile.TemporaryDirectory() as t:
            args=parse_args(['--root',t,'--input-dir',str(HERE),'--mode','inventory','--no-pdf','--out',str(Path(t)/'out')])
            self.assertEqual(build(args),0)
            self.assertIn('GD-NGN-001',(Path(t)/'out'/'GENERAL_DOCUMENT_REAL_EXCEL_GALLERY.html').read_text(encoding='utf-8'))
            import csv
            with (Path(t)/'out'/'all_103_findings_with_images.csv').open(encoding='utf-8-sig') as f:
                self.assertEqual(len(list(csv.DictReader(f))),103)

if __name__=='__main__':unittest.main()
