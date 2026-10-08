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


"""
Stage 4 — Metric: Lower Circuit Hits (63-day window)

Counts the number of days in the past 63 trading days where a stock's
daily return hit or breached its lower circuit limit.

Circuit limits sourced from NSE sec_list:
  - Non-F&O stocks : use assigned band (2 / 5 / 10 / 20 / 40 %)
  - F&O / No Band  : treated as 20%
  - Not in sec_list: treated as 20% (NSE default)

Used in Stage 6 G6 gate: lower_circuit_hits_63d == 0 to exclude
distressed stocks regardless of whether their circuit is 5% or 20%.

Inputs : prices (full price history), T, all_dates, band_map (optional)
Returns: dataframe with columns [symbol, lower_circuit_hits_63d]
"""

from io import StringIO

import pandas as pd
import requests

SEC_LIST_URL = "https://nsearchives.nseindia.com/content/equities/sec_list.csv"


def fetch_band_map() -> dict:
    """
    Fetch current price band per symbol from NSE sec_list.
    Returns {SYMBOL_UPPER: band_str} e.g. {"CPPLUS": "5", "RELIANCE": "No Band"}
    Call once in stage4_assemble.py and pass result into compute().
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.nseindia.com/",
        }
        resp = requests.get(SEC_LIST_URL, timeout=15, headers=headers)
        resp.raise_for_status()
        sl = pd.read_csv(StringIO(resp.text))
        sl["Symbol"] = sl["Symbol"].str.strip().str.upper()
        band_map = sl.set_index("Symbol")["Band"].to_dict()
        print(f"sec_list fetched: {len(band_map)} symbols")
        return band_map
    except Exception as exc:
        print(f"WARNING: could not fetch sec_list ({exc}). Defaulting all bands to 20%.")
        return {}


def _band_threshold(symbol: str, band_map: dict) -> float:
    """Return lower circuit threshold as a fraction (e.g. 0.05 for 5%)."""
    b = band_map.get(symbol.upper().replace(".NS", ""))
    if b is None or b == "No Band":
        return 0.20
    return int(b) / 100


def compute(
    prices: pd.DataFrame,
    T,
    all_dates: list,
    band_map: dict = None,
) -> pd.DataFrame:
    """
    prices    : full prices.parquet (symbol, date, close, ...)
    T         : robustly-resolved T (date)
    all_dates : sorted list of trading dates <= T
    band_map  : {SYMBOL: band_str} from fetch_band_map().
                If None, fetched fresh (use pre-fetched in assembler).

    Returns DataFrame: symbol, lower_circuit_hits_63d
    """
    if band_map is None:
        band_map = fetch_band_map()

    # (T_63, T] → exactly 63 daily returns
    T_63 = all_dates[-64]

    window = (
        prices[(prices["date"] > T_63) & (prices["date"] <= T)]
        .copy()
        .sort_values(["symbol", "date"])
    )
    window["daily_ret"] = window.groupby("symbol")["close"].pct_change()
    window = window.dropna(subset=["daily_ret"])

    window["threshold"] = window["symbol"].map(lambda s: _band_threshold(s, band_map))
    window["hit"] = window["daily_ret"] <= -(window["threshold"] - 0.001)

    result = (
        window.groupby("symbol")["hit"]
        .sum()
        .astype(int)
        .rename("lower_circuit_hits_63d")
        .reset_index()
    )

    n_hits = (result["lower_circuit_hits_63d"] >= 1).sum()
    print(
        f"lower_circuit_hits_63d: {len(result)} symbols computed. "
        f"{n_hits} with >= 1 lower circuit hit in 63-day window."
    )

    return result


if __name__ == "__main__":
    import pandas as pd

    BASE = "/home/ec2-user/nse-factor-engine"

    px = pd.read_parquet(f"{BASE}/data/prices.parquet")
    date_counts = px.groupby("date")["symbol"].count()
    T = date_counts[date_counts >= 490].index.max()
    all_dates = sorted(px[px["date"] <= T]["date"].unique())

    print(f"T = {T.date()}")

    band_map = fetch_band_map()
    print(f"CPPLUS band : {band_map.get('CPPLUS', band_map.get('CPPLUS.NS', 'NOT FOUND'))}")

    result = compute(px, T, all_dates, band_map=band_map)

    print(f"\nShape: {result.shape}")
    print(
        f"\nDistribution:\n{result['lower_circuit_hits_63d'].value_counts().sort_index().head(15).to_string()}"
    )
    print(f"\nCPPLUS:\n{result[result['symbol'].str.startswith('CPPLUS')].to_string(index=False)}")
    print(
        f"\nTop 15:\n{result.sort_values('lower_circuit_hits_63d', ascending=False).head(15).to_string(index=False)}"
    )
