"""Offline, read-only batch template discovery and region-scoped field extraction.

Companion to Adaptive Document Annotator v0.6. Does not edit PDFs or Cleaner state.
Requires: pip install pymupdf opencv-python numpy; optional pytesseract + Tesseract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import cv2
import numpy as np
try:
    import pymupdf as fitz
except ImportError:
    import fitz

SIZE = (560, 792)  # comparable page thumbnails, not an OCR resolution
DATE_RE = re.compile(r'(?<!\d)(1[34]\d{2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})(?!\d)')
TRANSLATE = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def render_page(page):
    # Fixed-size thumbnails retain aspect ratio and explicitly pad with white.
    pix = page.get_pixmap(matrix=fitz.Matrix(1.0, 1.0), colorspace=fitz.csGRAY, alpha=False)
    raw = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    cw, ch = SIZE
    scale = min(cw / pix.width, ch / pix.height)
    nw, nh = max(1, round(pix.width * scale)), max(1, round(pix.height * scale))
    dst = np.full((ch, cw), 255, dtype=np.uint8)
    patch = cv2.resize(raw, (nw, nh), interpolation=cv2.INTER_AREA)
    ox, oy = (cw - nw) // 2, (ch - nh) // 2
    dst[oy:oy+nh, ox:ox+nw] = patch
    return dst


def fingerprint(gray):
    # Fingerprint printing infrastructure, not body contents. Fixed by design:
    # date/subject/letter text are allowed to differ between similar templates.
    reduced = cv2.resize(gray, (112, 158), interpolation=cv2.INTER_AREA)
    reduced = cv2.GaussianBlur(reduced, (5, 5), 2.0)
    h, w = reduced.shape
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[:int(.28*h), :] = 1       # letterhead and meta boxes
    mask[int(.83*h):, :] = 1       # footer and company mark
    mask[:, :int(.075*w)] = 1      # vertical branding, margin
    gx = cv2.Sobel(reduced, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(reduced, cv2.CV_32F, 0, 1, ksize=3)
    edge = cv2.magnitude(gx, gy)
    # Structure with dominant horizontal/vertical graphics is more distinctive.
    vec = np.concatenate([np.clip(255 - reduced.astype(np.float32), 0, 255)[mask>0], edge[mask>0] * .65])
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 1e-6 else vec


def compare(a, b):
    return float(np.dot(a, b))


def sha256_file(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda: f.read(2**20), b''):
            h.update(data)
    return h.hexdigest()


def static_proposals(images, outdir, gid):
    """Find recurrent printed ink, which is a PROPOSAL, never an exclusion policy."""
    if len(images) < 3:
        return []
    binary = np.stack([im < 170 for im in images], axis=0)
    persistence = binary.mean(axis=0).astype('float32')
    frequent = (persistence >= .82).astype('uint8') * 255
    frequent = cv2.morphologyEx(frequent, cv2.MORPH_OPEN, np.ones((2,2),np.uint8))
    joined = cv2.dilate(frequent, np.ones((7,5),np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(joined, 8)
    boxes = []
    height, width = images[0].shape
    for i in range(1, n):
        x,y,w,h,area = [int(v) for v in stats[i]]
        if area < 75 or w < 11 or h < 5 or w*h > .50 * width * height:
            continue
        boxes.append((x,y,x+w,y+h,area))
    boxes.sort(key=lambda b: b[4], reverse=True)
    proposals = []
    for x1,y1,x2,y2,_ in boxes[:40]:
        proposals.append({'bbox_norm':[round(x1/width,4),round(y1/height,4),round(x2/width,4),round(y2/height,4)],
                          'role_proposal':'IGNORE_STATIC','approved':False})
    preview = cv2.cvtColor(images[0], cv2.COLOR_GRAY2BGR)
    for x1,y1,x2,y2,_ in boxes[:40]:
        cv2.rectangle(preview,(x1,y1),(x2,y2),(0,0,255),2)
    cv2.imwrite(str(outdir / f'{gid}_static_suggestions.png'),preview)
    cv2.imwrite(str(outdir / f'{gid}_persistent_ink.png'),frequent)
    return proposals


def discover(args):
    root = Path(args.root)
    if not root.exists() or not root.is_dir():
        raise SystemExit('Folder not found: '+str(root))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    paths = sorted((root.rglob('*.pdf') if args.recursive else root.glob('*.pdf')),
                   key=lambda p:str(p).casefold())
    if args.max_files:
        paths = paths[:args.max_files]
    items, errors = [], []
    print(f'[DISCOVER] Scanning up to {len(paths)} PDFs (first page only, offline).')
    for i, path in enumerate(paths, 1):
        try:
            with fitz.open(str(path)) as doc:
                if len(doc)==0: continue
                page=doc[0]
                im=render_page(page)
                if (im < 225).mean() < .001:
                    errors.append({'path':str(path),'reason':'near-blank-page'})
                    continue
                items.append({'path':str(path),'relative':str(path.relative_to(root)),
                              'pages':len(doc),'aspect':round(page.rect.width/page.rect.height,3),
                              'image':im,'feature':fingerprint(im)})
        except Exception as exc:
            errors.append({'path':str(path),'error':str(exc)})
        if i%50==0: print(f'[SCAN] {i}/{len(paths)}')
    groups=[]
    for item in items:
        similarities=[]
        for grp in groups:
            if abs(grp['members'][0]['aspect'] - item['aspect']) > .07: continue
            similarities.append((compare(grp['representative']['feature'],item['feature']),grp))
        if similarities:
            score, group = max(similarities, key=lambda it:it[0])
        else:
            score, group = 0, None
        if group is not None and score >= args.threshold:
            item['similarity_to_prototype']=round(score,4)
            group['members'].append(item)
        else:
            group={'representative':item,'members':[item]}
            item['similarity_to_prototype']=1.0
            groups.append(group)
    serial=[]
    for idx, grp in enumerate(sorted(groups,key=lambda g:-len(g['members'])),1):
        gid=f'G{idx:03d}'
        members=grp['members']
        images=[x['image'] for x in members]
        cv2.imwrite(str(out/f'{gid}_example.png'),images[0])
        suggestions=static_proposals(images,out,gid)
        serial.append({'group_id':gid,'document_count':len(members),
                       'classification':'CANDIDATE_NOT_APPROVED',
                       'alignment':'page-size-normalization-only',
                       'static_mask_status':'REVIEW_REQUIRED',
                       'suggested_ignore_regions':suggestions,
                       'example_image':f'{gid}_example.png',
                       'members':[{'relative_path':x['relative'],'pages':x['pages'],
                                   'similarity':x['similarity_to_prototype']} for x in members]})
    result={'schema':'cleaner.template_discovery/0.1','source_root':str(root),
            'method':'letterhead-footer-visual-similarity+pixel-persistence',
            'important':'NO mask is approved automatically. Inspect alignment/structure and label EXTRACT zones.',
            'files_scanned':len(items),'candidate_groups':len(serial),
            'errors':errors,'groups':serial}
    (out/'discovery.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(f'[RESULT] files={len(items)} groups={len(serial)} errors={len(errors)}')
    for x in serial[:12]:print(f"[GROUP] {x['group_id']} files={x['document_count']} example={x['members'][0]['relative_path']}")
    print('[REVIEW]',out/'discovery.json')


def normalize_role(role):
    s=str(role or '').strip().upper()
    if s.startswith('IGNORE_STATIC'): return 'IGNORE_STATIC', s.partition(':')[2] or 'static_region'
    if s.startswith('EXTRACT:'): return 'EXTRACT', s.split(':',1)[1].strip().lower()
    if s in ('EXTRACT_DATE','DATE','LETTER_DATE'):return 'EXTRACT','letter_date'
    if s in ('EXTRACT_REFERENCE','LETTER_REFERENCE'):return 'EXTRACT','letter_reference'
    return None,None


def from_example(args):
    ex=Path(args.regions)
    raw=json.loads(ex.read_text(encoding='utf-8'))
    zones=[]
    for r in raw.get('regions',[]):
        act,field=normalize_role(r.get('role'))
        if not act:continue
        bb=r.get('bbox_normalized')
        if not bb:
            bb2=r.get('bbox'); wh=raw.get('page_size_px')
            if not bb2 or not wh: continue
            bb=[bb2[0]/wh[0],bb2[1]/wh[1],bb2[2]/wh[0],bb2[3]/wh[1]]
        bb=[round(float(v),5) for v in bb]
        if len(bb)!=4 or any(v<0 or v>1 for v in bb) or bb[0]>=bb[2] or bb[1]>=bb[3]:
            raise ValueError('Invalid rectangle for '+field)
        zones.append({'action':act,'field':field,'bbox_norm':bb,'source_region':r.get('id'),
                      'recognition':'native_then_ocr' if act=='EXTRACT' else 'none'})
    if not any(z['action']=='EXTRACT' for z in zones):
        raise SystemExit('No EXTRACT fields labeled. In Human Edit set a region Role to EXTRACT:letter_date etc.')
    payload={'schema':'cleaner.extraction_policy/0.1','family':raw.get('family'),
             'source_example':str(ex),'page_number':raw.get('page',1),
             'status':'DRAFT_REVIEW_REQUIRED',
             'zones':zones,'notes':'Draft generated from Human Edit labels; manual approval is necessary before production.'}
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print('[POLICY]',out,'zones=',len(zones),'draft; not approved')


def ocr_crop(page,rect,lang,psm):
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return '', 'ocr_dependency_unavailable'
    try:
        pix=page.get_pixmap(matrix=fitz.Matrix(300/72,300/72),clip=rect,colorspace=fitz.csRGB,alpha=False)
        im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        txt=pytesseract.image_to_string(im,lang=lang,config=f'--psm {psm}')
        return txt,'tesseract_region'
    except Exception as exc:
        return '',f'ocr_failed:{type(exc).__name__}:{exc}'


def date_values(text):
    return sorted(set('/'.join((y,m.zfill(2),d.zfill(2)))
                      for y,m,d in DATE_RE.findall(str(text).translate(TRANSLATE))))


def extract(args):
    policy=json.loads(Path(args.policy).read_text(encoding='utf-8'))
    if policy.get('schema')!='cleaner.extraction_policy/0.1':raise SystemExit('Unsupported policy schema')
    results=[]
    with fitz.open(args.pdf) as doc:
        pi=int(policy.get('page_number',1))-1
        if pi<0 or pi>=len(doc):raise SystemExit('Profile page does not exist in PDF')
        page=doc[pi]
        for zone in policy['zones']:
            if zone.get('action')!='EXTRACT':continue
            bb=zone['bbox_norm']; rect=fitz.Rect(bb[0]*page.rect.width,bb[1]*page.rect.height,
                                                   bb[2]*page.rect.width,bb[3]*page.rect.height)
            native=page.get_text('text',clip=rect).strip()
            native_dates=date_values(native)
            is_date=zone.get('field')=='letter_date'
            ocr='';ocr_method='not_requested'
            if is_date or not native:
                psm=7 if is_date else 6
                ocr,ocr_method=ocr_crop(page,rect,args.lang,psm)
                if is_date and not date_values(ocr):
                    retry,retry_method=ocr_crop(page,rect,args.lang,6)
                    if date_values(retry):ocr,ocr_method=retry,retry_method+'_psm6'
            ocr_dates=date_values(ocr)
            union=sorted(set(native_dates+ocr_dates))
            text=native or ocr.strip()
            expected=args.expected_date if is_date else None
            agreement=(bool(set(native_dates)&set(ocr_dates)) if native_dates and ocr_dates else None)
            if is_date:
                if expected and union and expected not in union:
                    status='DATE_CONFLICT_REQUIRES_REVIEW'
                elif native_dates and ocr_dates and agreement is False:
                    status='NATIVE_OCR_CONFLICT_REQUIRES_REVIEW'
                elif native_dates and ocr_dates and agreement:
                    status='DUAL_DATE_CANDIDATE_AGREES_UNVERIFIED'
                elif union:
                    status='SINGLE_READER_DATE_CANDIDATE_UNVERIFIED'
                else: status='DATE_NOT_READ_REVIEW_REQUIRED'
            else:
                status='EXTRACTED_UNVERIFIED' if text else 'UNREADABLE'
            results.append({'field':zone['field'],'page':pi+1,'bbox_norm':bb,
                            'candidate_text':text,'native_text':native,'ocr_text':ocr.strip(),
                            'native_dates':native_dates,'ocr_dates':ocr_dates,
                            'normalized_dates':union,'native_ocr_agreement':agreement,
                            'ocr_method':ocr_method,'expected_date':expected,'status':status})
    payload={'schema':'cleaner.source_evidence_extraction/0.1',
             'pdf':str(Path(args.pdf).resolve()),'sha256':sha256_file(Path(args.pdf)),
             'policy':str(Path(args.policy).resolve()),'policy_status':policy.get('status'),
             'state':'UNVERIFIED_DO_NOT_MUTATE_CLEANER','results':results}
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    for x in results: print('[FIELD]',x['field'],repr(x['candidate_text'][:80]),x['status'])
    print('[EVIDENCE]',out)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    d=sub.add_parser('discover',help='Cluster visual PDF templates; propose recurring fixed areas')
    d.add_argument('--root',required=True);d.add_argument('--out',required=True)
    d.add_argument('--max-files',type=int,default=150);d.add_argument('--threshold',type=float,default=.86)
    d.add_argument('--recursive',action='store_true')
    e=sub.add_parser('from-example',help='Build draft ignore/extract policy from v0.6 regions.json')
    e.add_argument('--regions',required=True);e.add_argument('--out',required=True)
    x=sub.add_parser('extract',help='Extract ONLY allowed fields by normalized coordinates')
    x.add_argument('--pdf',required=True);x.add_argument('--policy',required=True);x.add_argument('--out',required=True)
    x.add_argument('--expected-date');x.add_argument('--lang',default='fas+eng')
    args=p.parse_args()
    {'discover':discover,'from-example':from_example,'extract':extract}[args.command](args)

if __name__=='__main__':main()
