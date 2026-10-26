"""Repair hyperlinks in a retrieved COPY using its original source workbook path."""
import argparse
from pathlib import Path
import shutil
from datetime import datetime
from cleaner_v07.links import rewrite_links
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--workbook',required=True)
p.add_argument('--source-path',required=True)
a=p.parse_args()
path=Path(a.workbook)
if path.resolve()==Path(a.source_path).resolve():p.error('Use a separate retrieved copy')
backup=path.with_name(path.stem+'.before_links_'+datetime.now().strftime('%Y%m%dT%H%M%S%f')+path.suffix)
shutil.copy2(path,backup)
r=rewrite_links(path,a.source_path)
print('[LINKS] converted=',r['converted'],'unresolved=',len(r['unresolved']))
print('[BACKUP]',backup)
