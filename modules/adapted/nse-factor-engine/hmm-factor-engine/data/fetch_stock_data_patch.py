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
fetch_stock_data_patch.py — safe incremental fetch
Each batch saved to its own temp file. Final merge at end.
Re-running skips already-saved batches.
"""

import time
from pathlib import Path

import pandas as pd
import yfinance as yf

START_DATE = "2013-01-01"
END_DATE = "2026-08-12"
BATCH_SIZE = 20
SLEEP_BATCH = 3

CONSTITUENT_CSV = Path(
    "/home/ec2-user/nse-factor-engine/nifty_constituent_history/nifty500_2005-01-01_to_2026-06-30.csv"
)
OUTPUT_DIR = Path(__file__).parent
PRICE_FILE = OUTPUT_DIR / "prices_hmm_daily.parquet"
VOLUME_FILE = OUTPUT_DIR / "prices_hmm_daily_volume.parquet"
TEMP_DIR = OUTPUT_DIR / "fetch_temp"

RENAME_MAP = {
    "8KMILES": "SECURKLOUD",
    "ADLABS": "IMAGICAA",
    "AKZOINDIA": "JSWDULUX",
    "APPAPER": "IPAPPM",
    "CENTURYTEX": "ABREL",
    "EXCEL": "LANDSMILL",
    "GSKCONS": "HINDUNILVR",
    "GUJGASLTD": "GUJENERGY",
    "IBVENTURES": "DHANI",
    "INFIBEAM": "CCAVENUE",
    "MERCK": "PGHL",
    "MOTHERSUMI": "MOTHERSON",
    "ORIENTREF": "RHIM",
    "SEQUENT": "VIYASH",
    "SKSMICRO": "BHARATFIN",
    "SMLISUZU": "SMLMAH",
    "TATAMOTORS": "TMPV",
    "TATASPONGE": "TATASTLLP",
    "UCALFUEL": "UCAL",
    "WIDIA": "KENNAMET",
    "ALSTOMT&D": "GVT&D",
}

NEW_SYMBOLS = [
    "BALAMINES",
    "CEMPRO",
    "EQUITASBNK",
    "GARFIBRES",
    "GRWRHITECH",
    "ICICIBANK",
    "JUBLINGREA",
    "LTM",
    "M&M",
    "MOTILALOFS",
    "PATANJALI",
    "PENIND",
    "REPRO",
    "UJJIVANSFB",
    "HDFCBANK",
]


def load_universe() -> list:
    df = pd.read_csv(CONSTITUENT_CSV)
    all_syms = set()
    for s in df["symbols"].dropna():
        for sym in str(s).split(","):
            sym = sym.strip()
            if sym:
                all_syms.add(sym)
    all_syms.update(NEW_SYMBOLS)
    all_syms.update(RENAME_MAP.values())
    return sorted(all_syms)


def fetch_batch(tickers_ns: list) -> pd.DataFrame:
    try:
        raw = yf.download(tickers_ns, start=START_DATE, end=END_DATE, auto_adjust=True, progress=False, threads=True)
    except Exception as e:
        print(f"ERROR: {e}")
        return pd.DataFrame()

    if raw.empty:
        return pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns.names = ["field", "ticker"]
        df = raw.stack(level="ticker", future_stack=True).reset_index()
        df.columns = df.columns.str.strip().str.lower()
        df = df.rename(columns={"ticker": "symbol"})
    else:
        df = raw.reset_index()
        df.columns = df.columns.str.strip().str.lower()
        df["symbol"] = tickers_ns[0].replace(".NS", "")

    df["symbol"] = df["symbol"].str.replace(".NS", "", regex=False)
    df["date"] = pd.to_datetime(df["date"])
    cols = ["symbol", "date", "open", "high", "low", "close", "volume"]
    df = df[[c for c in cols if c in df.columns]].dropna(subset=["close"])
    df = df[df["volume"] > 0]
    return df


def main():
    TEMP_DIR.mkdir(exist_ok=True)

    all_tickers = load_universe()
    tickers_ns = [f"{t}.NS" for t in all_tickers]
    total_batches = (len(tickers_ns) + BATCH_SIZE - 1) // BATCH_SIZE

    print(f"Total tickers : {len(all_tickers)}")
    print(f"Total batches : {total_batches}")
    print(f"Temp dir      : {TEMP_DIR}")

    # ── Fetch batches — skip already saved ────────────────────────
    for i in range(0, len(tickers_ns), BATCH_SIZE):
        batch_num = i // BATCH_SIZE + 1
        batch = tickers_ns[i : i + BATCH_SIZE]
        temp_file = TEMP_DIR / f"batch_{batch_num:04d}.parquet"

        if temp_file.exists():
            print(f"  Batch {batch_num}/{total_batches}: SKIP (already saved)")
            continue

        syms = [t.replace(".NS", "") for t in batch]
        print(f"  Batch {batch_num}/{total_batches}: {syms[0]}..{syms[-1]}", end=" ", flush=True)

        df = fetch_batch(batch)

        if df.empty:
            print("EMPTY")
            # Save empty marker so we don't retry
            pd.DataFrame().to_parquet(temp_file)
        else:
            df.to_parquet(temp_file, index=False)
            print(f"→ {df['symbol'].nunique()} symbols, {len(df)} rows saved")

        time.sleep(SLEEP_BATCH)

    # ── Merge all temp files ───────────────────────────────────────
    print("\nMerging all batches ...")
    parts = []
    for f in sorted(TEMP_DIR.glob("batch_*.parquet")):
        try:
            df = pd.read_parquet(f)
            if not df.empty:
                parts.append(df)
        except Exception:
            pass

    if not parts:
        print("ERROR: no data to merge")
        return

    combined = pd.concat(parts, ignore_index=True)
    combined = combined.drop_duplicates(subset=["symbol", "date"], keep="last")
    combined = combined.sort_values(["symbol", "date"]).reset_index(drop=True)

    # ── Apply renames ──────────────────────────────────────────────
    print("Applying renames ...")
    extra = []
    for old_sym, new_sym in RENAME_MAP.items():
        new_rows = combined[combined["symbol"] == new_sym].copy()
        old_rows = combined[combined["symbol"] == old_sym]
        if new_rows.empty or not old_rows.empty:
            continue
        old_copy = new_rows.copy()
        old_copy["symbol"] = old_sym
        extra.append(old_copy)
        print(f"  {old_sym} <- {new_sym}: {len(old_copy)} rows")

    if extra:
        combined = pd.concat([combined, *extra], ignore_index=True)
        combined = combined.drop_duplicates(subset=["symbol", "date"], keep="last")
        combined = combined.sort_values(["symbol", "date"]).reset_index(drop=True)

    # ── Save final outputs ─────────────────────────────────────────
    print("\nSaving prices parquet ...")
    combined.to_parquet(PRICE_FILE, index=False)
    print(f"  Symbols : {combined['symbol'].nunique()}")
    print(f"  Rows    : {len(combined)}")
    print(f"  Dates   : {combined['date'].min().date()} -> {combined['date'].max().date()}")

    print("\nBuilding volume parquet ...")
    volume = combined.pivot_table(index="date", columns="symbol", values="volume", aggfunc="last")
    volume.index = pd.to_datetime(volume.index)
    volume.index.name = None
    volume.columns.name = None
    volume.to_parquet(VOLUME_FILE)
    print(f"  Shape : {volume.shape}")
    print("\nDone.")


if __name__ == "__main__":
    main()
