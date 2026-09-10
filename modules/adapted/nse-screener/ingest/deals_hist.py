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


"""Historical bulk + block deals, 2016→present (v5 raw material).

The JSON API silently truncates to 70 rows per response regardless of the
date window; the SAME endpoint with &csv=true returns everything. Fetched
in monthly chunks.

    python -m ingest.deals_hist          # backfill into data/deals_hist/
"""
import io
from datetime import date

import pandas as pd
from ingest import nse

import config

URL = "https://www.nseindia.com/api/historicalOR/bulk-block-short-deals?optionType={kind}&from={frm}&to={to}&csv=true"

COLS = {
    "date": "date",
    "symbol": "symbol",
    "security_name": "security_name",
    "client_name": "client_name",
    "buy_/_sell": "buy_sell",
    "quantity_traded": "qty",
    "trade_price_/_wght._avg._price": "price",
}


def fetch_month(year: int, month: int, kind: str) -> pd.DataFrame | None:
    frm = date(year, month, 1)
    to = (date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)) - pd.Timedelta(days=1)
    r = nse.get(
        URL.format(kind=f"{kind}_deals", frm=frm.strftime("%d-%m-%Y"), to=to.strftime("%d-%m-%Y")),
        timeout=config.TIMEOUT,
    )
    if r.status_code != 200 or not r.content.strip():
        return None
    df = pd.read_csv(io.BytesIO(r.content), encoding="utf-8-sig")
    df.columns = [c.strip().strip('"').strip().lower().replace(" ", "_") for c in df.columns]
    df = df.rename(columns=COLS)[list(COLS.values())]
    for c in df.select_dtypes("object"):
        df[c] = df[c].str.strip()
    df["date"] = pd.to_datetime(df["date"], format="%d-%b-%Y", errors="coerce")
    for c in ("qty", "price"):
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")
    df["kind"] = kind
    return df.dropna(subset=["date"])


def store_month(year: int, month: int) -> bool:
    out = config.DATA_DIR / "deals_hist" / f"{year}-{month:02d}.parquet"
    if out.exists():
        return True
    frames = [f for k in ("bulk", "block") if (f := fetch_month(year, month, k)) is not None and len(f)]
    if not frames:
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(frames, ignore_index=True).to_parquet(out, index=False)
    return True


def load_all() -> pd.DataFrame:
    files = sorted((config.DATA_DIR / "deals_hist").glob("*.parquet"))
    if not files:
        msg = "No deals history. Run: python -m ingest.deals_hist"
        raise SystemExit(msg)
    return pd.concat(map(pd.read_parquet, files), ignore_index=True)


if __name__ == "__main__":
    import time

    today, got = date.today(), 0
    for y in range(2016, today.year + 1):
        for m in range(1, 13):
            if (y, m) > (today.year, today.month):
                break
            try:
                if store_month(y, m):
                    got += 1
                time.sleep(config.SLEEP_SECS)
            except Exception as e:
                print(f"{y}-{m:02d}: {e} — continuing")
        print(f"{y} done")
    print(f"deals history: {got} months stored")
