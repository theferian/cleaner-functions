"""Resolve copied workbook hyperlinks against the original source location.

Edits only relationship attributes and literal HYPERLINK first arguments inside
OOXML ZIP parts; other XML, cells, styles, drawings and VBA bytes stay intact.
"""
from __future__ import annotations
from dataclasses import replace
import hashlib
import html
import json
import ntpath
import os
from pathlib import Path
import re
from urllib.parse import quote, unquote, urljoin, urlsplit
from xml.sax.saxutils import escape
from zipfile import ZipFile, is_zipfile

REL=re.compile(r'<(?:[\w]+:)?Relationship\b[^>]*>',re.S)
ATTR=re.compile(r'([\w:]+)\s*=\s*([\"\'])(.*?)\2',re.S)
FORMULA=re.compile(r'(<(?:[\w]+:)?f\b[^>]*>)(.*?)(</(?:[\w]+:)?f>)',re.S)
LITERAL=re.compile(r'^(\s*=?\s*(?:_xlfn\.)?HYPERLINK\s*\(\s*)"((?:[^"]|"")*)"(?=\s*[,;)])',re.I)

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def is_absolute(target):
    return (not target or target.startswith('#') or bool(re.match(r'^[A-Za-z]:[\\/]',target))
            or target.startswith(('\\\\','//','/')) or bool(re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:',target)))

def base_uri(source, hyperlink_base=''):
    source=str(source)
    if re.match(r'^[A-Za-z]:[\\/]',source):
        folder=ntpath.dirname(source).replace('\\','/')+'/'
        base='file:///'+quote(folder,safe='/:')
    elif source.startswith('\\\\'):
        base='file:'+quote(ntpath.dirname(source).replace('\\','/')+'/',safe='/')
    elif re.match(r'^https?://|^file:',source,re.I):
        base=urljoin(source,'./')
    elif Path(source).is_absolute():
        base=Path(source).parent.as_uri()+'/'
    else:
        raise ValueError('Original source path must be absolute: '+source)
    if hyperlink_base:
        raw=hyperlink_base.replace('\\','/')
        if re.match(r'^[A-Za-z]:/',raw): base='file:///'+quote(raw,safe='/:').rstrip('/')+'/'
        elif raw.startswith('//'): base='file:'+quote(raw,safe='/').rstrip('/')+'/'
        else: base=urljoin(base,quote(unquote(raw),safe='/:#%')).rstrip('/')+'/'
    return base

def absolute_target(target,source,hyperlink_base=''):
    if is_absolute(target):return target
    base=base_uri(source,hyperlink_base)
    raw=target.replace('\\','/')
    # A backslash-rooted Windows path is rooted on the source drive/share.
    if raw.startswith('/'):
        parsed=urlsplit(base)
        if parsed.scheme=='file' and re.match(r'^/[A-Za-z]:/',parsed.path):
            return 'file://'+parsed.path[:3]+quote(unquote(raw),safe='/:#')
    parsed=urlsplit(raw)
    encoded=quote(unquote(parsed.path),safe='/:')
    if parsed.query:encoded+='?'+parsed.query
    if parsed.fragment:encoded+='#'+quote(unquote(parsed.fragment),safe='!:$,')
    return urljoin(base,encoded)

def rewrite_links(workbook,source):
    path=Path(workbook)
    if Path(source).resolve()==path.resolve():raise ValueError('Refusing to modify the original source workbook')
    before=sha(path);changes=[];skipped=[];parts={}
    with ZipFile(path) as z:
        hyperlink_base=''
        if 'docProps/app.xml' in z.namelist():
            import xml.etree.ElementTree as ET
            for node in ET.fromstring(z.read('docProps/app.xml')).iter():
                if node.tag.split('}')[-1]=='HyperlinkBase':hyperlink_base=node.text or ''
        for name in z.namelist():
            if not (name.endswith('.rels') or re.match(r'xl/worksheets/[^/]+\.xml$',name)):continue
            original=z.read(name);text=original.decode('utf-8')
            def rel(match):
                attrs={m[1]:html.unescape(m[3]) for m in ATTR.finditer(match[0])}
                if not attrs.get('Type','').endswith('/hyperlink') or attrs.get('TargetMode')!='External':return match[0]
                old=attrs.get('Target','');new=absolute_target(old,source,hyperlink_base)
                if old==new:return match[0]
                changes.append(dict(part=name,kind='hyperlink',before=old,after=new))
                def attr(m):
                    if m[1]!='Target':return m[0]
                    return 'Target='+m[2]+escape(new,{'"':'&quot;',"'":'&apos;'})+m[2]
                return ATTR.sub(attr,match[0])
            def formula(match):
                text=html.unescape(match[2]);m=LITERAL.match(text)
                if not m:
                    if re.search(r'\bHYPERLINK\s*\(',text,re.I): skipped.append(dict(part=name,kind='DYNAMIC_HYPERLINK',formula=text))
                    return match[0]
                old=m[2].replace('""','"');new=absolute_target(old,source,hyperlink_base)
                if old==new:return match[0]
                changes.append(dict(part=name,kind='HYPERLINK_formula',before=old,after=new))
                changed=m[1]+'"'+new.replace('"','""')+'"'+text[m.end():]
                return match[1]+escape(changed)+match[3]
            text=REL.sub(rel,text) if name.endswith('.rels') else FORMULA.sub(formula,text)
            if text.encode('utf-8')!=original:parts[name]=text.encode('utf-8')
        if parts:
            temp=path.with_name(path.name+'.links.tmp')
            try:
                with ZipFile(temp,'w') as out:
                    out.comment=z.comment
                    for item in z.infolist():out.writestr(item,parts.get(item.filename,z.read(item.filename)))
                with ZipFile(temp) as check:
                    if check.testzip():raise ValueError('Hyperlink conversion ZIP verification failed')
            except BaseException:
                temp.unlink(missing_ok=True);raise
    if parts:temp.replace(path)
    receipt=dict(schema='cleaner.absolute_links/0.7.1',original_source=str(source),workbook=str(path),
                 before_sha256=before,after_sha256=sha(path),converted=len(changes),changes=changes,unresolved=skipped)
    Path(str(path)+'.links.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return receipt

def wrap_retrieval(original):
    # The installer patches the repository's retrieval function, while callers
    # and tests may also apply this adapter explicitly. Avoid normalizing twice:
    # a second pass would report the already-normalized copy as the source hash.
    if getattr(original, '_cleaner_absolute_links_wrapper', False):
        return original
    def retrieve(*args,**kwargs):
        result=original(*args,**kwargs)
        if str(result.family).upper()!='GENERAL_DOCUMENT':return result
        if Path(result.source_path).resolve()==Path(result.retrieved_path).resolve():
            raise ValueError('General Doc retrieval needs a separate destination for link conversion')
        receipt=rewrite_links(result.retrieved_path,result.source_path)
        print('[LINKS] absolute conversions='+str(receipt['converted'])+'; unresolved formulas='+str(len(receipt['unresolved'])))
        return replace(result,sha256=receipt['after_sha256'],metadata={**result.metadata,
            'source_sha256':receipt['before_sha256'],'retrieved_sha256':receipt['after_sha256'],
            'absolute_links':receipt,'copy_action':'copied_links_normalized'})
    retrieve._cleaner_absolute_links_wrapper = True
    return retrieve

def original_source(bound,root,project):
    bound=Path(bound);root=Path(root)
    sidecar=Path(str(bound)+'.links.json')
    if sidecar.is_file():return json.loads(sidecar.read_text(encoding='utf-8'))['original_source']
    lineage=bound.parent/'source_lineage.json'
    if lineage.is_file():
        candidate=json.loads(lineage.read_text(encoding='utf-8')).get('source')
        if candidate and str(candidate)!=str(bound):return original_source(candidate,root,project)
    manifest=root/'input'/f'{project}_retrieval_manifest.json'
    if manifest.is_file():
        for item in json.loads(manifest.read_text(encoding='utf-8-sig')).get('results',[]):
            raw=item.get('retrieved_path','')
            if (str(item.get('project_id','')).upper()==str(project).upper()
                and str(item.get('family','')).upper()=='GENERAL_DOCUMENT'
                and ntpath.basename(raw).casefold()==bound.name.casefold()):
                return item.get('source_path')
    return None
