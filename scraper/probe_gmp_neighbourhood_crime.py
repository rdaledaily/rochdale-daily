#!/usr/bin/env python3
"""Probe official GMP neighbourhood-crime workbook and capture its public schema.

This report is for build-time validation only. It must not be used to assign
counts to individual postcodes until the workbook's geography is verified.
Uses Python's zip/XML readers, avoiding spreadsheet office software.
"""
from __future__ import annotations
import io
import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

PAGE = ("https://www.gmp.police.uk/police-forces/greater-manchester-police/"
        "areas/greater-manchester-force-content/sd/stats-and-data/neighbourhood-crime/")
KNOWN = ("https://www.gmp.police.uk/SysSiteAssets/media/downloads/greater-manchester/"
         "stats-and-data/neighbourhood-crime/"
         "gmp-neighbourhood-crime-data---greater-manchester-police---aug-19-to-sep-26.xlsx")
OLDER = ("https://www.gmp.police.uk/SysSiteAssets/media/downloads/greater-manchester/"
         "stats-and-data/neighbourhood-crime/nieghbourhood-crime-gmp-website---jun-26.xlsx")
OUT = Path("reports/gmp-neighbourhood-workbook-schema.json")
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}

def fetch(url: str, maxbytes=10000000) -> bytes:
    req=Request(url, headers={"User-Agent":"Mozilla/5.0 (compatible; RochdaleDailyResearch/1.0)",
                              "Accept":"text/html,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*"})
    with urlopen(req,timeout=26) as resp:
        chunks=[];size=0
        while True:
            part=resp.read(65536)
            if not part:break
            size+=len(part)
            if size>maxbytes:raise RuntimeError("File exceeds maximum allowed size")
            chunks.append(part)
        return b"".join(chunks)

def discover():
    candidates=[]
    try:
        source=fetch(PAGE,1300000).decode("utf-8","replace")
        for href in re.findall(r'href\s*=\s*["\\x27]([^"\\x27]+\.xlsx(?:\?[^"\\x27]*)?)["\\x27]',source,re.I):
            if "neighbourhood" in href.lower() or "nieghbourhood" in href.lower():
                candidates.append(urljoin(PAGE,unescape(href)))
    except Exception as ex:print("PAGE DISCOVERY:",str(ex)[:160],file=sys.stderr)
    # Current exact link was copied from the official page in a normal
    # browser on 13 October 2026. The previous scraper guessed the wrong name.
    candidates.extend([KNOWN, OLDER])
    # We use the first CURRENT page link in source order, otherwise newest
    # filename candidate. Stale files are labelled by their actual content.
    seen=set()
    for url in candidates:
        if url in seen:continue
        seen.add(url)
        try:
            b=fetch(url)
            if b[:2]!=b"PK":continue
            with zipfile.ZipFile(io.BytesIO(b)) as z:
                if "[Content_Types].xml" not in z.namelist():continue
            return url,b
        except Exception as e: print("DOWNLOAD:",url.rsplit("/",1)[-1],str(e)[:100],file=sys.stderr)
    raise RuntimeError("GMP workbook could not be downloaded from the official site")

def shared_strings(z):
    name="xl/sharedStrings.xml"
    if name not in z.namelist():return []
    values=[]
    with z.open(name) as content:
        for event,node in ET.iterparse(content,events=("end",)):
            if node.tag.endswith("}si"):
                values.append("".join(t.text or "" for t in node.iter() if t.tag.endswith("}t")))
                node.clear()
    return values

def cell_value(c,shared):
    tag=c.attrib.get("t","")
    if tag=="inlineStr":
        return "".join(n.text or "" for n in c.iter() if n.tag.endswith("}t"))[:220]
    v=c.find("m:v",NS)
    if v is None:return ""
    raw=v.text or ""
    if tag=="s":
        try:return shared[int(raw)][:220]
        except (ValueError,IndexError):return ""
    if tag=="b":return raw=="1"
    if re.fullmatch(r"-?\d+(?:\.\d+)?",raw):
        return int(raw) if "." not in raw else float(raw)
    return raw[:220]

def inspect(content):
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        shared=shared_strings(z)
        book=ET.fromstring(z.read("xl/workbook.xml"))
        rel=ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        mapping={}
        for item in rel:
            if item.tag.endswith("}Relationship"):mapping[item.attrib.get("Id")]=item.attrib.get("Target")
        results=[]
        for sh in book.findall("m:sheets/m:sheet",NS):
            id_=sh.attrib.get("{"+NS["r"]+"}id")
            target=mapping.get(id_,"")
            if not target:continue
            if target.startswith("/"):target=target.lstrip("/")
            elif not target.startswith("xl/"):target="xl/"+target
            if target not in z.namelist():continue
            head=[]
            with z.open(target) as stream:
                for _,node in ET.iterparse(stream,events=("end",)):
                    if not node.tag.endswith("}row"):continue
                    if len(head)<14:
                        record={}
                        for cell in node.findall("m:c",NS)[:30]:
                            record[cell.attrib.get("r","")]=cell_value(cell,shared)
                        head.append(record)
                    node.clear()
                    if len(head)>=14:break
            results.append({"sheet":sh.attrib.get("name"),"head":head})
        return {"sharedStringCount":len(shared),"sheets":results}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--file",type=Path,help="An officially downloaded GMP XLSX saved locally. This route works even when automated access to the GMP site is challenged.")
    opts=parser.parse_args()
    now=datetime.now(timezone.utc).isoformat()
    try:
        if opts.file:
            name=opts.file
            if not name.is_file() or name.suffix.lower()!=".xlsx" or name.stat().st_size>10000000:
                raise RuntimeError("Supply a local .xlsx from the GMP site, not larger than 10 MB")
            content=name.read_bytes()
            url=KNOWN
            acquisition="browser_download_import"
        else:
            url,content=discover()
            acquisition="automated_official_download"
        if not content.startswith(b"PK"):
            raise RuntimeError("Downloaded file is not an XLSX ZIP")
        info=inspect(content)
        result={"status":"schema_available","sourcePage":PAGE,"workbookUrl":url,
                "acquisition":acquisition,"downloadBytes":len(content),
                "sha256":hashlib.sha256(content).hexdigest(),
                "checkedAt":now, **info,
                "warning":"Schema validation only. Neighbourhood crime is a limited subset of offence types. Do not attach counts to a postcode unless the worksheet's precise geography, date and category are verified."}
        print("GMP workbook schema inspected:",url,len(content),"bytes",acquisition)
        for s in info["sheets"]:
            print("SHEET",s["sheet"],"ROWS",str(s["head"][:4])[:1200])
    except Exception as exc:
        result={"status":"source_access_blocked" if not opts.file else "import_failed",
                "checkedAt":now,"sourcePage":PAGE,"currentOfficialWorkbookUrl":KNOWN,
                "error":"GMP's Cloudflare may challenge automated visitors; the newsroom can still inspect a browser-downloaded workbook using --file.",
                "detail":str(exc)[:180],
                "nextStep":"Download the linked XLSX in a normal browser and run this inspector with --file path/to/workbook.xlsx. Never invent neighbourhood crime figures from an unavailable feed."}
        print("WARNING: GMP workbook unavailable:",str(exc)[:180])
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\\n",encoding="utf-8")
if __name__=="__main__":main()
