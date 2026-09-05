"""Rating-action direction extraction (v22.1 unblock): the direction
lives in PDF attachments; this pipeline fetches URLs, downloads PDFs for
the liquid universe, and extracts downgrade/upgrade/reaffirm from text.

    python -m ingest.ratings urls   # phase 1: ~549 weekly API scans
    python -m ingest.ratings pdfs   # phase 2+3: download + parse
"""
import io
import re
import sys
import time
from datetime import date, timedelta

import pandas as pd

import config
from ingest import nse

DIR = config.DATA_DIR / "ratings"
API = ("https://www.nseindia.com/api/corporate-announcements"
       "?index=equities&from_date={frm}&to_date={to}")


def phase_urls():
    DIR.mkdir(parents=True, exist_ok=True)
    out = DIR / "urls.parquet"
    have = pd.read_parquet(out) if out.exists() else pd.DataFrame()
    done_weeks = set(have["week"]) if len(have) else set()
    frames = [have] if len(have) else []
    d = date(2016, 1, 4)
    while d <= date.today():
        wk = d.isoformat()
        if wk not in done_weeks:
            try:
                r = nse.get(API.format(frm=d.strftime("%d-%m-%Y"),
                                       to=(d + timedelta(days=6)).strftime("%d-%m-%Y")),
                            timeout=90)
                rows = r.json()
                rows = rows if isinstance(rows, list) else rows.get("data", [])
                df = pd.DataFrame(rows)
                if len(df):
                    sym = "symbol" if "symbol" in df.columns else "sm_symbol"
                    cr = df[df["desc"].astype(str).str.lower()
                            .str.contains("credit rating", na=False)]
                    if len(cr):
                        keep = pd.DataFrame({
                            "symbol": cr[sym].astype(str).str.strip(),
                            "an_dt": cr["an_dt"],
                            "pdf": cr.get("attchmntFile", "")})
                        keep["week"] = wk
                        frames.append(keep)
                time.sleep(1.0)
            except Exception as e:
                print(f"{wk}: {e}")
        d += timedelta(days=7)
    all_ = pd.concat(frames, ignore_index=True)
    all_.to_parquet(out, index=False)
    print(f"urls: {len(all_)} rating announcements")


DOWN = re.compile(r"downgrad|revised.{0,30}from.{1,25}to|lowered", re.I)
UP = re.compile(r"upgrad|raised", re.I)
REAF = re.compile(r"reaffirm|reiterated|maintained", re.I)


def phase_pdfs():
    from pypdf import PdfReader
    from ingest.financials import _liquid_universe
    urls = pd.read_parquet(DIR / "urls.parquet")
    liquid = _liquid_universe()
    urls = urls[urls["symbol"].isin(liquid)
                & urls["pdf"].astype(str).str.startswith("http")]
    out = DIR / "parsed.parquet"
    have = pd.read_parquet(out) if out.exists() else pd.DataFrame()
    done = set(have["pdf"]) if len(have) else set()
    rows = list(have.to_dict("records")) if len(have) else []
    n = 0
    for _, r in urls.iterrows():
        if r["pdf"] in done:
            continue
        try:
            resp = nse.get(r["pdf"], timeout=45)
            reader = PdfReader(io.BytesIO(resp.content))
            txt = " ".join((pg.extract_text() or "")
                           for pg in reader.pages[:3])[:6000]
            direction = ("downgrade" if DOWN.search(txt) and not UP.search(txt)
                         else "upgrade" if UP.search(txt) and not DOWN.search(txt)
                         else "reaffirm" if REAF.search(txt) else "unclear")
        except Exception:
            direction = "fetch_fail"
        rows.append({"symbol": r["symbol"], "an_dt": r["an_dt"],
                     "pdf": r["pdf"], "direction": direction})
        n += 1
        if n % 300 == 0:
            pd.DataFrame(rows).to_parquet(out, index=False)
            print(f"{n} parsed")
        time.sleep(0.6)
    pd.DataFrame(rows).to_parquet(out, index=False)
    d = pd.DataFrame(rows)
    print("directions:", d["direction"].value_counts().to_dict())


if __name__ == "__main__":
    {"urls": phase_urls, "pdfs": phase_pdfs}[sys.argv[1]]()
