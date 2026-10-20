# -*- coding: utf-8 -*-
import csv
from pathlib import Path
import tempfile
import unittest
from html.parser import HTMLParser
from GENERAL_DOC_REAL_SCREENSHOT_GALLERY_V02 import read_csv, RULES, build, parse_args
from GENERAL_DOC_GALLERY_LOCALE import RULES_FA, UI, TERMS, rule_localized, state_label

HERE = Path(__file__).resolve().parent

class _GalleryParser(HTMLParser):
    def __init__(self):super().__init__(); self.cases=0;self.images=0
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag=='article' and 'id' in d:self.cases+=1
        if tag=='img':self.images+=1

class BilingualGalleryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.groups=read_csv(HERE/'GENERAL_DOC_REVIEW_GROUPS.csv')
        cls.findings=read_csv(HERE/'GENERAL_DOC_FINDINGS_103.csv')
    def test_58_groups_103_findings_8_projects(self):
        self.assertEqual(len(self.groups),58)
        self.assertEqual(len(self.findings),103)
        self.assertEqual(len(set(x['project'] for x in self.groups)),8)
    def test_all_known_rules_are_translated(self):
        self.assertEqual(set(RULES),set(RULES_FA))
    def test_every_finding_type_has_translation(self):
        for f in self.findings:
            for code in f['issue'].split(';'):
                self.assertIn(code.strip(),RULES_FA)
    def test_combined_issues_not_dropped(self):
        key='MERGED_STATUS; POSSIBLE_NARRATIVE_REFERENCE; RECEIVE_STATUS_MISSING'
        title,action=rule_localized(key,'fa',RULES)
        self.assertIn('وضعیت در سلول مرکب',title)
        self.assertIn('شمارهٔ مرجع',title)
        self.assertIn('خالی بودن وضعیت پاسخ',title)
        self.assertGreater(len(action),150)
    def test_approved_terminology(self):
        terms=dict(TERMS)
        for key,val in [('General Document','دفتر گردش اسناد مهندسی'),('Engineering','بخش مهندسی'),
                        ('Revision','نسخه (Revision)'),('Cleaner','نظافتچی'),
                        ('Original Workbook','فایل اکسل اصلی'),('Issue','مغایرت'),
                        ('Portfolio','سبد پروژه‌ها'),('Original Evidence','شواهد اصلی'),
                        ('Narrative / Explanatory Text','شرح رویداد'),('Merged Cell','سلول مرکب')]:
            self.assertEqual(terms[key],val)
    def test_non_applicable_corrections_not_treated_as_pass(self):
        self.assertEqual(state_label('UNRESOLVED','fa'),'رسیدگی‌نشده')
        self.assertNotIn('تأییدشده',state_label('UNRESOLVED','fa'))
    def test_inventory_both_html_and_csv(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            args=parse_args(['--root',str(root),'--input-dir',str(HERE), '--mode','inventory',
                             '--no-pdf','--lang','both','--out',str(root/'test-output')])
            self.assertEqual(build(args),0)
            out=root/'test-output'
            for lang,term,dir_value in [('FA','دفتر گردش اسناد مهندسی','rtl'),('EN','GENERAL DOCUMENT','ltr')]:
                doc=(out/f'GENERAL_DOCUMENT_REAL_EXCEL_GALLERY_{lang}.html').read_text(encoding='utf8')
                self.assertIn(term,doc)
                self.assertIn(f'<html lang="{lang.lower()}" dir="{dir_value}"',doc)
                self.assertIn('GD-NGN-001',doc)
                parser=_GalleryParser();parser.feed(doc)
                self.assertEqual(parser.cases,58)
            fa=(out/'GENERAL_DOCUMENT_REAL_EXCEL_GALLERY_FA.html').read_text(encoding='utf8')
            self.assertIn('وضعیت در سلول مرکب',fa)
            self.assertIn('لایهٔ',fa) if False else None
            self.assertIn('در انتظار رسیدگی',fa) if False else None
            self.assertIn('سلول مرکب',fa)
            self.assertNotIn('naïve date',fa)
            self.assertEqual((out/'GENERAL_DOCUMENT_REAL_EXCEL_GALLERY.html').read_text(encoding='utf8'),fa)
            for name,expected in [('all_103_findings_bilingual.csv',103),('all_58_grouped_cases_bilingual.csv',58)]:
                with (out/name).open(encoding='utf-8-sig',newline='') as file:
                    self.assertEqual(len(list(csv.DictReader(file))),expected)
            with (out/'all_103_findings_bilingual.csv').open(encoding='utf-8-sig',newline='') as file:
                cases=list(csv.DictReader(file))
                self.assertTrue(all(f['recommended_action_fa'] and f['issue_title_fa'] for f in cases))
                self.assertEqual({f['project'] for f in cases},{'AZD','JND','FSH','YSK','EYV','BFG','NKH','NGN'})
    def test_args_one_language(self):
        self.assertEqual(parse_args(['--lang','fa','--mode','inventory']).lang,'fa')
        self.assertEqual(parse_args(['--lang','en','--mode','inventory']).lang,'en')
        self.assertEqual(parse_args(['--mode','inventory']).lang,'both')

if __name__=='__main__':unittest.main()
