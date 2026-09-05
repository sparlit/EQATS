"""US insider purchases (SEC Form 4 via openinsider) — v9 raw material.

    python -m us.insiders          # backfill 2016→now into us/data/insiders/

Monthly chunks; each page capped at 1000 rows so months are re-chunked
into halves when they hit the cap. Filing timestamp preserved — that is
the point-in-time key, never the trade date.
"""
import io
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

DATA = Path(__file__).resolve().parent / "data" / "insiders"
UA = {"User-Agent": "Mozilla/5.0 (research; contact via github deshpanda)"}

URL = ("http://openinsider.com/screener?s=&o=&pl=&ph=&ll=&lh=&fd=-1"
       "&fdr={frm}+-+{to}&td=0&tdr=&fdlyl=&fdlyh=&daysago="
       "&xp=1&vl=25&vh=&ocl=&och=&sic1=-1&sicl=100&sich=9999"
       "&grp=0&nfl=&nfh=&nil=&nih=&nol=&noh=&v2l=&v2h=&oc2l=&oc2h="
       "&sortcol=0&cnt=1000&page=1")

COLS = {"filing_date": "filing", "trade_date": "trade", "ticker": "ticker",
        "company_name": "company", "insider_name": "insider",
        "title": "title", "price": "price", "qty": "qty", "value": "value"}


def fetch_range(frm: date, to: date) -> pd.DataFrame | None:
    u = URL.format(frm=frm.strftime("%m%%2F%d%%2F%Y"),
                   to=to.strftime("%m%%2F%d%%2F%Y"))
    r = requests.get(u, headers=UA, timeout=60)
    r.raise_for_status()
    try:
        tables = pd.read_html(io.StringIO(r.text))
    except ValueError:
        return None
    t = max(tables, key=len)
    if len(t) < 2 or "Ticker" not in "".join(map(str, t.columns)):
        return None
    t.columns = [str(c).strip().lower().replace(" ", "_").replace("\xa0", "_")
                 for c in t.columns]
    t = t.rename(columns={c: COLS[k] for c in t.columns
                          for k in COLS if k in c})
    t = t[[c for c in ("filing", "trade", "ticker", "company", "insider",
                       "title", "price", "qty", "value") if c in t.columns]]
    for c in ("price", "qty", "value"):
        t[c] = pd.to_numeric(t[c].astype(str)
                             .str.replace(r"[$,+]", "", regex=True),
                             errors="coerce")
    t["filing"] = pd.to_datetime(t["filing"], errors="coerce")
    t["trade"] = pd.to_datetime(t["trade"], errors="coerce")
    return t.dropna(subset=["filing", "ticker"])


def fetch_month(y: int, m: int) -> pd.DataFrame | None:
    start = date(y, m, 1)
    end = (date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)) \
        - timedelta(days=1)
    df = fetch_range(start, end)
    if df is not None and len(df) >= 1000:      # hit the cap: split in half
        mid = start + (end - start) / 2
        a = fetch_range(start, mid)
        time.sleep(1)
        b = fetch_range(mid + timedelta(days=1), end)
        df = pd.concat([x for x in (a, b) if x is not None],
                       ignore_index=True)
    return df


def load_all() -> pd.DataFrame:
    files = sorted(DATA.glob("*.parquet"))
    if not files:
        raise SystemExit("No insider data. Run: python -m us.insiders")
    return pd.concat(map(pd.read_parquet, files), ignore_index=True)


if __name__ == "__main__":
    DATA.mkdir(parents=True, exist_ok=True)
    today, got = date.today(), 0
    for y in range(2016, today.year + 1):
        for m in range(1, 13):
            if (y, m) > (today.year, today.month):
                break
            out = DATA / f"{y}-{m:02d}.parquet"
            if out.exists():
                continue
            try:
                df = fetch_month(y, m)
                if df is not None and len(df):
                    df.to_parquet(out, index=False)
                    got += 1
                time.sleep(1.2)
            except Exception as e:
                print(f"{y}-{m:02d}: {e} — continuing", file=sys.stderr)
        print(f"{y} done ({got} months so far)")
    print(f"insider backfill complete: {got} new months")
