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


"""v11 Senate-trades event study (us/PROTOCOL_V11.md). Historical only:
the free dataset ends Dec 2020.

    python -m us.senate_study
"""
import json
from pathlib import Path

import pandas as pd
from us.event_study import load
from us.event_study import report as ev_report
from us.insider_study import study

DATA = Path(__file__).resolve().parent / "data"


def events(min_floor=15001):
    df = pd.DataFrame(json.load(open(DATA / "senate_tx.json")))
    df["td"] = pd.to_datetime(df["transaction_date"], errors="coerce")
    df = df[df["type"].str.contains("Purchase", na=False) & df["ticker"].str.match(r"^[A-Z]{1,5}$", na=False)]
    df["floor"] = df["amount"].str.extract(r"\$([\d,]+)")[0].str.replace(",", "").astype(float)
    df = df[df["floor"] >= min_floor].dropna(subset=["td"])
    # follower's entry: disclosure can take ~45 days (no timestamps in data)
    ev = pd.DataFrame({"ticker": df["ticker"], "date": df["td"] + pd.Timedelta(days=45)})
    ev = ev.sort_values("date")
    keep, last = [], {}
    for _, r in ev.iterrows():
        if (r["date"] - last.get(r["ticker"], pd.Timestamp("1900-01-01"))).days > 92:
            keep.append(r)
            last[r["ticker"]] = r["date"]
    return pd.DataFrame(keep)


def main():
    close, open_, _vol, member_at = load()
    for name, kw, hold in (
        ("baseline(>=15k,63d)", {}, 63),
        ("all_amounts", {"min_floor": 1001}, 63),
        ("hold_21", {}, 21),
        ("hold_126", {}, 126),
    ):
        ev = events(**kw)
        res = study(ev, close, open_, member_at, hold=hold)
        ev_report(name, res)
        if name.startswith("baseline"):
            for lab, lo, hi in (("  2016-18", "2016-01-01", "2019-01-01"), ("  2019-21", "2019-01-01", "2021-06-30")):
                ev_report(lab, res[(res["date"] >= lo) & (res["date"] < hi)])


if __name__ == "__main__":
    main()
