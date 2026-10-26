"""Enable absolute hyperlinks in the existing prepare-general-doc command."""
from pathlib import Path
from datetime import datetime
import argparse
import ast
import shutil

ROOT=Path(__file__).resolve().parent
MARKER='# CLEANER_GENERAL_DOC_ABSOLUTE_LINKS_V071'
PATCH='\n\n'+MARKER+'\nfrom cleaner_v07.links import wrap_retrieval as _absolute_links_wrapper\nretrieve_document = _absolute_links_wrapper(retrieve_document)\n'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true');mode.add_argument('--apply',action='store_true')
    a=p.parse_args()
    service=ROOT/'functions'/'retrieval'/'service.py'
    if not service.is_file():raise SystemExit('Run this installer from the cleaner-functions repository root')
    text=service.read_text(encoding='utf-8-sig')
    tree=ast.parse(text)
    if not any(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name=='retrieve_document' for n in tree.body):
        raise SystemExit('Unsupported retrieval service: retrieve_document was not found; no edit made')
    if MARKER in text:
        print('[OK] Absolute-link retrieval hook already installed');return
    updated=text+PATCH;ast.parse(updated)
    print('[CHECK] Existing retrieve_document found; hook can be added')
    if a.apply:
        backup=service.with_name('service.py.before_v071_'+datetime.now().strftime('%Y%m%dT%H%M%S%f'))
        shutil.copy2(service,backup)
        temp=service.with_suffix('.py.tmp');temp.write_text(updated,encoding='utf-8');temp.replace(service)
        print('[INSTALLED]',service)
        print('[BACKUP]',backup)
if __name__=='__main__':main()
