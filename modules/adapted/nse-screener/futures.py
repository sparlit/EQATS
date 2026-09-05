"""Stock-futures daily data (F&O bhavcopy, FUTSTK rows only) — data/features
material per the owner's rule: F&O as INFORMATION, never traded.

    python -m ingest.futures      # 2016→now → data/futstk/
"""
import io
import time
from datetime import date, timedelta

import pandas as pd

import config
from ingest import nse

OLD = ("https://nsearchives.nseindia.com/content/historical/DERIVATIVES/"
       "{yyyy}/{mon}/fo{ddmonyyyy}bhav.csv.zip")
NEW = ("https://nsearchives.nseindia.com/content/fo/"
       "BhavCopy_NSE_FO_0_0_0_{yyyymmdd}_F_0000.csv.zip")
CUTOVER = date(2024, 7, 6)
DIR = config.DATA_DIR / "futstk"


def fetch(d: date) -> pd.DataFrame | None:
    if d < CUTOVER:
        url = OLD.format(yyyy=d.strftime("%Y"), mon=d.strftime("%b").upper(),
                         ddmonyyyy=d.strftime("%d%b%Y").upper())
    else:
        url = NEW.format(yyyymmdd=d.strftime("%Y%m%d"))
    r = nse.get(url, timeout=config.TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    df = pd.read_csv(io.BytesIO(r.content), compression="zip",
                     low_memory=False)
    if "INSTRUMENT" in df.columns:                    # old format
        f = df[df["INSTRUMENT"] == "FUTSTK"]
        out = pd.DataFrame({
            "symbol": f["SYMBOL"].str.strip(),
            "expiry": pd.to_datetime(f["EXPIRY_DT"], format="%d-%b-%Y",
                                     errors="coerce"),
            "close": f["CLOSE"], "settle": f["SETTLE_PR"],
            "oi": f["OPEN_INT"], "chg_oi": f["CHG_IN_OI"],
            "contracts": f["CONTRACTS"]})
    else:                                             # UDiFF
        f = df[df["FinInstrmTp"] == "STF"]
        out = pd.DataFrame({
            "symbol": f["TckrSymb"].astype(str).str.strip(),
            "expiry": pd.to_datetime(f["XpryDt"], errors="coerce"),
            "close": f["ClsPric"], "settle": f["SttlmPric"],
            "oi": f["OpnIntrst"], "chg_oi": f["ChngInOpnIntrst"],
            "contracts": f["TtlTradgVol"]})
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
