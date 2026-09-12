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


"""v40 (buyback tender-offer price path). Per PROTOCOL_V40.md.

    python -m backtest.buyback40
"""
import pandas as pd
from backtest import features
from backtest.events17 import run_kind
from backtest.pit_study import load_ann
from ingest import etf_list

import config


def stat(df):
    return (
        (f"n={len(df):4d} mean={df['excess'].mean():+6.2f} med={df['excess'].median():+6.2f}") if len(df) else "n=   0"
    )


def main():
    ev = pd.read_parquet(config.DATA_DIR / "buybacks" / "events.parquet")
    ev["record_date"] = pd.to_datetime(ev["record_date"])
    ev["announce_dt"] = pd.to_datetime(ev["announce_dt"])

    p = features._panel(None, None)
    close, open_ = p["close"], p["open"]
    etfs = etf_list.symbols()
    keep = [c for c in close.columns if c not in etfs or c == "NIFTYBEES"]
    close, open_ = close[keep], open_[keep]
    liquid = p["turnover_lacs"].rolling(20).median() >= 500
    args = (close, open_, close["NIFTYBEES"], open_["NIFTYBEES"], liquid)
    dates = close.index

    def hold_to_record(row):
        """trading days from entry to the record-date close"""
        i = dates.searchsorted(row["an_dt"], side="right")
        j = dates.searchsorted(row["record_date"], side="right") - 1
        return max(j - i, 1)

    # A1: signal = announcement; A2: signal = 5 sessions pre-record;
    # A3: signal = record date, fixed 21d hold
    a1 = ev.dropna(subset=["announce_dt"]).copy()
    a1["an_dt"] = a1["announce_dt"]
    a2 = ev.copy()
    a2["an_dt"] = a2["record_date"].map(lambda d: dates[max(dates.searchsorted(d, side="right") - 6, 0)])
    a3 = ev.copy()
    a3["an_dt"] = a3["record_date"]

    baseline = load_ann().sample(n=60000, random_state=7)
    for label, lo, hi in (
        ("IS 2023-26 (DECISION)", "2023-01-01", "2027-01-01"),
        ("OOS 2016-22 (single shot)", "2016-01-01", "2023-01-01"),
    ):
        print(f"\n=== {label} ===")

        def W(d):
            return d[(d["an_dt"] >= lo) & (d["an_dt"] < hi)]

        n21 = run_kind(W(baseline), *args, hold=21, gap_days=0)
        print(f"  random-null h21 : {stat(n21)}")
        # variable-hold cells: bucket by median hold for a single engine pass
        for name, frame in (("A1 announce→record", a1), ("A2 pre-record 5d", a2)):
            w = W(frame)
            if not len(w):
                print(f"  {name:<20} n=   0")
                continue
            hold = int(w.apply(hold_to_record, axis=1).median())
            r = run_kind(w, *args, hold=max(hold, 1), gap_days=126)
            nb = run_kind(W(baseline), *args, hold=max(hold, 1), gap_days=0)
            nm = nb["excess"].mean() if len(nb) else 0.0
            ok = (
                len(r) >= 30
                and len(nb)
                and r["excess"].mean() >= nm + 3
                and r["excess"].median() > nb["excess"].median()
            )
            print(f"  {name:<20} {stat(r)}  (hold {hold}d, null mean {nm:+.2f})  [{'PASS' if ok else 'fail'}]")
        r3 = run_kind(W(a3), *args, hold=21, gap_days=126)
        print(f"  A3 post-record 21d   {stat(r3)}  (descriptive; null mean {n21['excess'].mean():+.2f})")


if __name__ == "__main__":
    main()
