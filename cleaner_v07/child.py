"""Process-local adapters; installed repository modules remain untouched."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from cleaner_v07 import runtime as r

def main():
    r.install_live_excel()
    try:
        operation=sys.argv[1]
        if operation=='materialize':
            r.materialize(Path(sys.argv[2]));return
        if operation=='known':
            r.auto_known(Path(sys.argv[2]),Path(sys.argv[3]));return
        script=Path(operation).resolve()
        if not script.is_relative_to(ROOT): raise ValueError('Child script must be inside Cleaner repository')
        if script.name=='weekly_report_pipeline.py':
            r.install_executor()
            import functions.cleaner as exports
            from functions.cleaner import executor
            exports.create_cleaned_copy_com=executor.create_cleaned_copy_com
            r.install_ordering()
        sys.argv=[str(script),*sys.argv[2:]]
        if script.name=='review_findings.py':
            reviewer=r.import_path('_v07_interactive_reviewer',script)
            original_show=reviewer.ExcelReviewNavigator.show
            def show(self,*a,**k): return r.retry(lambda:original_show(self,*a,**k))
            reviewer.ExcelReviewNavigator.show=show
            reviewer.main()
        else:
            import runpy
            runpy.run_path(str(script),run_name='__main__')
    finally:
        r.cleanup()

if __name__=='__main__': main()
