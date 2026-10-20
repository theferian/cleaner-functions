"""Headless AZD correspondence layout proposal using the user's existing v0.6 DetectionEngine.

Read only source. Outputs labeled PNGs and reviewable JSON; DOES NOT verify or
correct General Doc values. Run from any directory; bundled alongside v0.6.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont

# Reuse the real Adaptive Document Annotator segmentation engine, unchanged.
from adaptive_document_annotator_v0_6 import DetectionEngine

SCHEMA = "adaptive-letter-layout-proposals/0.1"
DIGIT_TRANSLATION = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
DATE_RE = re.compile(r"(?<!\d)(1[34]\d{2})\s*[/\-.]\s*(0?[1-9]|1[0-2])\s*[/\-.]\s*(0?[1-9]|[12]\d|3[01])(?!\d)")
FULL_REF_RE = re.compile(r"(?<!\w)(1[34]\d{2})\s*[/\\-]\s*([a-zA-Z]{1,5})\s*[/\\-]\s*([a-zA-Z]{1,3})\s*[/\\-]\s*(\d{2,8})(?!\d)",re.I)
COLORS = {"table":"#24a166", "text_block":"#3183e5", "header":"#ba6dd9", "title":"#e26d35", "image":"#9470ca"}
ROLE_WORDS = {
    "letter_reference": ("شماره", "شماره نامه", "reference", "ref.", "letter no", "letter number"),
    "date": ("تاریخ", "date", "dated"),
    "subject": ("موضوع", "subject", "re:", "regarding"),
    "recipient": ("گیرنده", "خطاب به", "به:", "to:", "attention"),
    "sender": ("فرستنده", "از:", "from:"),
    "attachment": ("پیوست", "ضمیمه", "attachment", "enclosure"),
    "signature": ("امضا", "امضاء", "signature", "signed by"),
    "stamp": ("مهر", "stamp", "seal"),
}


def norm(s):
    return str(s or "").translate(DIGIT_TRANSLATION).replace("\u200c", " ").replace("\u200e", "").strip()


def canonical_date(match):
    y, m, d = map(int, match.groups())
    return f"{y:04d}/{m:02d}/{d:02d}"


def canonical_ref(raw):
    m = FULL_REF_RE.search(norm(raw))
    if not m:
        return None
    year, office, direction, serial = m.groups()
    return f"{year}/{office.upper()}/{direction.upper()}/{serial}"


def area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def intersection_ratio(a, b):
    inter = area((max(a[0],b[0]), max(a[1],b[1]), min(a[2],b[2]), min(a[3],b[3])))
    return inter / max(1.0, min(area(a), area(b)))


def pdf_native_blocks(page, sx, sy):
    out=[]
    for block in page.get_text("blocks"):
        if len(block) < 7: continue
        x0,y0,x1,y1 = block[:4]
        if block[6] == 0 and not str(block[4]).strip(): continue
        out.append({"bbox":[round(x0*sx,1),round(y0*sy,1),round(x1*sx,1),round(y1*sy,1)],
                    "text":str(block[4] or "").strip() if block[6] == 0 else "",
                    "native_type":"text" if block[6]==0 else "image" if block[6]==1 else "unknown"})
    return out


def role_label_present(content, label):
    norm_label = norm(label).casefold()
    if norm_label in ("re:", "to:", "from:"):
        return re.search(r"(?<![a-z])" + re.escape(norm_label), content) is not None
    return norm_label in content


def classify_region(region, native_text):
    s=norm(native_text).casefold()
    region["role_candidates"] = [k for k, words in ROLE_WORDS.items() if any(role_label_present(s,w) for w in words)]
    if region.get("layout_type") == "text_block" and region["bbox"][1] < region.get("page_height",1)*.22 and region["role_candidates"]:
        region["suggested_layout_type"] = "header"
    else:
        region["suggested_layout_type"] = region["layout_type"]
    if "signature" in region["role_candidates"] or "stamp" in region["role_candidates"]:
        region["role_warning"] = "label text alone does not verify a physical stamp/signature"
    return region


def build_regions(detector_result, native_blocks, h, w):
    regions=[]
    for idx,p in enumerate(detector_result["proposals"],1):
        b=[round(float(v),1) for v in p["bbox"]]
        matched=[x for x in native_blocks if x["native_type"] == "text" and intersection_ratio(b,x["bbox"]) >= .28]
        native="\n".join(dict.fromkeys(x["text"] for x in matched))
        r={"id":f"R{idx:03d}","layout_type":p["layout_type"], "bbox_px":b,
           "bbox_normalized":[round(b[0]/w,5),round(b[1]/h,5),round(b[2]/w,5),round(b[3]/h,5)],
           "confidence":round(float(p["confidence"]),3),"source":p["source"],
           "native_text":native[:2500],"page_height":h,"bbox":b}
        classify_region(r,native)
        r.pop("page_height");r.pop("bbox")
        regions.append(r)
    # Preserve text blocks not represented in classical regions. Do not silently drop evidence.
    for x in native_blocks:
        if x["native_type"] != "text" or not x["text"]: continue
        if any(intersection_ratio(x["bbox"],r["bbox_px"]) >= .28 for r in regions):
            continue
        b=x["bbox"]
        r={"id":f"R{len(regions)+1:03d}","layout_type":"text_block", "bbox_px":b,
           "bbox_normalized":[round(b[0]/w,5),round(b[1]/h,5),round(b[2]/w,5),round(b[3]/h,5)],
           "confidence":1.0, "source":"pdf_native_uncovered", "native_text":x["text"][:2500],
           "page_height":h,"bbox":b}
        classify_region(r,x["text"]);r.pop("page_height");r.pop("bbox")
        regions.append(r)
    regions.sort(key=lambda r:(round(r["bbox_px"][1]/30),r["bbox_px"][0]))
    return regions


def extract_fields(native_blocks, expected_ref, expected_date, page_index):
    candidates=[]
    for block in native_blocks:
        raw=block["text"]
        if not raw: continue
        txt=norm(raw)
        for hit in DATE_RE.finditer(txt):
            val=canonical_date(hit)
            is_date_label=any(norm(w).casefold() in txt.casefold() for w in ROLE_WORDS["date"])
            candidates.append({"type":"issue_date_candidate" if is_date_label else "date_mentioned",
                               "value":val,"page":page_index,"bbox_px":block["bbox"],
                               "source":"native_pdf_text", "match_expected":val==expected_date,
                               "basis":"date with header label" if is_date_label else "date text found (role unverified)"})
        for hit in FULL_REF_RE.finditer(txt):
            val=canonical_ref(hit.group(0))
            candidates.append({"type":"letter_reference_candidate","value":val,
                               "page":page_index,"bbox_px":block["bbox"],
                               "source":"native_pdf_text","match_expected":val==expected_ref,
                               "basis":"full reference pattern"})
        if expected_ref:
            serial=expected_ref.split("/")[-1]
            if re.search(r"(?<!\d)" + re.escape(serial) + r"(?!\d)",txt) and not any(c.get("value")==expected_ref for c in candidates):
                candidates.append({"type":"serial_candidate", "value":serial,"page":page_index,
                                   "bbox_px":block["bbox"],"source":"native_pdf_text",
                                   "match_expected":False,"basis":"serial alone is not authoritative"})
    # block-level dedup while preserving distinct source locations
    dedup=[];seen=set()
    for c in candidates:
        key=(c["type"],c["value"],tuple(c["bbox_px"]))
        if key not in seen:
            seen.add(key);dedup.append(c)
    return dedup


def text_font():
    for path in ["C:/Windows/Fonts/arial.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if Path(path).exists():
            return ImageFont.truetype(path,15)
    return ImageFont.load_default()


def overlay(rgb, regions, fields, destination):
    im=Image.fromarray(rgb)
    draw=ImageDraw.Draw(im,"RGBA")
    font=text_font()
    for r in regions:
        b=r["bbox_px"]; typ=r["suggested_layout_type"]
        color=COLORS.get(typ,"#52778c")
        draw.rectangle(tuple(b),outline=color,width=3)
        draw.text((b[0], max(0,b[1]-18)),f"{r['id']} {typ}",font=font,fill=color,stroke_width=1,stroke_fill="white")
    for f in fields:
        b=f["bbox_px"]
        color="#19ab69" if f["match_expected"] else "#e3a321"
        draw.rectangle(tuple(b),outline=color,width=4)
        draw.text((b[0],max(0,b[1]-36)),f["type"]+": "+f["value"],font=font,fill=color,stroke_width=1,stroke_fill="black")
    im.save(destination)


def run(pdf_path:Path,out_dir:Path, expected_ref=None, expected_date=None, dpi=170, max_pages=8):
    if not pdf_path.is_file():raise FileNotFoundError(pdf_path)
    out_dir.mkdir(parents=True,exist_ok=True)
    expect_ref=canonical_ref(expected_ref or "")
    expect_date=canonical_date(DATE_RE.search(norm(expected_date))) if expected_date and DATE_RE.search(norm(expected_date)) else None
    sha=hashlib.sha256()
    with pdf_path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            sha.update(chunk)
    result={"schema":SCHEMA,"source_file":str(pdf_path.resolve()),"sha256":sha.hexdigest(),
            "engine":"Adaptive Document Annotator v0.6 DetectionEngine (unaltered)",
            "semantic_proposal_method":"native-PDF text pattern+label hints (unreviewed)",
            "document_family":"ENGINEERING_CORRESPONDENCE_OUTGOING",
            "expected_reference":expect_ref,"expected_date":expect_date,"pages":[],
            "automated_field_verification":"NOT_VERIFIED",
            "note":"Source evidence required: proposed fields are not automatic approval or correction."}
    engine=DetectionEngine()
    with pymupdf.open(str(pdf_path)) as doc:
        result["pdf_page_count"]=len(doc)
        for pi in range(min(len(doc),max_pages)):
            page=doc[pi]
            pix=page.get_pixmap(dpi=dpi, alpha=False)
            rgb=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width,pix.n)
            if rgb.shape[2]==4:rgb=rgb[:,:,:3]
            # Existing trained detector: CV segmentation, rule/table proposals.
            engine_result=engine.run(rgb)
            blocks=pdf_native_blocks(page,pix.width/page.rect.width,pix.height/page.rect.height)
            regions=build_regions(engine_result,blocks,pix.height,pix.width)
            fields=extract_fields(blocks,expect_ref,expect_date,pi+1)
            img_path=out_dir/f"page_{pi+1:02d}_labeled.png"
            overlay(rgb,regions,fields,img_path)
            result["pages"].append({"page":pi+1,"size_px":[pix.width,pix.height],
                                    "regions":regions,"field_candidates":fields,
                                    "native_text_blocks":len([b for b in blocks if b['native_type']=='text']),
                                    "detector_statistics":engine_result["stats"],
                                    "image":img_path.name})
            print(f"[PAGE {pi+1}] regions={len(regions)} native_blocks={len(blocks)} field_candidates={len(fields)} -> {img_path.name}")
    all_fields=[f for p in result["pages"] for f in p["field_candidates"]]
    result["summary"]={"pages_processed":len(result["pages"]),
                       "total_regions":sum(len(p["regions"]) for p in result["pages"]),
                       "field_candidates":len(all_fields),
                       "dates":sorted(set(f["value"] for f in all_fields if f["type"] in ("issue_date_candidate", "date_mentioned"))),
                       "full_reference_found":bool(expect_ref and any(f["type"]=="letter_reference_candidate" and f["value"]==expect_ref for f in all_fields)),
                       "expected_date_found":bool(expect_date and any("date" in f["type"] and f["value"]==expect_date for f in all_fields)),
                       "role_counts":dict(Counter(k for p in result["pages"] for r in p["regions"] for k in r["role_candidates"]))}
    if result["summary"]["full_reference_found"] and result["summary"]["expected_date_found"]:
        result["evidence_status"]="MATCHING_TEXT_CANDIDATES_FIELD_REVIEW_REQUIRED"
    elif not all_fields:
        result["evidence_status"]="LAYOUT_ONLY_OCR_OR_MANUAL_REVIEW_REQUIRED"
    else:
        result["evidence_status"]="EVIDENCE_INCOMPLETE_FIELD_REVIEW_REQUIRED"
    out=out_dir/"layout_proposals.json"
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print("[EVIDENCE]",result["evidence_status"])
    print("[DATES]",", ".join(result["summary"]["dates"]) or "none")
    print("[REF]", "found" if result["summary"]["full_reference_found"] else "not verified")
    print("[JSON]",out)
    return result


def main():
    parser=argparse.ArgumentParser(description="Run the original Adaptive Document Annotator v0.6 detection engine on a PDF, export labeled page overlays and proposed correspondence fields.")
    parser.add_argument("--pdf",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--reference",default="1404/ES/S/3003")
    parser.add_argument("--expected-date",default="1404/07/19")
    parser.add_argument("--dpi",type=int,default=170)
    parser.add_argument("--max-pages",type=int,default=8)
    args=parser.parse_args()
    run(args.pdf,args.out,args.reference,args.expected_date,args.dpi,args.max_pages)

if __name__=="__main__":main()
