"""Index reconstitution press releases from NSE Indices (niftyindices.com)
— the actual add/drop announcements with announce AND effective dates,
1998→present. Queued by v27's post-mortem: the honest power source for
any index-flow re-test (v27's synthetic detection gave 9-17 events;
these are the real thing).

    python -m ingest.reconstitution list   # scrape the 1,400+ item index
    python -m ingest.reconstitution pdfs   # download the ~1,100 relevant
Parse phase comes after a format review of the PDFs (the v25 pattern).
"""
import html as hu
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

import config

DIR = config.DATA_DIR / "reconstitution"
PDF_DIR = DIR / "pdfs"
BASE = "https://www.niftyindices.com"
H = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
KW = re.compile(r"replac|reconstit|exclusion|inclusion|change", re.I)


def scrape_list() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    page = requests.get(BASE + "/press-release", headers=H, timeout=60).text
    items = re.findall(
        r'data-date="([^"]+)"[^>]*>\s*<p>[^<]*</p>\s*'
        r'<a href=[\'"]([^\'"]+\.pdf)[\'"][^>]*>(.*?)</a>', page, re.S)
    rows = [{"announce": pd.to_datetime(d, format="%b %d, %Y"),
             "url": u if u.startswith("http") else BASE + u,
             "title": re.sub(r"\s+", " ", hu.unescape(t)).strip()}
            for d, u, t in items]
    df = pd.DataFrame(rows).drop_duplicates("url")
    df["relevant"] = df["title"].str.contains(KW)
    df.to_parquet(DIR / "index.parquet", index=False)
    print(f"{len(df)} press releases indexed "
          f"({df['relevant'].sum()} reconstitution-flavored) "
          f"{df['announce'].min().date()} → {df['announce'].max().date()}")


def fetch_pdfs() -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(DIR / "index.parquet")
    todo = df[df["relevant"]]
    got = 0
    for _, r in todo.iterrows():
        out = PDF_DIR / Path(r["url"]).name
        if out.exists():
            continue                              # restartable
        try:
            resp = requests.get(r["url"], headers=H, timeout=60)
            if resp.status_code == 200 and resp.content[:4] == b"%PDF":
                out.write_bytes(resp.content)
                got += 1
            else:
                print(f"skip {out.name}: {resp.status_code}", flush=True)
        except Exception as e:
            print(f"{out.name}: {e}", flush=True)
        time.sleep(0.7)
        if got and got % 100 == 0:
            print(f"{got} PDFs fetched", flush=True)
    print(f"pdf fetch done: {got} new, "
          f"{len(list(PDF_DIR.glob('*.pdf')))} total on disk")


SECTION = re.compile(r"^\s*\d+\)\s*((?:NIFTY|Nifty)[^\n]{0,60})\s*$",
                     re.M)
ROW = re.compile(r"^\s*\d+\s+(.+?)\s+([A-Z][A-Z0-9&\-]{1,15})\s*$", re.M)
EXCL = re.compile(r"being\s+excluded", re.I)
INCL = re.compile(r"being\s+included", re.I)
WEF = re.compile(r"(?:w\.?e\.?f\.?|effective\s+from)\s*:?\s*"
                 r"([A-Z][a-z]+ \d{1,2},? \d{4})")


def _index_name(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip().rstrip(".").lower()


def parse_pdf(path: Path, announce, title) -> list[dict]:
    from pypdf import PdfReader
    txt = "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)
    m = WEF.search(title) or WEF.search(txt[:3000])
    effective = pd.to_datetime(m.group(1).replace(",", ""),
                               format="%B %d %Y", errors="coerce") \
        if m else pd.NaT
    rows = []
    sections = list(SECTION.finditer(txt))
    for i, sec in enumerate(sections):
        idx = _index_name(sec.group(1))
        seg = txt[sec.end():sections[i + 1].start()
                  if i + 1 < len(sections) else len(txt)]
        # split the segment at excluded/included markers; rows after each
        marks = sorted([(m.start(), "drop") for m in EXCL.finditer(seg)]
                       + [(m.start(), "add") for m in INCL.finditer(seg)])
        for j, (pos, action) in enumerate(marks):
            chunk = seg[pos:marks[j + 1][0] if j + 1 < len(marks)
                        else len(seg)]
            for rm in ROW.finditer(chunk):
                name, sym = rm.group(1).strip(), rm.group(2)
                if sym in ("NIFTY", "INDEX") or len(name) < 3:
                    continue
                rows.append({"announce": announce, "effective": effective,
                             "index": idx, "action": action,
                             "symbol": sym, "company": name,
                             "pdf": path.name})
    return rows


def parse_all() -> None:
    idx = pd.read_parquet(DIR / "index.parquet").set_index(
        pd.read_parquet(DIR / "index.parquet")["url"]
        .map(lambda u: Path(u).name))
    rows, bad = [], 0
    for f in sorted(PDF_DIR.glob("*.pdf")):
        meta = idx.loc[f.name] if f.name in idx.index else None
        if meta is None:
            continue
        if isinstance(meta, pd.DataFrame):
            meta = meta.iloc[0]
        try:
            rows.extend(parse_pdf(f, meta["announce"], meta["title"]))
        except Exception:
            bad += 1
    ev = pd.DataFrame(rows).drop_duplicates(
        ["announce", "index", "action", "symbol"])
    ev.to_parquet(DIR / "events.parquet", index=False)
    print(f"parsed events: {len(ev)} rows from "
          f"{ev['pdf'].nunique()} PDFs ({bad} unreadable)")
    print(ev["action"].value_counts().to_dict())
    core = ev[ev["index"].str.contains(
        r"^nifty ?50$|^nifty next ?50$|^nifty ?100$|^nifty ?200$"
        r"|^nifty ?500$|midcap ?150", regex=True)]
    print(f"core-index events: {len(core)}")
    print(core.assign(y=core["announce"].dt.year)
          .groupby(["y"])["symbol"].count().to_string())


if __name__ == "__main__":
    {"list": scrape_list, "pdfs": fetch_pdfs,
     "parse": parse_all}[sys.argv[1]]()
