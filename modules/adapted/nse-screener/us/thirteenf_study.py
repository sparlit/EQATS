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


"""v10 13F guru-cloning event study (us/PROTOCOL_V10.md).

    python -m us.thirteenf_study
"""
import re
from pathlib import Path

import pandas as pd
import requests
from us.event_study import load
from us.event_study import report as ev_report
from us.insider_study import study

DATA = Path(__file__).resolve().parent / "data"
SUFFIX = re.compile(
    r"\b(INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LTD|LP|LLC|PLC|"
    r"CL|CLASS|COM|NEW|DEL|HLDG|HLDGS|HOLDING|HOLDINGS|GROUP|GRP|"
    r"THE|A|B|C|ADR|ADS|SHS|SH|ORD)\b|[^A-Z0-9 ]"
)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", SUFFIX.sub(" ", str(s).upper())).strip()


def ticker_map() -> dict:
    f = DATA / "company_tickers.json"
    if not f.exists():
        r = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": "research contact@deshpanda.dev"},
            timeout=60,
        )
        r.raise_for_status()
        f.write_bytes(r.content)
    j = pd.read_json(f, orient="index")
    j["n"] = j["title"].map(norm)
    # prefer the lowest-cik (primary) listing per normalized name
    j = j.sort_values("cik_str").drop_duplicates("n")
    return dict(zip(j["n"], j["ticker"], strict=False))


def new_positions(min_weight=0.01, consensus=1) -> pd.DataFrame:
    pos = pd.read_parquet(DATA / "13f_positions.parquet")
    pos["filed"] = pd.to_datetime(pos["filed"])
    events = []
    for fund, g in pos.groupby("fund"):
        filings = sorted(g["filed"].unique())
        prev_names = None
        for d in filings:
            cur = g[g["filed"] == d]
            total = cur["value"].sum()
            names = set(cur["issuer"])
            if prev_names is not None and total > 0:
                for _, r in cur.iterrows():
                    if r["issuer"] not in prev_names and r["value"] / total >= min_weight:
                        events.append({"fund": fund, "issuer": r["issuer"], "date": d, "w": r["value"] / total})
            prev_names = names
    ev = pd.DataFrame(events)
    tm = ticker_map()
    ev["ticker"] = ev["issuer"].map(norm).map(tm)
    unmapped = ev["ticker"].isna().mean()
    print(f"  issuer→ticker unmapped: {unmapped:.0%}")
    ev = ev.dropna(subset=["ticker"])
    if consensus > 1:
        ev["q"] = ev["date"].dt.to_period("Q")
        cnt = ev.groupby(["ticker", "q"])["fund"].nunique()
        ok = cnt[cnt >= consensus].index
        ev = ev[ev.set_index(["ticker", "q"]).index.isin(ok)]
        ev = ev.sort_values("date").groupby(["ticker", "q"], as_index=False).last()
    # one event per ticker per hold window
    ev = ev.sort_values("date")
    keep, last = [], {}
    for _, r in ev.iterrows():
        if (r["date"] - last.get(r["ticker"], pd.Timestamp("1900-01-01"))).days > 92:
            keep.append(r)
            last[r["ticker"]] = r["date"]
    return pd.DataFrame(keep)


def main():
    close, open_, _vol, member_at = load()
    variants = [
        ("baseline(w>=1%,63d)", {}, 63),
        ("w_0.5%", {"min_weight": 0.005}, 63),
        ("consensus_2", {"consensus": 2}, 63),
        ("hold_21", {}, 21),
        ("hold_126", {}, 126),
    ]
    cache = {}
    for label, lo, hi in (
        ("IN-SAMPLE 2023-26", "2023-01-01", "2027-01-01"),
        ("OUT-OF-SAMPLE 2016-22", "2016-01-01", "2023-01-01"),
    ):
        print(f"\n=== {label} ===")
        for name, kw, hold in variants:
            key = (tuple(sorted(kw.items())), hold)
            if key not in cache:
                ev = new_positions(**kw)
                cache[key] = study(ev, close, open_, member_at, hold=hold)
            res = cache[key]
            ev_report(name, res[(res["date"] >= lo) & (res["date"] < hi)])


if __name__ == "__main__":
    main()
