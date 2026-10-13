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


import io
import time
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

# ============================================================
# JOHN'S NSE 500 DATA DOWNLOADER
# SAFE VERSION
# ============================================================

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

DATA_DIR.mkdir(exist_ok=True)

UNIVERSE_FILE = ROOT / "universe.csv"
OHLCV_FILE = DATA_DIR / "sample_ohlcv.csv"

PERIOD = "1y"

NIFTY500_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/csv,text/plain,*/*",
}


# ============================================================
# DOWNLOAD NIFTY 500 UNIVERSE
# ============================================================


def download_nifty500_universe():

    print("=" * 70)
    print("DOWNLOADING NIFTY 500 UNIVERSE")
    print("=" * 70)

    try:
        response = requests.get(NIFTY500_URL, headers=HEADERS, timeout=30)

        print("NSE response:", response.status_code)

        response.raise_for_status()

        df = pd.read_csv(io.BytesIO(response.content))

        print("Columns:", list(df.columns))

        symbol_column = None

        for col in df.columns:
            if str(col).strip().lower() == "symbol":
                symbol_column = col
                break

        if symbol_column is None:
            raise RuntimeError("Nifty 500 Symbol column was not found.")

        result = pd.DataFrame()

        result["symbol"] = df[symbol_column].astype(str).str.strip()

        result = result[result["symbol"].notna()]

        result = result[result["symbol"].str.lower() != "nan"]

        result = result[result["symbol"] != ""]

        result = result.drop_duplicates(subset=["symbol"])

        if len(result) < 450:
            raise RuntimeError(f"Only {len(result)} stocks received. Expected approximately 500.")

        result["sector"] = "Nifty 500"

        result.to_csv(UNIVERSE_FILE, index=False)

        print(f"VALID NIFTY 500 UNIVERSE: {len(result)} stocks")

        return result

    except Exception as e:
        print()
        print("ERROR:", e)
        print()
        print("IMPORTANT: I will NOT use the old small universe.csv.")

        raise RuntimeError(
            "Nifty 500 universe download failed. "
            "Fix the universe/data source before "
            "running the backtest."
        )


# ============================================================
# DOWNLOAD DAILY OHLCV
# ============================================================


def download_ohlcv(universe):

    symbols = universe["symbol"].astype(str).str.strip().tolist()

    print()
    print("=" * 70)
    print("DOWNLOADING HISTORICAL OHLCV")
    print("=" * 70)

    print("Stocks:", len(symbols))
    print("Period:", PERIOD)
    print("Interval: 1D")
    print()

    yahoo_symbols = [symbol + ".NS" for symbol in symbols]

    all_data = []

    batch_size = 50

    for start in range(0, len(yahoo_symbols), batch_size):
        batch = yahoo_symbols[start : start + batch_size]

        print(
            f"Batch {start + 1}-{min(start + batch_size, len(yahoo_symbols))}/{len(yahoo_symbols)}"
        )

        try:
            data = yf.download(
                tickers=batch,
                period=PERIOD,
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=True,
            )

            if data.empty:
                print("No data returned.")
                continue

            if isinstance(data.columns, pd.MultiIndex):
                for yahoo_symbol in batch:
                    if yahoo_symbol not in data.columns.levels[0]:
                        continue

                    stock = data[yahoo_symbol].copy()

                    stock = stock.reset_index()

                    required = ["Date", "Open", "High", "Low", "Close", "Volume"]

                    if not all(c in stock.columns for c in required):
                        continue

                    stock = stock[required]

                    stock["symbol"] = yahoo_symbol.replace(".NS", "")

                    stock = stock.dropna(subset=["Close"])

                    all_data.append(stock)

        except Exception as e:
            print("Batch error:", e)

        time.sleep(2)

    if not all_data:
        raise RuntimeError("ZERO OHLCV DATA DOWNLOADED.")

    final = pd.concat(all_data, ignore_index=True)

    final = final.rename(
        columns={
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )

    final["date"] = pd.to_datetime(final["date"]).dt.strftime("%Y-%m-%d")

    final = final[["symbol", "date", "open", "high", "low", "close", "volume"]]

    final = final.sort_values(["symbol", "date"])

    final = final.drop_duplicates(subset=["symbol", "date"])

    stocks_found = final["symbol"].nunique()

    rows = len(final)

    print()
    print("=" * 70)
    print("DATA VALIDATION")
    print("=" * 70)

    print("Stocks with OHLCV:", stocks_found)

    print("Total rows:", rows)

    print("Date from:", final["date"].min())

    print("Date to:", final["date"].max())

    # --------------------------------------------------------
    # DO NOT ALLOW A TINY DATASET
    # --------------------------------------------------------

    if stocks_found < 400:
        raise RuntimeError(f"Only {stocks_found} stocks have data. Expected at least 400.")

    if rows < 50000:
        raise RuntimeError(
            f"Only {rows} OHLCV rows downloaded. Dataset is too small for the backtest."
        )

    final.to_csv(OHLCV_FILE, index=False)

    print()
    print("Saved:", OHLCV_FILE)

    print()
    print(final.head())

    return final


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print()
    print("=" * 70)
    print("JOHN'S NSE 500 DATA DOWNLOADER")
    print("=" * 70)
    print()

    universe = download_nifty500_universe()

    download_ohlcv(universe)

    print()
    print("DATA PREPARATION COMPLETED.")
