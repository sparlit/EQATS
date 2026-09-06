"""Buyback tender-offer event calendar.

Why this dataset exists: SEBI reserves 15% of every tender-offer buyback
for "small shareholders" (holdings <= Rs 2,00,000 at record date), and
since 2025 all buybacks must use the tender route. The Oct-2024
deemed-dividend tax that had killed the trade was repealed by Finance
Act 2026 (w.e.f. 2026-04-01), so the event class is live again.

Three phases, honest about what each can deliver:
  calendar  — symbol + RECORD date + subject, from the corporate-actions
              API (works 2016+; verified 75 buyback rows 2024-2026)
  announce  — match each record date back to its ANNOUNCEMENT in the
              existing 1.26M-row ann_full store (gives the announce date
              and often the tender price/size in the snippet text)
  GAP (not built): realized ACCEPTANCE RATIOS live in post-offer "basis
              of acceptance" filings as PDF attachments. Without them a
              tender return cannot be computed exactly — only a
              BREAK-EVEN acceptance ratio can. Any protocol must say so.

    python -m ingest.buybacks calendar
    python -m ingest.buybacks announce
"""
import sys
import time

import pandas as pd

import config
from ingest import nse, renames

DIR = config.DATA_DIR / "buybacks"
CA_URL = ("https://www.nseindia.com/api/corporates-corporateActions"
          "?index=equities&from_date={frm}&to_date={to}")
WARMUP = ("https://www.nseindia.com/companies-listing/"
          "corporate-filings-actions")


def calendar() -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    s = nse.session()
    s.get(WARMUP, timeout=15)
    frames = []
    for yr in range(2016, 2027):
        try:
            r = nse.get(CA_URL.format(frm=f"01-01-{yr}", to=f"31-12-{yr}"),
                        timeout=120)
            d = r.json()
            d = d if isinstance(d, list) else d.get("data", [])
            if d:
                frames.append(pd.DataFrame(d))
            print(f"  {yr}: {len(d)} CA rows", flush=True)
        except Exception as e:
            print(f"  {yr}: {e}", flush=True)
        time.sleep(1)
    ca = pd.concat(frames, ignore_index=True)
    bb = ca[ca["subject"].str.contains("buy ?back", case=False, na=False)].copy()
    bb["symbol"] = renames.canonical(bb["symbol"].astype(str).str.strip())
    bb["record_date"] = pd.to_datetime(bb["exDate"], format="%d-%b-%Y",
                                       errors="coerce")
    bb = (bb.dropna(subset=["record_date"])
            .sort_values("record_date")
            .drop_duplicates(["symbol", "record_date"]))
    keep = ["symbol", "comp", "record_date", "subject", "isin"]
    bb[[c for c in keep if c in bb.columns]].to_parquet(
        DIR / "calendar.parquet", index=False)
    print(f"buyback calendar: {len(bb)} events "
          f"{bb['record_date'].min().date()} → {bb['record_date'].max().date()}")
    print(bb.groupby(bb["record_date"].dt.year).size().to_string())


def announce() -> None:
    """Match record dates to announcements in the existing ann_full store."""
    from pathlib import Path
    cal = pd.read_parquet(DIR / "calendar.parquet")
    ann = pd.concat(map(pd.read_parquet,
                        Path(config.DATA_DIR / "ann_full").glob("*.parquet")),
                    ignore_index=True)
    ann["an_dt"] = pd.to_datetime(ann["an_dt"], errors="coerce")
    ann["symbol"] = renames.canonical(ann["symbol"].astype(str))
    txt = (ann["desc"].astype(str) + " " + ann["snippet"].astype(str)).str.lower()
    bb = ann[txt.str.contains("buy ?back|buy-back", regex=True, na=False)].copy()
    rows = []
    for _, e in cal.iterrows():
        w = bb[(bb["symbol"] == e["symbol"])
               & (bb["an_dt"] <= e["record_date"])
               & (bb["an_dt"] >= e["record_date"] - pd.Timedelta(days=120))]
        if w.empty:
            rows.append({**e, "announce_dt": pd.NaT, "snippet": None})
            continue
        first = w.sort_values("an_dt").iloc[0]
        rows.append({**e, "announce_dt": first["an_dt"],
                     "snippet": str(first.get("snippet"))[:400]})
    out = pd.DataFrame(rows)
    out.to_parquet(DIR / "events.parquet", index=False)
    got = out["announce_dt"].notna().sum()
    print(f"buyback events: {len(out)} | with announcement matched: {got} "
          f"({100*got/len(out):.0f}%)")
    lag = (out["record_date"] - out["announce_dt"]).dt.days.dropna()
    print(f"announce→record lag days: median {lag.median():.0f} "
          f"p25 {lag.quantile(.25):.0f} p75 {lag.quantile(.75):.0f}")


if __name__ == "__main__":
    {"calendar": calendar, "announce": announce}[sys.argv[1]]()
