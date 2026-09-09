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


"""Corporate actions (splits + bonuses) → back-adjustment factors.

Unadjusted bhavcopy prices make every split look like a crash — a 10:1
split reads as a -90% gap. We fetch NSE's CA feed, parse the ratios out
of the free-text subject line, and back-adjust: all prices strictly
before the ex-date are multiplied by the factor, volumes divided.

Dividends and rights are ignored: small relative to momentum moves, and
parsing rights terms reliably is not worth the error surface.
"""
import re
from datetime import date, timedelta

import numpy as np
import pandas as pd
from ingest import nse

import config

CA_URL = "https://www.nseindia.com/api/corporates-corporateActions?index={segment}&from_date={frm}&to_date={to}"
# ETF corporate actions (e.g. the NIFTYBEES 10:1 split, Dec 2019) live in
# the 'mf' segment, NOT 'equities' — miss them and the benchmark "crashes".
SEGMENTS = ("equities", "mf")
OUT = config.DATA_DIR / "corporate_actions.parquet"

# "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- ..."
# Older records abbreviate: "Fv Splt Frm Rs 10 To Re 1"
SPLIT_RE = re.compile(r"fr?o?m\s+r[se]\.?\s*([\d.]+).*?to\s+r[se]\.?\s*([\d.]+)", re.IGNORECASE)
SPLIT_KEY = re.compile(r"spli?t", re.IGNORECASE)  # Split / Splt
# "Bonus 1:2" = 1 new share per 2 held
BONUS_RE = re.compile(r"bonus\s+(\d+)\s*:\s*(\d+)", re.IGNORECASE)


def fetch(start: date, end: date) -> pd.DataFrame:
    frames, d = [], start
    while d <= end:  # quarterly chunks; NSE dislikes big ranges
        q_end = min(d + timedelta(days=90), end)
        for seg in SEGMENTS:
            url = CA_URL.format(segment=seg, frm=d.strftime("%d-%m-%Y"), to=q_end.strftime("%d-%m-%Y"))
            r = nse.get(url, timeout=config.TIMEOUT)
            r.raise_for_status()
            rows = r.json()
            if rows:
                frames.append(pd.DataFrame(rows)[["symbol", "series", "subject", "exDate"]])
        d = q_end + timedelta(days=1)
    df = pd.concat(frames, ignore_index=True).drop_duplicates()
    df["exDate"] = pd.to_datetime(df["exDate"], format="%d-%b-%Y", errors="coerce")
    return df.dropna(subset=["exDate"])


def store(start: date, end: date) -> pd.DataFrame:
    df = fetch(start, end)
    if OUT.exists():  # merge with what we already have
        df = pd.concat([pd.read_parquet(OUT), df]).drop_duplicates(subset=["symbol", "subject", "exDate"])
    df.to_parquet(OUT, index=False)
    return df


def factor(subject: str) -> float:
    """Combined price-adjustment factor from one subject line (1.0 = none)."""
    f = 1.0
    if SPLIT_KEY.search(subject):
        m = SPLIT_RE.search(subject)
        if m and float(m.group(1)) > 0:
            f *= float(m.group(2)) / float(m.group(1))  # new_fv / old_fv
    m = BONUS_RE.search(subject)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        f *= b / (a + b)
    return f


# Clean ratios a split/bonus can produce: FV splits (10:1, 5:1, ...) and
# bonus (a+b)/b for small a,b. A crash almost never lands exactly on one.
_CLEAN = sorted(
    {o / n for o, n in [(10, 1), (10, 2), (10, 5), (5, 1), (5, 2), (2, 1), (4, 1)]}
    | {(a + b) / b for a in range(1, 11) for b in range(1, 11) if 1.75 <= (a + b) / b <= 12}
)


def implied_splits(df: pd.DataFrame, known: pd.DataFrame) -> pd.DataFrame:
    """Detect split-shaped gaps the CA feed missed. Conservative on purpose:
    require prev_close/open within 3% of a clean split ratio AND sustained
    volume scale-up — a false positive would erase a real crash from the
    backtest's loss book, which is the expensive direction to be wrong in.
    """
    events = []
    have = {(s, d.date()) for s, d in zip(known["symbol"], known["exDate"], strict=False)}
    for sym, g in df.groupby("symbol"):
        g = g.sort_values("date")
        ratio = g["close"].shift() / g["open"]
        # tick-size artifacts make penny-stock crashes land on clean ratios
        ratio[g["close"].shift() < 20] = np.nan
        for i in np.where(ratio >= 1.75)[0]:
            clean = min(_CLEAN, key=lambda c: abs(c - ratio.iloc[i]))
            if abs(clean / ratio.iloc[i] - 1) > 0.03:
                continue
            d = g["date"].iloc[i]
            if any((sym, (d + pd.Timedelta(days=k)).date()) in have for k in range(-5, 6)):
                continue  # feed already covers it
            vol_pre = g["volume"].iloc[max(0, i - 20) : i].median()
            vol_post = g["volume"].iloc[i : i + 10].median()
            if vol_pre > 0 and vol_post / vol_pre >= 1.5:
                events.append({"symbol": sym, "exDate": d, "factor": 1 / clean, "source": "implied"})
    return pd.DataFrame(events)


def adjust(df: pd.DataFrame) -> pd.DataFrame:
    """Back-adjust a long bhavcopy frame (symbol/date/OHLC/volume) in place."""
    if not OUT.exists():
        msg = "No corporate_actions.parquet — run the CA backfill."
        raise SystemExit(msg)
    ca = pd.read_parquet(OUT)
    from ingest import renames

    ca["symbol"] = renames.canonical(ca["symbol"])
    ca["factor"] = ca["subject"].map(factor)
    ca = ca[(ca["factor"] != 1.0) & (ca["factor"] > 0)]

    imp = implied_splits(df, ca)
    if len(imp):
        print(f"  CA: {len(imp)} implied splits not in the feed (saved to data/implied_splits.csv)")
        imp.to_csv(config.DATA_DIR / "implied_splits.csv", index=False)
        ca = pd.concat([ca[["symbol", "exDate", "factor"]], imp], ignore_index=True)

    px_cols = ["open", "high", "low", "close"]
    df[["volume", "deliv_qty"]] = df[["volume", "deliv_qty"]].astype("float64")
    for sym, grp in ca.groupby("symbol"):
        m_sym = df["symbol"] == sym
        if not m_sym.any():
            continue
        for _, row in grp.iterrows():
            m = m_sym & (df["date"] < row["exDate"])
            if m.any():
                df.loc[m, px_cols] *= row["factor"]
                for c in ("volume", "deliv_qty"):
                    df.loc[m, c] /= row["factor"]
    return df
