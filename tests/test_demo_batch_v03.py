import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

def module(name):
    p=Path(__file__).resolve().parents[1]/(name+'.py')
    s=importlib.util.spec_from_file_location(name,p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

class Review(Exception):
    def __init__(self,stage,message,count=0):
        super().__init__(message); self.stage=stage; self.count=count

def fake(tmp_path, structural=False):
    saved=[]; calls=[]
    def stage(*a):
        if structural: raise Review('FIELD_VALIDATION','Unknown mapping')
    def board(*a):
        calls.append('board'); raise Review('BOARD_TO_LOG','One unresolved cell',1)
    def coverage(*a):
        calls.append('coverage'); raise Review('COVERAGE','Unmapped slot',1)
    def engineering(*a):
        calls.append('engineering'); raise Review('ENGINEERING','Unknown status',1)
    m=SimpleNamespace(STAGES=['M_LINE','FIELD_VALIDATION'], ReviewNeeded=Review, LOG_NAME='board.json', ENGINEERING_NAME='report.json',
        choose_run=lambda *a:('run1',tmp_path), save_progress=lambda d,p:saved.append(json.loads(json.dumps(p))),
        guarded_stage=stage, guard_wrong_field_replacement=lambda *a:None,
        guarded_board_to_log=board, guarded_coverage=coverage, guarded_engineering=engineering,
        load=lambda p:{'issues':[{'kind':'unknown'}]})
    return m,saved,calls

def args():
    return SimpleNamespace(color='never',workbook=__file__, project='NGN',status_date='1405/07/30')

def test_deferred_reviews_still_calculate(tmp_path):
    m,s,c=fake(tmp_path)
    assert module('RUN_GENERAL_DOCUMENT_BATCH_V03').execute(m,args())==2
    assert c==['board','coverage','engineering']
    assert len(s[-1]['review_items'])==3
    assert s[-1]['report_status']=='PROVISIONAL_REVIEW_PENDING'

def test_unknown_structure_blocks_dependent_calculation(tmp_path):
    m,s,c=fake(tmp_path,True)
    assert module('RUN_GENERAL_DOCUMENT_BATCH_V03').execute(m,args())==2
    assert not c
    assert s[-1]['report_status']=='BLOCKED_STRUCTURAL_REVIEW'

def test_hard_error_not_silently_deferred(tmp_path):
    m,s,c=fake(tmp_path)
    m.guarded_board_to_log=lambda *a: (_ for _ in ()).throw(RuntimeError('corrupt data'))
    assert module('RUN_GENERAL_DOCUMENT_BATCH_V03').execute(m,args())==1
    assert s[-1]['status']=='ERROR'
    assert not c

def test_collects_every_audit_and_all_projects(tmp_path):
    m=module('DEMO_ALL_GENERAL_DOCS');m.ROOT=tmp_path
    cfg={'AZD':{},'JND':{}}
    for project in cfg:
        rid=project.lower(); run=tmp_path/'runs'/rid
        eng=run/'engineering_lists'; eng.mkdir(parents=True)
        for key,filename,_ in m.OUTPUTS:
            m.write_csv(eng/filename,[{'document':project+'_'+key}])
        (run/'nested').mkdir();(run/'nested'/'extra_audit.csv').write_text('audit\n1\n')
        m.write_json(run/'field_validation_review_queue.json',{'items':[{'review_id':'x','cell':'A1'}]})
        m.write_json(tmp_path/'batch'/'projects'/project/'state.json',dict(project=project,run_id=rid,status='REVIEW_REQUIRED',status_date='1405/07/30'))
    out=m.gather(tmp_path/'batch',list(cfg),cfg)
    assert all(len(rows)==2 for rows in out['lists'].values())
    assert all(p['report_status']=='PROVISIONAL_REVIEW_PENDING' for p in out['projects'])
    assert (tmp_path/'batch'/'projects'/'AZD'/'evidence'/'nested'/'extra_audit.csv').is_file()
    assert any(r['detail'].find('A1')>=0 for r in out['reviews'] if r.get('detail'))

def test_missing_is_not_zero(tmp_path):
    m=module('DEMO_ALL_GENERAL_DOCS');m.ROOT=tmp_path
    out=m.gather(tmp_path/'batch',['NGN'],{'NGN':{}})
    assert out['projects'][0]['not_sent']==''
    assert out['projects'][0]['report_status']=='NOT_CALCULATED'

def test_source_snapshot_timestamp_and_integrity(tmp_path):
    m=module('DEMO_ALL_GENERAL_DOCS')
    source=tmp_path/'old.xlsx';source.write_bytes(b'old content')
    state={}; dest=m.snapshot_source(source,tmp_path/'project',state,'TEST')
    assert dest.name.endswith('__old.xlsx')
    assert dest.name!=source.name
    assert dest.read_bytes()==source.read_bytes()
    assert state['sha256']==m.sha256(source)

if __name__ == '__main__':
    import tempfile
    import unittest
    class BatchTests(unittest.TestCase):
        pass
    for name, func in list(globals().items()):
        if name.startswith('test_') and callable(func):
            def run(self, f=func):
                with tempfile.TemporaryDirectory() as directory:
                    f(Path(directory))
            setattr(BatchTests,name,run)
    del func
    unittest.main()
