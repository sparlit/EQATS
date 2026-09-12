import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""v22.1 certification: PDF-confirmed rating directions (PROTOCOL_V21 v22
section). Downgrades must be < -2% mean AND median vs both nulls, BOTH
windows; upgrades/reaffirms serve as direction controls.

    python -m backtest.ratings_cert
"""
from pathlib import Path

import pandas as pd
from backtest import features, monthly
from backtest.events17 import report as _rep
from backtest.events17 import run_kind
from ingest import etf_list, renames

import config


def main():
    p = features._panel(None, None)
    close, open_ = p["close"], p["open"]
    etfs = etf_list.symbols()
    keep = [c for c in close.columns if c not in etfs or c == "NIFTYBEES"]
    close, open_ = close[keep], open_[keep]
    liquid = p["turnover_lacs"].rolling(20).median() >= 500
    args = (close, open_, close["NIFTYBEES"], open_["NIFTYBEES"], liquid)

    d = pd.read_parquet(config.DATA_DIR / "ratings" / "parsed.parquet")
    d["symbol"] = renames.canonical(d["symbol"])
    d["an_dt"] = pd.to_datetime(d["an_dt"], errors="coerce")
    d = d.dropna(subset=["an_dt"])

    ann = pd.concat(map(pd.read_parquet, Path(config.DATA_DIR / "ann_full").glob("*.parquet")), ignore_index=True)
    ann["symbol"] = renames.canonical(ann["symbol"])
    ann["an_dt"] = pd.to_datetime(ann["an_dt"], errors="coerce")
    base_pool = ann.dropna(subset=["an_dt"]).sample(n=60000, random_state=7)

    for label, lo, hi in (("IS 2023-26", "2023-01-01", "2027-01-01"), ("OOS 2018-22", "2018-01-01", "2023-01-01")):
        print(f"=== {label} ===")

        def W(x):
            return x[(x["an_dt"] >= lo) & (x["an_dt"] < hi)]

        nb = run_kind(W(base_pool), *args, gap_days=0)
        nm = nb["excess"].mean()
        print(f"  random-announcement null: mean={nm:+.2f} median={nb['excess'].median():+.2f} (n={len(nb)})")
        for kind in ("downgrade", "upgrade", "reaffirm"):
            _rep(f"{kind} 63d", run_kind(W(d[d["direction"] == kind]), *args, gap_days=63), nm)
        _rep("downgrade 126d", run_kind(W(d[d["direction"] == "downgrade"]), *args, hold=126, gap_days=63), nm)


if __name__ == "__main__":
    main()
