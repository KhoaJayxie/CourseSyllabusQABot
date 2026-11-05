"""Extract RAG chunks from Speech and Language Processing PDF."""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "Speech and Language Processing_Jurafsky.pdf"
OUT = ROOT / "data" / "processed" / "speech_language_processing.unified.chunks.jsonl"
SLUG = "speech-and-language-processing-jurafsky"

TOC_RE = re.compile(r"^(?:Contents|Table of Contents|Summary of Contents)\s*$", re.I)
CHAPTER_RE = re.compile(r"^(?:CHAPTER(?:\s+\d+)?\b|\d+\.\s+[A-Z])", re.I)
BODY_START_RE = re.compile(r"^CHAPTER\s*$", re.I)
REF_RE = re.compile(r"^(?:REFERENCES|References|BIBLIOGRAPHY)\s*$", re.I)
TABLE_CAPTION_RE = re.compile(r"^(?:Table|TABLE)\s+(\d+(?:\.\d+|[-.][A-Z0-9]+)*)\b[.:]?\s*(.*)$")
FIGURE_RE = re.compile(r"^(?:Figure|Fig\.)\s+\d+(?:\.\d+)*\b", re.I)
CODE_RE = re.compile(r"^(?:>>>|\.\.\.|\s{4,}(?:def |class |return |for |while |if |import |from )|(?:def|class)\s+\w+\s*\(|(?:import|from)\s+\w+)")
FOOTER_RE = re.compile(r"^(?:\d+\s+(?:CHAPTER|CONTENTS)\b|(?:CHAPTER\s+\d+|CONTENTS)\s+\d+|\d+)$", re.I)


def line_text(page: Any) -> list[str]:
    raw = unicodedata.normalize("NFC", page.extract_text(extraction_mode="layout") or "")
    result=[]
    for line in raw.replace("\r", "\n").split("\n"):
        text=re.sub(r"\s+", " ", line).strip()
        if text:
            result.append(text)
    return result


def join_lines(lines: list[dict[str, Any]]) -> str:
    out=""
    for row in lines:
        part=row["text"].strip()
        if not part: continue
        if not out: out=part
        elif out.endswith(("-", "‐", "‑")) and part[:1].islower(): out=out[:-1]+part
        else: out += " " + part
    return out


def sentence_end(text: str) -> bool:
    return bool(re.search(r"[.!?][\"'’”)]*$", text.strip()))


def record(chunk_id: str, kind: str, page_a: int, page_b: int, text: str, lines: list[dict[str, Any]], *, subtype=None, content=None, embed=None, inferred=False, status="ok", reasons=None, notes=None, relations=None, lang="en") -> dict[str, Any]:
    first=lines[0] if lines else None; last=lines[-1] if lines else None
    return {
        "chunk_id":chunk_id,"document_id":SLUG,"chunk_type":kind,"subtype":subtype,
        "page_start":page_a,"page_end":page_b,"page_inferred":inferred,
        "embed_text": embed if embed is not None else text,
        "content":content if content is not None else {"text":text},
        "relations":relations or {"parent_id":None,"related_table_ids":[],"depends_on":[],"step":None,"prev_id":None,"next_id":None},
        "provenance":{"source_line_ids":[f"{SLUG}:p{x['page']}:l{x['line']}" for x in lines],"line_start":first["line"] if first else None,"line_end":last["line"] if last else None},
        "quality":{"status":status,"review_reasons":reasons or [],"notes":notes or []},"lang":lang,
    }


