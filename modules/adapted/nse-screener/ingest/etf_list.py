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


"""Current NSE ETF list. ETFs trade in the EQ series so they leak into a
'stock' universe silently — the v2 backtest's top two winners were silver
ETFs, i.e. an accidental leveraged commodity bet. We exclude them from
candidate pools (the benchmark ETF is read from the price panel directly,
so exclusion doesn't affect it).

Caveat: this is today's list, applied to all of history. ETFs delisted
before today would still leak into old backtest windows; acceptable —
the big AUM ETFs that dominate signals are all long-lived.
"""
import pandas as pd
from ingest import nse

import config

ETF_URL = "https://www.nseindia.com/api/etf"
OUT = config.DATA_DIR / "etf_list.parquet"


def store() -> set[str]:
    r = nse.get(ETF_URL, timeout=config.TIMEOUT)
    r.raise_for_status()
    df = pd.DataFrame(r.json()["data"])[["symbol", "assets"]]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    return set(df["symbol"])


def symbols() -> set[str]:
    if not OUT.exists():
        return store()
    return set(pd.read_parquet(OUT)["symbol"])
