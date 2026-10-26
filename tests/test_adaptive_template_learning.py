import json
from pathlib import Path
import subprocess
import sys

import pymupdf

SCRIPT=Path(__file__).with_name('adaptive_template_learning.py')


def write_pdf(path, company, serial, date):
    doc=pymupdf.open()
    p=doc.new_page(width=595,height=842)
    if company=='A':
        p.draw_rect(pymupdf.Rect(25,25,140,95),color=(0,0,0),width=4)
        p.insert_text((30,45),'TAKIN ENERGY GROUP',fontsize=12)
        p.draw_line((20,120),(575,120),color=(0,0,0),width=2)
        p.draw_rect(pymupdf.Rect(25,790,570,825),color=(0,0,0),width=2)
    else:
        p.draw_circle((500,55),35,color=(0,0,0),width=5)
        p.insert_text((460,55),'OTHER CO',fontsize=12)
        p.draw_line((20,160),(575,160),color=(0,0,0),width=3)
        p.draw_line((30,810),(550,800),color=(0,0,0),width=4)
    p.insert_text((25,100),f'Date: {date}  Ref: {serial}',fontsize=11)
    p.insert_text((70,330),f'Request about document serial {serial}: content changes every time',fontsize=11)
    doc.save(path)
    doc.close()


def run(*args):
    return subprocess.run([sys.executable,str(SCRIPT),*map(str,args)],capture_output=True,text=True,check=True)


def test_discover_and_extraction(tmp_path):
    inp=tmp_path/'letters';inp.mkdir()
    for n in range(3):write_pdf(inp/f'a_{n}.pdf','A',f'A-33{n}',f'1404/07/{19+n:02}')
    for n in range(3):write_pdf(inp/f'b_{n}.pdf','B',f'B-47{n}',f'1404/08/{10+n:02}')
    out=tmp_path/'groups'
    run('discover','--root',inp,'--out',out,'--max-files','10','--threshold','.83')
    result=json.loads((out/'discovery.json').read_text(encoding='utf8'))
    assert result['files_scanned']==6
    assert result['candidate_groups']>=2, [g['members'] for g in result['groups']]
    assert any(g['document_count']>=3 for g in result['groups'])
    reg=tmp_path/'regions.json'
    reg.write_text(json.dumps({'family':'ENGINEERING_CORRESPONDENCE','page':1,'page_size_px':[595,842],
                               'regions':[{'id':'R01','role':'IGNORE_STATIC:logo','bbox_normalized':[.01,.01,.24,.12]},
                                          {'id':'R02','role':'EXTRACT:letter_date','bbox_normalized':[.04,.10,.20,.14]}]}),encoding='utf8')
    policy=tmp_path/'policy.json'
    run('from-example','--regions',reg,'--out',policy)
    assert json.loads(policy.read_text())['status']=='DRAFT_REVIEW_REQUIRED'
    audit=tmp_path/'audit.json'
    run('extract','--pdf',inp/'a_0.pdf','--policy',policy,'--out',audit,'--expected-date','1404/07/19')
    payload=json.loads(audit.read_text())
    assert payload['state']=='UNVERIFIED_DO_NOT_MUTATE_CLEANER'
    assert payload['results'][0]['normalized_dates']==['1404/07/19'],payload['results']
    assert payload['results'][0]['status'] in {'DUAL_DATE_CANDIDATE_AGREES_UNVERIFIED','SINGLE_READER_DATE_CANDIDATE_UNVERIFIED'}

if __name__=='__main__':
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as td:
        print(test_discover_and_extraction(Path(td)))
