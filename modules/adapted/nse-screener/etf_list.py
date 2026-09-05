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

import config
from ingest import nse

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
