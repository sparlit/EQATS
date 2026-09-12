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


"""Stock-futures daily data (F&O bhavcopy, FUTSTK rows only) — data/features
material per the owner's rule: F&O as INFORMATION, never traded.

    python -m ingest.futures      # 2016→now → data/futstk/
"""
import io
import time
from datetime import date, timedelta

import pandas as pd
from ingest import nse

import config

OLD = "https://nsearchives.nseindia.com/content/historical/DERIVATIVES/{yyyy}/{mon}/fo{ddmonyyyy}bhav.csv.zip"
NEW = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{yyyymmdd}_F_0000.csv.zip"
CUTOVER = date(2024, 7, 6)
DIR = config.DATA_DIR / "futstk"


def fetch(d: date) -> pd.DataFrame | None:
    if d < CUTOVER:
        url = OLD.format(yyyy=d.strftime("%Y"), mon=d.strftime("%b").upper(), ddmonyyyy=d.strftime("%d%b%Y").upper())
    else:
        url = NEW.format(yyyymmdd=d.strftime("%Y%m%d"))
    r = nse.get(url, timeout=config.TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    df = pd.read_csv(io.BytesIO(r.content), compression="zip", low_memory=False)
    if "INSTRUMENT" in df.columns:  # old format
        f = df[df["INSTRUMENT"] == "FUTSTK"]
        out = pd.DataFrame(
            {
                "symbol": f["SYMBOL"].str.strip(),
                "expiry": pd.to_datetime(f["EXPIRY_DT"], format="%d-%b-%Y", errors="coerce"),
                "close": f["CLOSE"],
                "settle": f["SETTLE_PR"],
                "oi": f["OPEN_INT"],
                "chg_oi": f["CHG_IN_OI"],
                "contracts": f["CONTRACTS"],
            }
        )
    else:  # UDiFF
        f = df[df["FinInstrmTp"] == "STF"]
        out = pd.DataFrame(
            {
                "symbol": f["TckrSymb"].astype(str).str.strip(),
                "expiry": pd.to_datetime(f["XpryDt"], errors="coerce"),
                "close": f["ClsPric"],
                "settle": f["SttlmPric"],
                "oi": f["OpnIntrst"],
                "chg_oi": f["ChngInOpnIntrst"],
                "contracts": f["TtlTradgVol"],
            }
        )
    out["date"] = pd.to_datetime(d)
    return out.dropna(subset=["expiry"])


if __name__ == "__main__":
    DIR.mkdir(parents=True, exist_ok=True)
    d, got = date(2016, 1, 1), 0
    while d <= date.today():
        if d.weekday() < 5:
            f = DIR / f"{d.isoformat()}.parquet"
            if not f.exists():
                try:
                    w = fetch(d)
                    if w is not None and len(w):
                        w.to_parquet(f, index=False)
                        got += 1
                    time.sleep(1.0)
                except Exception as e:
                    print(f"{d}: {e} — continuing")
        d += timedelta(days=1)
        if got and got % 100 == 0:
            print(f"{got} days stored, at {d}")
    print(f"futstk backfill done: {got} days")
