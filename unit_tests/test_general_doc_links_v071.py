from pathlib import Path
import tempfile
import unittest
import sys
from zipfile import ZipFile
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cleaner_v07.links import absolute_target,rewrite_links,wrap_retrieval,sha


def book(path,target='../letters/drawing%20one.pdf',formula='HYPERLINK("../letters/a.pdf","نامه")',base=''):
    from xml.sax.saxutils import escape
    with ZipFile(path,'w') as z:
        z.writestr('xl/worksheets/_rels/sheet1.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" TargetMode="External" Target="'+escape(target,{'"':'&quot;'})+'"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c r="A1"><f>'+escape(formula)+'</f></c></row></sheetData></worksheet>')
        z.writestr('docProps/app.xml','<Properties><HyperlinkBase>'+escape(base)+'</HyperlinkBase></Properties>')
        z.writestr('xl/styles.xml',b'<styles>UNCHANGED</styles>')
        z.writestr('xl/drawings/drawing1.xml',b'unchanged drawing bytes')

class LinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def test_windows_parent_and_persian(self):
        self.assertEqual(absolute_target('../letters/a.pdf',r'W:\Project\Updated Doc\General.xlsx'),'file:///W:/Project/letters/a.pdf')
        self.assertIn('%D9',absolute_target('../نامه.pdf',r'W:\Project\Updated Doc\General.xlsx'))
    def test_unc_source(self):
        self.assertEqual(absolute_target('../a.pdf',r'\\server\share\Project\General.xlsx'),'file://server/share/a.pdf')
    def test_absolute_and_internal_unchanged(self):
        for link in ['https://example.com/a','mailto:a@b.com','file:///W:/a.pdf',r'W:\a.pdf',r'\\server\share\a.pdf',"#'Sheet 1'!A1"]:
            self.assertEqual(absolute_target(link,r'W:\Project\General.xlsx'),link)
    def test_hyperlink_base(self):
        self.assertEqual(absolute_target('a.pdf',r'W:\Project\General.xlsx',r'W:\Letters'),'file:///W:/Letters/a.pdf')
        self.assertEqual(absolute_target('a.pdf',r'W:\Project\Updated\General.xlsx','../Letters'),'file:///W:/Project/Letters/a.pdf')
    def test_percent_encoded_hash_kept_in_filename(self):
        self.assertEqual(absolute_target('a%23b.pdf',r'W:\Project\General.xlsx'),'file:///W:/Project/a%23b.pdf')
    def test_rewrite_preserves_other_package_parts(self):
        p=self.root/'copy.xlsx';book(p)
        with ZipFile(p) as z:before={n:z.read(n) for n in z.namelist()}
        r=rewrite_links(p,r'W:\Project\Updated Doc\General.xlsx')
        self.assertEqual(r['converted'],2)
        with ZipFile(p) as z:
            for n in ['xl/styles.xml','xl/drawings/drawing1.xml','docProps/app.xml']:self.assertEqual(z.read(n),before[n])
            target=next(iter(ET.fromstring(z.read('xl/worksheets/_rels/sheet1.xml.rels')))).get('Target')
            self.assertEqual(target,'file:///W:/Project/letters/drawing%20one.pdf')
            self.assertIn(b'file:///W:/Project/letters/a.pdf',z.read('xl/worksheets/sheet1.xml'))
        self.assertNotEqual(r['before_sha256'],r['after_sha256'])
        after=sha(p);second=rewrite_links(p,r'W:\Project\Updated Doc\General.xlsx')
        self.assertEqual(second['converted'],0);self.assertEqual(sha(p),after)
    def test_dynamic_formula_remains_explicit(self):
        p=self.root/'copy.xlsx';book(p,target='https://example.com/a',formula='HYPERLINK(A2&"/a.pdf","name")')
        r=rewrite_links(p,r'W:\Project\General.xlsx')
        self.assertEqual(r['converted'],0);self.assertEqual(len(r['unresolved']),1)
    def test_internal_formula_not_changed(self):
        p=self.root/'copy.xlsx';book(p,target='https://example.com/a',formula='HYPERLINK("#Sheet2!A1","here")')
        before=sha(p);r=rewrite_links(p,r'W:\Project\General.xlsx')
        self.assertEqual(r['converted'],0);self.assertEqual(before,sha(p))
    def test_refuse_original(self):
        p=self.root/'original.xlsx';book(p);before=sha(p)
        with self.assertRaises(ValueError):rewrite_links(p,str(p))
        self.assertEqual(before,sha(p))
    def test_actual_retrieval_contract_and_hashes(self):
        from functions.retrieval.service import retrieve_document
        p=self.root/'original.xlsx';book(p);before=sha(p)
        cfg={'families':{'GENERAL_DOCUMENT':{'name_token':'LATEST_GENERAL_DOC'}},'projects':{'AZD':{'sources':{'GENERAL_DOCUMENT':{'mode':'direct','path':str(p)}}}}}
        result=wrap_retrieval(retrieve_document)(cfg,project_id='AZD',family='GENERAL_DOCUMENT',destination=self.root/'input',retrieval_date='14050730')
        self.assertEqual(sha(p),before)
        self.assertEqual(result.metadata['source_sha256'],before)
        self.assertEqual(result.sha256,sha(result.retrieved_path))
        self.assertEqual(result.metadata['absolute_links']['converted'],2)

    def test_retrieval_wrapper_is_idempotent_after_install(self):
        from functions.retrieval.service import retrieve_document
        p=self.root/'original.xlsx';book(p);before=sha(p)
        cfg={'families':{'GENERAL_DOCUMENT':{'name_token':'LATEST_GENERAL_DOC'}},'projects':{'AZD':{'sources':{'GENERAL_DOCUMENT':{'mode':'direct','path':str(p)}}}}}
        wrapped=wrap_retrieval(wrap_retrieval(retrieve_document))
        result=wrapped(cfg,project_id='AZD',family='GENERAL_DOCUMENT',destination=self.root/'input',retrieval_date='14050730')
        self.assertEqual(sha(p),before)
        self.assertEqual(result.metadata['source_sha256'],before)
        self.assertEqual(result.metadata['absolute_links']['converted'],2)

if __name__=='__main__':unittest.main()