def main() -> None:
    sys.stdout.reconfigure(errors="backslashreplace")
    reader=PdfReader(str(PDF))
    pages=[line_text(p) for p in reader.pages]
    # Start from the first actual contents page, not cover/title/copyright/praise.
    toc_pages=[i for i,ls in enumerate(pages) if any(TOC_RE.match(x) for x in ls[:8])]
    if not toc_pages:
        raise RuntimeError("Could not identify the first Contents page; no output written")
    start=toc_pages[0]
    rows=[]
    for p in range(start,len(pages)):
        for n,text in enumerate(pages[p],1):
            if FOOTER_RE.match(text): continue
            rows.append({"page":p+1,"line":n,"text":text})

    # References sections recur per chapter: omit until next chapter heading.
    filtered=[]; in_refs=False
    for r in rows:
        text=r["text"]
        if REF_RE.match(text):
            in_refs=True
            continue
        if in_refs and CHAPTER_RE.match(text): in_refs=False
        if in_refs: continue
        # Suppress running headers and figure captions.
        if FIGURE_RE.match(text): continue
        if re.match(r"^(?:Speech and Language Processing|DRAFT|Jurafsky|Martin)\s*(?:\|.*)?$",text,re.I): continue
        filtered.append(r)

    # Detect text-of-contents through the first chapter opening; retain as non-embedded TOC.
    first_chapter_i=next((i for i,r in enumerate(filtered) if BODY_START_RE.match(r["text"])),None)
    if first_chapter_i is None: raise RuntimeError("Could not find the first body chapter heading")
    toc_end_page=filtered[first_chapter_i]["page"]
    toc_rows=[r for r in filtered if r["page"]<toc_end_page]
    body_rows=[r for r in filtered if r["page"]>=toc_end_page]
    chunks=[]
    # TOC records page-local, preserve source text and provenance.
    by_page={}
    for r in toc_rows: by_page.setdefault(r['page'],[]).append(r)
    for p,group in sorted(by_page.items()):
        text=join_lines(group)
        if text: chunks.append(record("", "toc",p,p,text,group,embed=""))

    # Identify table captions, preserve table as a structured chunk using conservative
    # row segmentation where PDF extraction has clear column separators/spacing.
    # Ambiguous tables are explicitly quality-marked and retained as raw cell text.
    captions=[]
    for idx,r in enumerate(body_rows):
        m=TABLE_CAPTION_RE.match(r['text'])
        if m: captions.append((idx,m.group(1),r['text']))
    table_ranges=[]
    for j,(idx,tid,caption) in enumerate(captions):
        if len(caption.strip()) < 18:
            caption=caption.rstrip(" .:")
            for continuation in body_rows[idx+1:idx+4]:
                caption += " " + continuation["text"]
                if len(caption) >= 28: break
        end=captions[j+1][0] if j+1<len(captions) else len(body_rows)
        # Captions often precede nearby prose; only take compact tabular rows until
        # the first clear paragraph or next section heading, with cautious review.
        stop=end
        for k in range(idx+1,end):
            t=body_rows[k]['text']
            if CHAPTER_RE.match(t) or re.match(r"^\d+(?:\.\d+)+\s+\S",t): stop=k; break
            if len(t)>240 and not re.search(r"\s{2,}|\t|\|",t): stop=k; break
        table_ranges.append((idx,stop,tid,caption))

    consumed=set(); table_chunks=[]
    for idx,stop,tid,caption in table_ranges:
        subset=body_rows[idx:stop]
        # Find table-like region after the caption; split row/cell strings conservatively.
        candidate=[]
        for r in subset[1:]:
            if re.search(r"\s{2,}|\t|\|",r['text']): candidate.append(r)
        cells=[]
        for r in candidate:
            parts=[x.strip() for x in re.split(r"\s{2,}|\t|\|",r['text']) if x.strip()]
            if len(parts)>1: cells.append(parts)
        if cells:
            width=max(map(len,cells)); columns=[f"Column {i+1}" for i in range(width)]
            table_rows_data=[]
            for parts in cells:
                vals=parts+[""]*(width-len(parts))
                table_rows_data.append(dict(zip(columns,vals)))
            confidence="heuristic row/cell boundaries from PDF layout; verify table structure"
            status="needs_review"
        else:
            columns=[]; table_rows_data=[]
            confidence="table caption detected but cell boundaries are not reliably extractable from PDF text"
            status="needs_review"
        p0,p1=subset[0]['page'],subset[-1]['page']
        slugid=tid.lower().replace('.','-')
        table_chunks.append(record(f"{SLUG}:{slugid}:p{p0}-p{p1}:full","table",p0,p1,"",subset,
            content={"table_id":f"Table {tid}","caption":caption,"columns":columns,"header_type":"column_headers" if columns else None,"rows":table_rows_data,"context":"","unit":None},
            embed=caption+ ("\n"+"\n".join("; ".join(f"{k}: {v}" for k,v in rr.items() if v) for rr in table_rows_data) if table_rows_data else ""),
            status=status,reasons=[confidence],notes=[]))
        consumed.update(range(idx,stop))

    # Build prose and code candidates in document order. Paragraph-sized chunks
    # split after sentence boundaries, never at an arbitrary character count.
    pending=[]
    def flush_pending():
        nonlocal pending
        if pending:
            text=join_lines(pending)
            if text: chunks.append(record("","text",pending[0]['page'],pending[-1]['page'],text,pending,embed=re.sub(r"\s+"," ",text).strip()))
            pending=[]
    for i,r in enumerate(body_rows):
        if i in consumed:
            flush_pending(); continue
        text=r['text']
        if TABLE_CAPTION_RE.match(text):
            flush_pending(); continue
        if CODE_RE.match(text):
            flush_pending()
            block=[r]; j=i+1
            while j<len(body_rows) and j not in consumed and (CODE_RE.match(body_rows[j]['text']) or body_rows[j]['text'].startswith((" ","\t"))):
                block.append(body_rows[j]); j+=1
            code="\n".join(x['text'] for x in block)
            symbol=f"code_p{r['page']}_l{r['line']}"
            chunks.append(record("","code",block[0]['page'],block[-1]['page'],code,block,subtype="script",
                content={"code":code,"language":"python","symbol":symbol,"description":"Code excerpt extracted from the source PDF; inspect for OCR/layout artifacts.","description_lang":"en"},
                embed="Code excerpt from Speech and Language Processing.",status="needs_review",reasons=["Automatically detected code; verify language and block boundaries."],lang="code"))
            continue
        pending.append(r)
        text_now=join_lines(pending)
        if len(text_now)>=1200 and sentence_end(text_now):
            flush_pending()
    flush_pending()
    chunks.extend(table_chunks)

    # Sort by actual page/line; tables sit at their caption position; preserve stable
    # text numbering gaps only where removals occur (IDs are assigned after ordering).
    def sort_key(c):
        prov=c['provenance']; return (c['page_start'],prov['line_start'] if prov['line_start'] is not None else 0, 0 if c['chunk_type']=='toc' else 1)
    chunks.sort(key=sort_key)
    counters={"text":0}
    for c in chunks:
        if c['chunk_type'] in ('text','toc'):
            counters['text']+=1;c['chunk_id']=f"{SLUG}:text:{counters['text']:04d}"
    code_count={}
    for c in chunks:
        if c['chunk_type']=='code':
            base=c['content']['symbol']; code_count[base]=code_count.get(base,0)+1
            c['chunk_id']=f"{SLUG}:code:{base}"
    for order,c in enumerate(chunks): c['order']=order
    for typ in {c['chunk_type'] for c in chunks}:
        members=[c for c in chunks if c['chunk_type']==typ]
        for i,c in enumerate(members):
            c['relations']['prev_id']=members[i-1]['chunk_id'] if i else None
            c['relations']['next_id']=members[i+1]['chunk_id'] if i+1<len(members) else None
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with OUT.open('w',encoding='utf-8',newline='\n') as f:
        for c in chunks:f.write(json.dumps(c,ensure_ascii=False)+'\n')
    print(f"PDF pages: {len(reader.pages)}; first contents PDF page: {start+1}; first chapter page: {toc_end_page}")
    print(f"Wrote {len(chunks)} chunks to {OUT}")
    print("NOTE: Table and code detection is heuristic; review-marked chunks must be checked.")

if __name__=='__main__': main()
